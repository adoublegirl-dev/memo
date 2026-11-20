import argparse
import base64
import getpass
import hashlib
import json
import os
import time
import socket
import posixpath
import shlex
from urllib.parse import unquote, urlparse

import paramiko
from cryptography.hazmat.primitives import serialization
from pathlib import Path

# ---- 服务器连接配置：通过环境变量提供，切勿硬编码 ----
#   MEMO_SERVER_HOST   服务器地址
#   MEMO_SERVER_PORT   SSH 端口（默认 22）
#   MEMO_SERVER_USER   登录用户
#   MEMO_REMOTE_ROOT   服务器上的官网根目录
HOST = os.getenv('MEMO_SERVER_HOST', '').strip()
PORT = int(os.getenv('MEMO_SERVER_PORT', '22') or '22')
USER = os.getenv('MEMO_SERVER_USER', '').strip()
REMOTE_ROOT = os.getenv('MEMO_REMOTE_ROOT', '/root/MEMO/guanwang').strip()

SIGNING_KEY_ID = 'memo-ed25519-21a636a075e5bc03'
SIGNING_PUBLIC_KEY = b'''-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAmtf08uuRTatRP8V90m94R7WTArYtFj73AjzWWFTrOZ8=
-----END PUBLIC KEY-----
'''

# ---- 本地路径：默认基于仓库根推算，可用环境变量覆盖 ----
REPO_ROOT = Path(__file__).resolve().parent.parent
WEBSITE_DIR = REPO_ROOT / 'website'
# 打包产物目录（安装包 / 服务包），默认取仓库同级目录，可用 MEMO_BUILD_ROOT 覆盖
BUILD_ROOT = Path(os.getenv('MEMO_BUILD_ROOT', str(REPO_ROOT.parent / 'Memo_Installer')))

LOCAL_FILES = [
    (str(WEBSITE_DIR / 'index-glass.html'), 'index.html'),
    (str(WEBSITE_DIR / 'mobile.html'), 'mobile.html'),
    (str(WEBSITE_DIR / 'boot-visual.html'), 'boot-visual.html'),
    (str(WEBSITE_DIR / 'assets' / 'memo-bg.png'), 'assets/memo-bg.png'),
    # Signed/versioned assets first. The signed manifest is activated only after
    # every referenced file exists; website convenience aliases are refreshed last.
    (str(BUILD_ROOT / 'build' / 'Memo Setup 0.10.8-alpha.4.exe'), 'downloads/Memo Setup 0.10.8-alpha.4.exe'),
    (str(BUILD_ROOT / 'build-lite' / 'Memo Lite Setup 0.10.8-alpha.4.exe'), 'downloads/Memo Lite Setup 0.10.8-alpha.4.exe'),
    (str(BUILD_ROOT / 'artifacts' / 'Memo-Service-0.10.8-alpha.4.zip'), 'downloads/service/Memo-Service-0.10.8-alpha.4.zip'),
    (str(BUILD_ROOT / 'artifacts' / 'service-v2' / 'Memo-Service-0.10.8-alpha_to_0.10.8-alpha.2.zip'), 'downloads/service/Memo-Service-0.10.8-alpha_to_0.10.8-alpha.2.zip'),
    (str(BUILD_ROOT / 'artifacts' / 'service' / 'Memo-Service-0.10.8-alpha.2_to_0.10.8-alpha.4.zip'), 'downloads/service/Memo-Service-0.10.8-alpha.2_to_0.10.8-alpha.4.zip'),
    (str(WEBSITE_DIR / 'downloads' / 'latest.json'), 'downloads/latest.json'),
    (str(BUILD_ROOT / 'build' / 'Memo-Setup-latest.exe'), 'downloads/Memo-Setup-latest.exe'),
    (str(BUILD_ROOT / 'build-lite' / 'Memo-Lite-Setup-latest.exe'), 'downloads/Memo-Lite-Setup-latest.exe'),
]

def run(ssh, cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    code = stdout.channel.recv_exit_status()
    if code != 0:
        raise RuntimeError(f'Command failed {code}: {cmd}\nSTDOUT:{out}\nSTDERR:{err}')
    return out.strip()

def ensure_remote_dir(sftp, remote_dir):
    parts = remote_dir.strip('/').split('/')
    cur = ''
    for part in parts:
        cur += '/' + part
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            sftp.mkdir(cur)

def close_connection(ssh, sftp):
    try:
        if sftp:
            sftp.close()
    except Exception:
        pass
    try:
        if ssh:
            ssh.close()
    except Exception:
        pass


def resumable_tmp_path(sftp, remote_path):
    remote_dir = posixpath.dirname(remote_path)
    base = posixpath.basename(remote_path)
    candidates = []
    for name in sftp.listdir(remote_dir):
        if name == base + '.uploading' or name.startswith(base + '.uploading-'):
            path = posixpath.join(remote_dir, name)
            try:
                candidates.append((sftp.stat(path).st_size, path))
            except OSError:
                pass
    return max(candidates, default=(0, remote_path + '.uploading'))


def local_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_manifest_bytes(manifest):
    unsigned = {key: value for key, value in manifest.items() if key != 'signature'}
    return json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def verify_manifest_signature(manifest):
    signature = manifest.get('signature') or {}
    if manifest.get('formatVersion') != 3 or manifest.get('signatureVersion') != 1:
        raise RuntimeError('latest.json is not a supported signed release manifest')
    if signature.get('algorithm') != 'Ed25519' or signature.get('keyId') != SIGNING_KEY_ID:
        raise RuntimeError('latest.json uses an unknown or invalid signing key')
    try:
        signature_bytes = base64.b64decode(str(signature.get('value') or ''), validate=True)
        public_key = serialization.load_pem_public_key(SIGNING_PUBLIC_KEY)
        public_key.verify(signature_bytes, canonical_manifest_bytes(manifest))
    except Exception as exc:
        raise RuntimeError('latest.json Ed25519 signature verification failed') from exc


def normalized_sha256(value):
    return str(value or '').lower().removeprefix('sha256:')


def signed_asset_rel(item, folder='downloads'):
    name = str(item.get('name') or '')
    if not name or os.path.basename(name) != name or name in ('.', '..'):
        raise RuntimeError(f'Unsafe signed asset name: {name}')
    return f'{folder}/{name}'


def validate_asset(item, remote_rel):
    local_path = next(local for local, item_rel in LOCAL_FILES if item_rel == remote_rel)
    actual_size = os.path.getsize(local_path)
    actual_hash = local_sha256(local_path)
    if int(item.get('size') or 0) != actual_size:
        raise RuntimeError(f'{remote_rel} size does not match latest.json: {actual_size} != {item.get("size")}')
    if normalized_sha256(item.get('sha256')) != actual_hash:
        raise RuntimeError(f'{remote_rel} SHA256 does not match latest.json: {actual_hash}')
    url_path = unquote(urlparse(str(item.get('url') or '')).path).lstrip('/')
    if url_path != remote_rel:
        raise RuntimeError(f'{remote_rel} URL does not match upload destination: {url_path}')


def validate_release_manifest():
    manifest_path = next(local for local, rel in LOCAL_FILES if rel == 'downloads/latest.json')
    with open(manifest_path, 'r', encoding='utf-8') as handle:
        manifest = json.load(handle)
    verify_manifest_signature(manifest)
    if not manifest.get('version') or not manifest.get('serviceVersion'):
        raise RuntimeError('latest.json missing launcher or service version')
    launcher = manifest.get('launcher') or {}
    service = manifest.get('service') or {}
    launcher_full = launcher.get('full') or {}
    launcher_lite = launcher.get('lite') or {}
    full_rel = signed_asset_rel(launcher_full)
    lite_rel = signed_asset_rel(launcher_lite)
    validate_asset(launcher_full, full_rel)
    validate_asset(launcher_lite, lite_rel)
    if manifest.get('full') != launcher_full or manifest.get('lite') != launcher_lite:
        raise RuntimeError('Legacy Full/Lite fields differ from signed launcher assets')
    service_full = service.get('full') or {}
    validate_asset(service_full, signed_asset_rel(service_full, 'downloads/service'))
    for patch in service.get('patches') or []:
        validate_asset(patch, signed_asset_rel(patch, 'downloads/service'))
    # Convenience aliases are not referenced by the signed manifest, but must
    # contain the exact same bytes for direct website downloads.
    for versioned_rel, alias_rel in (
        (full_rel, 'downloads/Memo-Setup-latest.exe'),
        (lite_rel, 'downloads/Memo-Lite-Setup-latest.exe'),
    ):
        versioned = next(local for local, rel in LOCAL_FILES if rel == versioned_rel)
        alias = next(local for local, rel in LOCAL_FILES if rel == alias_rel)
        if os.path.getsize(versioned) != os.path.getsize(alias) or local_sha256(versioned) != local_sha256(alias):
            raise RuntimeError(f'Website alias differs from signed asset: {alias_rel}')
    print(f'Signed local release manifest verified: launcher={manifest["version"]}, service={manifest["serviceVersion"]}')


def reconnect_pair(password, ssh=None, sftp=None, delay=2):
    close_connection(ssh, sftp)
    if delay:
        time.sleep(delay)
    ssh = connect_ssh(password)
    transport = ssh.get_transport()
    if transport:
        transport.set_keepalive(20)
    sftp = ssh.open_sftp()
    sftp.get_channel().settimeout(120)
    return ssh, sftp


def upload_large_in_parts(ssh, sftp, password, local_path, remote_rel, part_size=8 * 1024 * 1024):
    remote_path = posixpath.join(REMOTE_ROOT, remote_rel)
    remote_dir = posixpath.dirname(remote_path)
    size = os.path.getsize(local_path)
    expected_hash = local_sha256(local_path)
    part_dir = remote_path + f'.parts-{expected_hash[:12]}'
    tmp_path = remote_path + '.uploading-parts'
    part_count = (size + part_size - 1) // part_size
    started = time.time()
    ensure_remote_dir(sftp, remote_dir)
    try:
        sftp.stat(part_dir)
    except FileNotFoundError:
        sftp.mkdir(part_dir)
    print(f'Uploading {remote_rel} in {part_count} verified parts of at most {part_size/1024/1024:.0f} MB')

    with open(local_path, 'rb') as source:
        for index in range(part_count):
            source.seek(index * part_size)
            data = source.read(min(part_size, size - index * part_size))
            part_name = f'part-{index:05d}.bin'
            part_path = posixpath.join(part_dir, part_name)
            part_hash = hashlib.sha256(data).hexdigest()
            complete = False
            for attempt in range(1, 11):
                try:
                    try:
                        remote_size = sftp.stat(part_path).st_size
                    except FileNotFoundError:
                        remote_size = -1
                    if remote_size == len(data):
                        remote_hash = run(ssh, f'sha256sum {shlex.quote(part_path)}').split()[0].lower()
                        if remote_hash == part_hash:
                            complete = True
                            break
                    with sftp.file(part_path, 'wb') as target:
                        for offset in range(0, len(data), 256 * 1024):
                            target.write(data[offset:offset + 256 * 1024])
                        target.flush()
                    if sftp.stat(part_path).st_size != len(data):
                        raise IOError(f'part size mismatch: {part_name}')
                    remote_hash = run(ssh, f'sha256sum {shlex.quote(part_path)}').split()[0].lower()
                    if remote_hash != part_hash:
                        raise IOError(f'part SHA256 mismatch: {part_name}')
                    complete = True
                    break
                except Exception as exc:
                    if attempt >= 10:
                        raise
                    print(f'  Part {index + 1}/{part_count} interrupted: {type(exc).__name__}: {exc}', flush=True)
                    ssh, sftp = reconnect_pair(password, ssh, sftp, min(attempt * 5, 30))
            if not complete:
                raise RuntimeError(f'Part upload failed: {part_name}')
            sent = min((index + 1) * part_size, size)
            print(f'  {remote_rel}: part {index + 1}/{part_count}, {sent/1024/1024:.1f}/{size/1024/1024:.1f} MB ({sent/size*100:.1f}%)', flush=True)
            # Stay below the observed 40-53 MB connection cutoff.
            if (index + 1) % 4 == 0 and index + 1 < part_count:
                ssh, sftp = reconnect_pair(password, ssh, sftp, 2)

    # Quote the directory, but leave the fixed wildcard for shell expansion.
    quoted_glob = shlex.quote(part_dir) + '/part-*.bin'
    run(ssh, f'cat {quoted_glob} > {shlex.quote(tmp_path)}')
    remote_size = int(run(ssh, f'stat -c %s {shlex.quote(tmp_path)}'))
    if remote_size != size:
        raise IOError(f'assembled size mismatch: {remote_size} != {size}')
    remote_hash = run(ssh, f'sha256sum {shlex.quote(tmp_path)}').split()[0].lower()
    if remote_hash != expected_hash:
        raise IOError(f'assembled SHA256 mismatch for {remote_rel}')
    run(ssh, f'mv -f {shlex.quote(tmp_path)} {shlex.quote(remote_path)} && rm -rf {shlex.quote(part_dir)}')
    print(f'Uploaded {remote_rel} in {time.time()-started:.1f}s; assembled SHA256 verified')
    return ssh, sftp


def upload_atomic(ssh, sftp, password, local_path, remote_rel, max_attempts=10):
    remote_path = posixpath.join(REMOTE_ROOT, remote_rel)
    remote_dir = posixpath.dirname(remote_path)
    size = os.path.getsize(local_path)
    if size >= 32 * 1024 * 1024:
        return upload_large_in_parts(ssh, sftp, password, local_path, remote_rel)
    expected_hash = local_sha256(local_path)
    started = time.time()
    print(f'Uploading {remote_rel} ({size/1024/1024:.1f} MB)')

    for attempt in range(1, max_attempts + 1):
        try:
            ensure_remote_dir(sftp, remote_dir)
            offset, tmp_path = resumable_tmp_path(sftp, remote_path)
            if offset > size:
                sftp.remove(tmp_path)
                offset = 0
            if offset:
                print(f'  Resume from {offset/1024/1024:.1f} MB (attempt {attempt}/{max_attempts})', flush=True)
            mode = 'r+b' if offset else 'wb'
            sent = offset
            reported = offset
            with open(local_path, 'rb') as source, sftp.file(tmp_path, mode) as target:
                source.seek(offset)
                target.seek(offset)
                while True:
                    chunk = source.read(512 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
                    sent += len(chunk)
                    if sent == size or sent - reported >= 20 * 1024 * 1024:
                        reported = sent
                        print(f'  {remote_rel}: {sent/1024/1024:.1f}/{size/1024/1024:.1f} MB ({sent/size*100:.1f}%)', flush=True)
                target.flush()
            remote_size = sftp.stat(tmp_path).st_size
            if remote_size != size:
                raise IOError(f'remote size mismatch: {remote_size} != {size}')
            remote_hash = run(ssh, f'sha256sum {shlex.quote(tmp_path)}').split()[0].lower()
            if remote_hash != expected_hash:
                raise IOError(f'remote SHA256 mismatch for {remote_rel}')
            try:
                sftp.posix_rename(tmp_path, remote_path)
            except Exception:
                try:
                    sftp.remove(remote_path)
                except FileNotFoundError:
                    pass
                sftp.rename(tmp_path, remote_path)
            print(f'Uploaded {remote_rel} in {time.time()-started:.1f}s; SHA256 verified')
            return ssh, sftp
        except Exception as exc:
            if attempt >= max_attempts:
                raise
            print(f'  Upload interrupted: {type(exc).__name__}: {exc}', flush=True)
            print(f'  Reconnecting in {min(5 * attempt, 30)}s; partial file will be resumed.', flush=True)
            ssh, sftp = reconnect_pair(password, ssh, sftp, min(5 * attempt, 30))
    raise RuntimeError(f'Upload retries exhausted: {remote_rel}')


def connect_ssh(password):
    last_error = None
    for attempt in range(1, 6):
        try:
            print(f'Connecting to {HOST}:{PORT} ... attempt {attempt}/5', flush=True)
            sock = socket.create_connection((HOST, PORT), timeout=25)
            sock.settimeout(75)
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                HOST,
                PORT,
                USER,
                password,
                sock=sock,
                timeout=30,
                banner_timeout=75,
                auth_timeout=45,
                look_for_keys=False,
                allow_agent=False,
            )
            transport = ssh.get_transport()
            if transport:
                transport.set_keepalive(20)
            return ssh
        except Exception as exc:
            last_error = exc
            print(f'Connect failed: {type(exc).__name__}: {exc}', flush=True)
            time.sleep(3 * attempt)
    raise last_error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe-only', action='store_true', help='只更新签名发布资产（Full/Lite/Service Patch/latest.json），不更新网页和图片')
    parser.add_argument('--validate-only', action='store_true', help='仅执行本地签名与发布资产校验，不连接服务器')
    args = parser.parse_args()
    release_only = args.exe_only or args.validate_only
    selected_files = [item for item in LOCAL_FILES if item[1].startswith('downloads/')] if release_only else LOCAL_FILES

    for local, rel in selected_files:
        if not os.path.exists(local):
            raise FileNotFoundError(local)
    if release_only:
        validate_release_manifest()
    if args.validate_only:
        print('VALIDATION_ONLY_OK: no server connection was opened')
        return

    if not HOST or not USER:
        raise SystemExit(
            '未配置服务器连接信息。请先设置环境变量：\n'
            '  MEMO_SERVER_HOST  服务器地址（必填）\n'
            '  MEMO_SERVER_PORT  SSH 端口（默认 22）\n'
            '  MEMO_SERVER_USER  登录用户（必填）\n'
            '  MEMO_SERVER_PASSWORD  登录密码（不设则交互输入）'
        )

    password = os.getenv('MEMO_SERVER_PASSWORD') or getpass.getpass(f'SSH password for {USER}@{HOST}:{PORT}: ')
    ssh = connect_ssh(password)
    sftp = ssh.open_sftp()
    sftp.get_channel().settimeout(120)
    ts = time.strftime('%Y%m%d-%H%M%S')
    backup_dir = posixpath.join(REMOTE_ROOT, f'_backup_{ts}')

    print('Remote:', run(ssh, 'hostname && pwd'))
    run(ssh, f'mkdir -p {REMOTE_ROOT}/assets {REMOTE_ROOT}/downloads/service {backup_dir}')
    existing = run(ssh, f'find {REMOTE_ROOT} -maxdepth 2 -type f | sort | sed "s#{REMOTE_ROOT}/##" | head -80')
    print('Existing files preview:\n' + existing)

    backup_targets = [rel for _local, rel in selected_files]
    for rel in backup_targets:
        src = posixpath.join(REMOTE_ROOT, rel)
        dst = posixpath.join(backup_dir, rel)
        run(ssh, f'if [ -f "{src}" ]; then mkdir -p "$(dirname "{dst}")"; cp -a "{src}" "{dst}"; fi')
    print('Backup created:', backup_dir)

    for local, rel in selected_files:
        ssh, sftp = upload_atomic(ssh, sftp, password, local, rel)

    # Mirror every selected file into the active web root atomically. All files
    # referenced by latest.json precede it; unsigned website aliases follow it.
    for _local, rel in selected_files:
        source = posixpath.join(REMOTE_ROOT, rel)
        destination = posixpath.join('/var/www/memo', rel)
        destination_dir = posixpath.dirname(destination)
        run(
            ssh,
            f'if [ -d /var/www/memo ]; then mkdir -p {shlex.quote(destination_dir)}; '
            f'cp -a {shlex.quote(source)} {shlex.quote(destination + ".tmp")} && '
            f'mv -f {shlex.quote(destination + ".tmp")} {shlex.quote(destination)} && '
            f'chown www-data:www-data {shlex.quote(destination)}; fi',
        )
    run(ssh, f'find {REMOTE_ROOT} -type f \\( -name "*.exe" -o -name "*.zip" -o -name "latest.json" -o -name "index.html" -o -name "memo-bg.png" \\) -print0 | xargs -0 -r ls -lh')
    print('Deployment completed.')
    sftp.close()
    ssh.close()

if __name__ == '__main__':
    main()
