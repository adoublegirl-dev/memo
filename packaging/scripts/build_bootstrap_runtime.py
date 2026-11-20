"""Build the minimal CPython bootstrap used to unpack Memo Full assets."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"
DEFAULT_OUTPUT = ROOT / "bootstrap-runtime"
PYTHON_VERSION = "3.11.9"
EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size > 5_000_000:
        return
    urllib.request.urlretrieve(EMBED_URL, target)


def build(output: Path, force: bool = False) -> dict:
    archive = CACHE / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    download(archive)
    fingerprint = sha256_file(archive)
    manifest_path = output / ".memo-bootstrap-manifest.json"
    if output.is_dir() and not force:
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing.get("archiveSha256") == fingerprint and (output / "python.exe").is_file():
                print(f"Using cached bootstrap runtime: {output}")
                return existing
        except (OSError, ValueError):
            pass

    staging = output.with_name(f"{output.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(staging)
    manifest = {
        "schemaVersion": 1,
        "pythonVersion": PYTHON_VERSION,
        "archiveSha256": fingerprint,
    }
    (staging / ".memo-bootstrap-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if output.exists():
        shutil.rmtree(output)
    try:
        staging.replace(output)
    except PermissionError:
        shutil.copytree(staging, output)
        shutil.rmtree(staging)
    print(f"Bootstrap runtime ready: {output}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    build(Path(args.output).resolve(), force=args.force)


if __name__ == "__main__":
    main()
