from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import os
import posixpath
import re
import secrets
import socket
import sys
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
HOST = os.getenv("MEMO_SERVER_HOST", "").strip()
PORT = int(os.getenv("MEMO_SERVER_PORT", "0") or 0)
USER = os.getenv("MEMO_SERVER_USER", "").strip()
REMOTE_SITE_SOURCE = "/root/MEMO/guanwang"
REMOTE_SITE_LIVE = "/var/www/memo"
REMOTE_APP = "/opt/memo-feedback/app"
REMOTE_ENV = "/opt/memo-feedback/.env"

FILES = [
    (ROOT / "website" / "index-glass.html", f"{REMOTE_SITE_SOURCE}/index.html"),
    (ROOT / "website" / "mobile.html", f"{REMOTE_SITE_SOURCE}/mobile.html"),
    (ROOT / "website" / "feedback.html", f"{REMOTE_SITE_SOURCE}/feedback.html"),
    (ROOT / "website" / "feedback.css", f"{REMOTE_SITE_SOURCE}/feedback.css"),
    (ROOT / "website" / "feedback.js", f"{REMOTE_SITE_SOURCE}/feedback.js"),
    (ROOT / "feedback_service" / "__init__.py", f"{REMOTE_APP}/feedback_service/__init__.py"),
    (ROOT / "feedback_service" / "app.py", f"{REMOTE_APP}/feedback_service/app.py"),
    (ROOT / "feedback_service" / "config.py", f"{REMOTE_APP}/feedback_service/config.py"),
    (ROOT / "feedback_service" / "database.py", f"{REMOTE_APP}/feedback_service/database.py"),
    (ROOT / "feedback_service" / "security.py", f"{REMOTE_APP}/feedback_service/security.py"),
    (ROOT / "feedback_service" / "requirements.txt", f"{REMOTE_APP}/requirements.txt"),
    (ROOT / "feedback_service" / "static" / "admin.html", f"{REMOTE_APP}/feedback_service/static/admin.html"),
    (ROOT / "feedback_service" / "static" / "admin.css", f"{REMOTE_APP}/feedback_service/static/admin.css"),
    (ROOT / "feedback_service" / "static" / "admin.js", f"{REMOTE_APP}/feedback_service/static/admin.js"),
]


def run(ssh: paramiko.SSHClient, command: str) -> str:
    _, stdout, stderr = ssh.exec_command(command)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError(f"Remote command failed ({code}): {command}\n{out}\n{err}")
    return out.strip()


class ConfirmHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, known_hosts: Path):
        self.known_hosts = known_hosts

    def missing_host_key(self, client, hostname, key):
        fingerprint = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        print(f"Unknown SSH host key for {hostname}: SHA256:{fingerprint}")
        expected = os.getenv("MEMO_SERVER_HOSTKEY_SHA256", "").removeprefix("SHA256:")
        trusted = hmac.compare_digest(expected, fingerprint) if expected else input("Trust and save this host key? [yes/N]: ").strip().lower() == "yes"
        if not trusted:
            raise paramiko.SSHException("SSH host key was not trusted")
        client.get_host_keys().add(hostname, key.get_name(), key)
        self.known_hosts.parent.mkdir(parents=True, exist_ok=True)
        client.save_host_keys(str(self.known_hosts))


def connect(password: str) -> paramiko.SSHClient:
    sock = socket.create_connection((HOST, PORT), timeout=25)
    sock.settimeout(90)
    client = paramiko.SSHClient()
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    client.load_system_host_keys()
    if known_hosts.exists():
        client.load_host_keys(str(known_hosts))
    client.set_missing_host_key_policy(ConfirmHostKeyPolicy(known_hosts))
    client.connect(HOST, PORT, USER, password, sock=sock, look_for_keys=False, allow_agent=False, timeout=30, banner_timeout=75, auth_timeout=45)
    return client


def mkdirs(sftp: paramiko.SFTPClient, folder: str) -> None:
    current = ""
    for part in folder.strip("/").split("/"):
        current += "/" + part
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)


def upload_atomic(sftp: paramiko.SFTPClient, local: Path, remote: str) -> None:
    mkdirs(sftp, posixpath.dirname(remote))
    temp = f"{remote}.uploading-{int(time.time())}"
    sftp.put(str(local), temp)
    try:
        sftp.posix_rename(temp, remote)
    except Exception:
        try:
            sftp.remove(remote)
        except FileNotFoundError:
            pass
        sftp.rename(temp, remote)
    print(f"Uploaded: {local.name} -> {remote}")


def password_hash(password: str) -> str:
    iterations = 240_000
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def first_env() -> str:
    print("First deployment: create the feedback administrator account.")
    while True:
        username = input("Admin username [admin]: ").strip() or "admin"
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", username):
            break
        print("Username may contain only letters, numbers, underscore and hyphen.")
    while True:
        password = getpass.getpass("Admin password (at least 12 characters): ")
        confirm = getpass.getpass("Confirm admin password: ")
        if len(password) < 12:
            print("Password is too short.")
        elif not hmac.compare_digest(password, confirm):
            print("Passwords do not match.")
        else:
            break
    return "\n".join([
        "FEEDBACK_DATA_DIR=/var/lib/memo-feedback",
        f"FEEDBACK_ADMIN_USERNAME={username}",
        f"FEEDBACK_ADMIN_PASSWORD_HASH={password_hash(password)}",
        f"FEEDBACK_SESSION_SECRET={secrets.token_urlsafe(48)}",
        f"FEEDBACK_IP_HASH_SECRET={secrets.token_urlsafe(48)}",
        "FEEDBACK_COOKIE_SECURE=1",
        "",
    ])


def main() -> int:
    global HOST, PORT, USER
    HOST = HOST or input("SSH host or IP: ").strip()
    PORT = PORT or int(input("SSH port [22]: ").strip() or "22")
    USER = USER or input("SSH username: ").strip()
    if not HOST or not USER:
        raise ValueError("SSH host and username are required")
    missing = [str(local) for local, _ in FILES if not local.is_file()]
    if missing:
        raise FileNotFoundError("Missing deployment files:\n" + "\n".join(missing))
    password = os.getenv("MEMO_SERVER_PASSWORD") or getpass.getpass(f"SSH password for {USER}@{HOST}:{PORT}: ")
    ssh = connect(password)
    sftp = ssh.open_sftp()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = f"/opt/memo-feedback/backups/deploy-{stamp}"
    try:
        print(run(ssh, "hostname"))
        run(ssh, f"mkdir -p {backup}/site {backup}/app /var/lib/memo-feedback/uploads {REMOTE_APP} /etc/nginx/snippets; id -u memo-feedback >/dev/null 2>&1 || useradd --system --home /var/lib/memo-feedback --shell /usr/sbin/nologin memo-feedback")
        run(ssh, f"for f in index.html mobile.html feedback.html feedback.css feedback.js; do [ ! -f {REMOTE_SITE_LIVE}/$f ] || cp -a {REMOTE_SITE_LIVE}/$f {backup}/site/$f; done")
        run(ssh, f"[ ! -d {REMOTE_APP}/feedback_service ] || cp -a {REMOTE_APP}/feedback_service {backup}/app/")
        run(ssh, "python3 - <<'PY'\nimport sqlite3, pathlib, datetime\nsrc=pathlib.Path('/var/lib/memo-feedback/feedback.db')\nif src.exists():\n dst=pathlib.Path('/opt/memo-feedback/backups') / ('feedback-before-deploy-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.db')\n with sqlite3.connect(src) as a, sqlite3.connect(dst) as b: a.backup(b)\n print(dst)\nPY")
        for local, remote in FILES:
            upload_atomic(sftp, local, remote)
        run(ssh, f"mkdir -p {REMOTE_SITE_LIVE}; for f in index.html mobile.html feedback.html feedback.css feedback.js; do cp -a {REMOTE_SITE_SOURCE}/$f {REMOTE_SITE_LIVE}/$f.tmp && mv -f {REMOTE_SITE_LIVE}/$f.tmp {REMOTE_SITE_LIVE}/$f; done; chown -R www-data:www-data {REMOTE_SITE_LIVE}")

        try:
            sftp.stat(REMOTE_ENV)
            print("Existing feedback .env preserved.")
        except FileNotFoundError:
            content = first_env().encode("utf-8")
            with sftp.file(REMOTE_ENV, "wb") as handle:
                handle.write(content)
            sftp.chmod(REMOTE_ENV, 0o600)
            print("Created feedback .env.")
        run(ssh, "chown -R memo-feedback:memo-feedback /var/lib/memo-feedback; chown memo-feedback:memo-feedback /opt/memo-feedback/.env; chmod 600 /opt/memo-feedback/.env")

        service = """[Unit]\nDescription=Memo Feedback Service\nAfter=network.target\n\n[Service]\nType=simple\nWorkingDirectory=/opt/memo-feedback/app\nEnvironmentFile=/opt/memo-feedback/.env\nExecStart=/opt/memo-feedback/venv/bin/uvicorn feedback_service.app:app --host 127.0.0.1 --port 9130 --workers 1\nRestart=on-failure\nRestartSec=3\nUser=memo-feedback\nGroup=memo-feedback\nNoNewPrivileges=true\nPrivateTmp=true\nProtectSystem=strict\nProtectHome=true\nReadWritePaths=/var/lib/memo-feedback\n\n[Install]\nWantedBy=multi-user.target\n"""
        with sftp.file("/etc/systemd/system/memo-feedback.service", "wb") as handle:
            handle.write(service.encode("utf-8"))

        snippet = """location /api/feedback { if ($scheme = http) { return 301 https://$host$request_uri; } proxy_pass http://127.0.0.1:9130; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $remote_addr; proxy_set_header X-Forwarded-Proto $scheme; client_max_body_size 11m; }\nlocation /api/admin/ { if ($scheme = http) { return 301 https://$host$request_uri; } proxy_pass http://127.0.0.1:9130; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $remote_addr; proxy_set_header X-Forwarded-Proto $scheme; client_max_body_size 1m; }\nlocation /admin/feedback { if ($scheme = http) { return 301 https://$host$request_uri; } proxy_pass http://127.0.0.1:9130; proxy_set_header Host $host; }\nlocation ^~ /feedback-admin-static/ { if ($scheme = http) { return 301 https://$host$request_uri; } proxy_pass http://127.0.0.1:9130; proxy_set_header Host $host; }\n"""
        with sftp.file("/etc/nginx/snippets/memo-feedback.conf", "wb") as handle:
            handle.write(snippet.encode("utf-8"))

        nginx_site = "/etc/nginx/sites-available/memo.zhaguzhagu.com"
        run(ssh, f"cp -a {nginx_site} {backup}/memo.zhaguzhagu.com.nginx")
        patch_script = """from pathlib import Path\nimport re\np=Path('/etc/nginx/sites-available/memo.zhaguzhagu.com')\nif not p.exists(): raise SystemExit(f'nginx site not found: {p}')\ntext=p.read_text()\nline='include /etc/nginx/snippets/memo-feedback.conf;'\nif line not in text:\n    pattern=r'(?m)^(\\s*)server_name\\s+memo\\.zhaguzhagu\\.com\\s*;'\n    matches=list(re.finditer(pattern,text))\n    if not matches: raise SystemExit('server_name memo.zhaguzhagu.com not found')\n    text=re.sub(pattern, lambda m: m.group(0)+'\\n'+m.group(1)+line, text)\n    p.write_text(text)\n    if line not in text: raise SystemExit('nginx include insertion failed')\n"""
        encoded = base64.b64encode(patch_script.encode()).decode()
        run(ssh, f"python3 -c \"import base64;exec(base64.b64decode('{encoded}'))\"")
        run(ssh, "python3 -m venv /opt/memo-feedback/venv && /opt/memo-feedback/venv/bin/pip install -q --upgrade pip && /opt/memo-feedback/venv/bin/pip install -q -r /opt/memo-feedback/app/requirements.txt")
        run(ssh, "systemctl daemon-reload && systemctl enable memo-feedback --now && systemctl restart memo-feedback")
        run(ssh, f"if nginx -t; then systemctl reload nginx; else cp -a {backup}/memo.zhaguzhagu.com.nginx {nginx_site}; nginx -t; exit 1; fi")
        health = run(ssh, "for i in $(seq 1 30); do if curl -fsS http://127.0.0.1:9130/health; then exit 0; fi; sleep 1; done; journalctl -u memo-feedback.service -n 80 --no-pager >&2; exit 1")
        print(health)
        run(ssh, "test $(curl -ksS -o /dev/null -w '%{http_code}' https://memo.zhaguzhagu.com/admin/feedback) = 200")
        print("Deployment complete.")
        print("Feedback: https://memo.zhaguzhagu.com/feedback.html")
        print("Admin: https://memo.zhaguzhagu.com/admin/feedback")
        return 0
    finally:
        sftp.close()
        ssh.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
