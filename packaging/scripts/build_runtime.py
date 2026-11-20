"""Build a redistributable Memo Python runtime from the official embedded CPython.

The runtime directory is generated locally and gitignored. It contains no Memo
user data, config, databases, logs, or transcripts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
CACHE = ROOT / ".cache"
LOCK_FILE = ROOT / "requirements-runtime.lock.txt"
PRUNE_SCRIPT = ROOT / "scripts" / "prune_runtime.py"
PYTHON_VERSION = "3.11.9"
EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
MANIFEST_NAME = ".memo-runtime-manifest.json"


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 5_000_000:
        print(f"Using cached runtime archive: {target}")
        return
    print(f"Downloading official Python Embedded Runtime: {url}")
    urllib.request.urlretrieve(url, target)


def enable_site_packages(runtime: Path) -> None:
    pth = next(runtime.glob("python*._pth"), None)
    if not pth:
        raise RuntimeError("Embedded runtime ._pth file not found")
    lines = pth.read_text(encoding="utf-8").splitlines()
    enabled = []
    has_site = False
    for line in lines:
        if line.strip() == "#import site":
            enabled.append("import site")
            has_site = True
        else:
            enabled.append(line)
    if not has_site:
        enabled.extend(["Lib/site-packages", "import site"])
    elif "Lib/site-packages" not in enabled:
        enabled.insert(1, "Lib/site-packages")
    # In the installed layout runtime/ and app/ are siblings under Programs/Memo/.
    # Embedded Python ignores PYTHONPATH while ._pth isolation is active, so the
    # service app root must be explicitly listed here.
    if "../app" not in enabled:
        enabled.insert(2, "../app")
    pth.write_text("\n".join(enabled) + "\n", encoding="utf-8")
    (runtime / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_fingerprint() -> str:
    digest = hashlib.sha256()
    for label, path in (("lock", LOCK_FILE), ("prune", PRUNE_SCRIPT)):
        if not path.is_file():
            raise RuntimeError(f"Required runtime input missing: {path}")
        digest.update(label.encode("ascii"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\n")
    digest.update(f"python={PYTHON_VERSION}\nplatform=win_amd64\nno_compile=1\n".encode("ascii"))
    return digest.hexdigest()


def read_manifest(runtime: Path) -> dict:
    try:
        return json.loads((runtime / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def prepare_wheelhouse() -> Path:
    wheelhouse = CACHE / "wheels" / build_fingerprint()
    marker = wheelhouse / ".complete"
    if marker.is_file():
        print(f"Using cached wheelhouse: {wheelhouse}")
        return wheelhouse
    wheelhouse.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--only-binary=:all:",
        "--dest",
        str(wheelhouse),
        "-r",
        str(LOCK_FILE),
    ]
    print("Resolving pinned runtime wheels into the local wheelhouse")
    subprocess.run(command, check=True, env={**os.environ, "PIP_USER": "0"})
    marker.write_text(build_fingerprint() + "\n", encoding="ascii")
    return wheelhouse


def install_dependencies(runtime: Path) -> None:
    target = runtime / "Lib" / "site-packages"
    wheelhouse = prepare_wheelhouse()
    # pip normally compiles every .py file to .pyc. Electron Builder excludes
    # those files, so --no-compile avoids generating and scanning throwaway data.
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-user",
        "--no-compile",
        "--no-index",
        "--find-links",
        str(wheelhouse),
        "--target",
        str(target),
        "-r",
        str(LOCK_FILE),
    ]
    print("Installing pinned dependency wheels into embedded runtime")
    subprocess.run(command, check=True, env={**os.environ, "PIP_USER": "0", "PYTHONDONTWRITEBYTECODE": "1"})


def quick_smoke(runtime: Path) -> None:
    python = runtime / "python.exe"
    run = subprocess.run(
        [str(python), "-B", "-c", "import json,numpy,pydantic; print('cached runtime ready')"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=30,
    )
    if run.returncode != 0:
        raise RuntimeError(run.stderr or run.stdout)


def smoke(runtime: Path) -> None:
    python = runtime / "python.exe"
    code = (
        "import dotenv, numpy, pydantic, openai, mcp, torch, sentence_transformers; "
        "x=torch.tensor([1.0,2.0]); assert float((x*x).sum())==5.0; "
        "print('embedded runtime smoke ok', torch.__version__)"
    )
    run = subprocess.run(
        [str(python), "-B", "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=180,
    )
    if run.returncode != 0:
        raise RuntimeError(run.stderr or run.stdout)
    print(run.stdout.strip())


def prune_runtime(runtime: Path) -> dict:
    scripts_dir = str(PRUNE_SCRIPT.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from prune_runtime import prune

    result = prune(runtime, dry_run=False, verbose=False)
    print(f"Runtime pruned: {result['freed_mb']:.2f} MB, {result['removed_files']} files, {result['removed_dirs']} directories")
    return result


def commit_staging(staging: Path, output: Path) -> None:
    previous = output.with_name(f"{output.name}.previous")
    if previous.exists():
        shutil.rmtree(previous)
    if output.exists():
        output.replace(previous)
    try:
        staging.replace(output)
    except PermissionError:
        shutil.copytree(staging, output)
        shutil.rmtree(staging)
    if previous.exists():
        shutil.rmtree(previous)


def build_runtime(output: Path, force: bool = False, seed_from: Path | None = None) -> dict:
    fingerprint = build_fingerprint()
    if output.is_dir() and not force:
        manifest = read_manifest(output)
        if manifest.get("fingerprint") == fingerprint:
            quick_smoke(output)
            print(f"Using cached pruned runtime: {output}")
            return manifest

    staging = output.with_name(f"{output.name}.building")
    if staging.exists():
        shutil.rmtree(staging)
    if seed_from:
        if not (seed_from / "python.exe").is_file():
            raise RuntimeError(f"Seed runtime is invalid: {seed_from}")
        print(f"Seeding optimized runtime from: {seed_from}")
        shutil.copytree(seed_from, staging)
    else:
        archive = CACHE / f"python-{PYTHON_VERSION}-embed-amd64.zip"
        download(EMBED_URL, archive)
        staging.mkdir(parents=True)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(staging)
        enable_site_packages(staging)
        install_dependencies(staging)

    enable_site_packages(staging)
    prune_result = prune_runtime(staging)
    smoke(staging)
    manifest = {
        "schemaVersion": 1,
        "pythonVersion": PYTHON_VERSION,
        "platform": "win_amd64",
        "fingerprint": fingerprint,
        "lockSha256": sha256_bytes(LOCK_FILE.read_bytes()),
        "pruneSha256": sha256_bytes(PRUNE_SCRIPT.read_bytes()),
        "pruned": prune_result,
    }
    (staging / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    commit_staging(staging, output)
    print(f"Runtime created: {output}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(RUNTIME))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--seed-from", default="", help="Existing validated runtime to prune without downloading wheels")
    args = parser.parse_args()
    seed = Path(args.seed_from).resolve() if args.seed_from else None
    build_runtime(Path(args.output).resolve(), force=args.force, seed_from=seed)


if __name__ == "__main__":
    main()
