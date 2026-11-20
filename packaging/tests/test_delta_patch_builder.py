import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_delta_patch import build, build_from_packages


def git(repo: Path, *args: str) -> str:
    run = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", check=True)
    return run.stdout.strip()


def write_service_tree(repo: Path, engine: bytes, obsolete: bool = True, added: bool = False):
    files = {
        "start_all.bat": b"@echo off\n",
        "stop_all.bat": b"@echo off\n",
        "requirements.txt": b"numpy\n",
        "pyproject.toml": b"[project]\nname='memo'\n",
        ".env.example": b"LLM_API_KEY=\n",
        "mcp_config.example.json": b"{}\n",
        "README.md": b"memo\n",
        "memo/__init__.py": b"",
        "memo/core/engine.py": engine,
        "scripts/memo_dashboard.py": b"VALUE='dashboard'\n",
        "dashboard/dist/index.html": b"<div>memo</div>\n",
    }
    if obsolete:
        files["scripts/obsolete.py"] = b"obsolete\n"
    if added:
        files["scripts/added.py"] = b"added\n"
    for name, content in files.items():
        path = repo / Path(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    if not obsolete:
        path = repo / "scripts" / "obsolete.py"
        if path.exists():
            path.unlink()
    (repo / "data").mkdir(exist_ok=True)
    (repo / "data" / "must-never-ship.db").write_bytes(b"secret")


def make_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Memo Test")
    write_service_tree(repo, b"VALUE='old'\n")
    git(repo, "add", "--all")
    git(repo, "commit", "-m", "old")
    old = git(repo, "rev-parse", "HEAD")
    write_service_tree(repo, b"VALUE='new'\n", obsolete=False, added=True)
    git(repo, "add", "--all")
    git(repo, "commit", "-m", "new")
    new = git(repo, "rev-parse", "HEAD")
    return repo, old, new


def make_full_package(path: Path, version: str, files: dict[str, bytes]):
    rows = [{"path": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()} for name, content in sorted(files.items())]
    manifest = {
        "schemaVersion": 2,
        "kind": "full",
        "serviceVersion": version,
        "sourceCommit": f"commit-{version}",
        "files": rows,
        "targetFiles": {row["path"]: row["sha256"] for row in rows},
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, content in files.items():
            bundle.writestr(f"app/{name}", content)
        bundle.writestr("service-patch-manifest.json", json.dumps(manifest))


def test_release_delta_uses_exact_full_package_bytes_not_git_checkout_bytes(tmp_path):
    required = {
        "start_all.bat": b"@echo off\r\n",
        "stop_all.bat": b"@echo off\r\n",
        "memo/__init__.py": b"",
        "memo/core/engine.py": b"VALUE='old'\r\n",
        "scripts/memo_dashboard.py": b"VALUE='dashboard'\r\n",
    }
    target = dict(required)
    target["memo/core/engine.py"] = b"VALUE='new'\r\n"
    old_zip = tmp_path / "old-full.zip"
    new_zip = tmp_path / "new-full.zip"
    make_full_package(old_zip, "1.0.0", required)
    make_full_package(new_zip, "1.1.0", target)

    result = build_from_packages(old_zip, new_zip, tmp_path / "out")

    with zipfile.ZipFile(tmp_path / "out" / result["name"]) as bundle:
        manifest = json.loads(bundle.read("service-patch-manifest.json"))
    engine = next(row for row in manifest["files"] if row["path"] == "memo/core/engine.py")
    assert engine["oldSha256"] == hashlib.sha256(b"VALUE='old'\r\n").hexdigest()
    assert engine["sha256"] == hashlib.sha256(b"VALUE='new'\r\n").hexdigest()


def test_delta_builder_is_deterministic_and_contains_conservative_delete_hash(tmp_path):
    repo, old, new = make_repo(tmp_path)
    output = tmp_path / "out"

    first = build(repo, output, old, new, "1.0.0", "1.1.0")
    first_hash = first["sha256"]
    second = build(repo, output, old, new, "1.0.0", "1.1.0")

    assert second["sha256"] == first_hash
    assert first["files"] == 2
    assert first["deletes"] == 1
    archive = output / first["name"]
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read("service-patch-manifest.json"))
        names = set(bundle.namelist())
    changed = {row["path"]: row for row in manifest["files"]}
    deleted = {row["path"]: row for row in manifest["deletes"]}
    assert changed["memo/core/engine.py"]["oldSha256"] == hashlib.sha256(b"VALUE='old'\n").hexdigest()
    assert changed["scripts/added.py"]["oldSha256"] is None
    assert deleted == {"scripts/obsolete.py": {"path": "scripts/obsolete.py", "oldSha256": hashlib.sha256(b"obsolete\n").hexdigest()}}
    assert "data/must-never-ship.db" not in manifest["targetFiles"]
    assert "app/data/must-never-ship.db" not in names


def test_delta_builder_rejects_suspicious_mass_delete(tmp_path):
    repo, old, _ = make_repo(tmp_path)
    for index in range(25):
        path = repo / "scripts" / f"bulk_{index}.py"
        path.write_text(f"VALUE={index}\n", encoding="utf-8")
    git(repo, "add", "--all")
    git(repo, "commit", "-m", "many files")
    many = git(repo, "rev-parse", "HEAD")
    for path in (repo / "scripts").glob("bulk_*.py"):
        path.unlink()
    git(repo, "add", "--all")
    git(repo, "commit", "-m", "mass delete")
    deleted = git(repo, "rev-parse", "HEAD")

    with pytest.raises(RuntimeError, match="suspicious delete set"):
        build(repo, tmp_path / "out", many, deleted, "1.1.0", "1.2.0")
