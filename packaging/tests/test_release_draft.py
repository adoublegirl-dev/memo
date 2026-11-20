from pathlib import Path

import pytest

from scripts.build_release_draft import build_draft


def test_release_draft_is_explicitly_unsigned_and_non_publishable(tmp_path: Path):
    full = tmp_path / "Memo Setup 1.2.3.exe"
    lite = tmp_path / "Memo Lite Setup 1.2.3.exe"
    service = tmp_path / "Memo-Service-1.2.3.zip"
    full.write_bytes(b"full")
    lite.write_bytes(b"lite")
    service.write_bytes(b"service")
    output = tmp_path / "latest.1.2.3.draft.DO_NOT_PUBLISH.json"

    manifest = build_draft(full, lite, service, "1.2.3", "1.2.3", "https://example.test/downloads", output)

    assert output.is_file()
    assert "signature" not in manifest
    assert manifest["version"] == "1.2.3"
    assert manifest["serviceVersion"] == "1.2.3"
    assert manifest["launcher"]["full"]["name"] == full.name
    assert manifest["service"]["full"]["name"] == service.name


def test_release_draft_refuses_publishable_filename(tmp_path: Path):
    files = []
    for name in ("full.exe", "lite.exe", "service.zip"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        files.append(path)

    with pytest.raises(RuntimeError, match="DO_NOT_PUBLISH"):
        build_draft(*files, "1.2.3", "1.2.3", "https://example.test/downloads", tmp_path / "latest.json")
