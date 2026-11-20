import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_full_and_lite_support_current_user_and_elevated_install_modes():
    full = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["build"]["nsis"]
    lite = json.loads((ROOT / "electron-builder.lite.json").read_text(encoding="utf-8"))["nsis"]
    for config in (full, lite):
        assert config["perMachine"] is False
        assert config["allowElevation"] is True


def test_full_uses_single_offline_asset_archive_and_minimal_bootstrap():
    full = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["build"]
    assert "runtime-package/**/*" in full["files"]
    assert "bootstrap-runtime/**/*" in full["files"]
    assert "runtime/**/*" not in full["files"]
    assert full["electronLanguages"] == ["zh-CN", "en-US"]


def test_lite_excludes_every_full_only_runtime_asset():
    lite = json.loads((ROOT / "electron-builder.lite.json").read_text(encoding="utf-8"))
    for excluded in ("!runtime/**/*", "!runtime-staging/**/*", "!runtime-package/**/*", "!bootstrap-runtime/**/*", "!models/**/*"):
        assert excluded in lite["files"]


def test_runtime_build_avoids_throwaway_pyc_and_runs_pruning():
    source = (ROOT / "scripts" / "build_runtime.py").read_text(encoding="utf-8")
    assert '"--no-compile"' in source
    assert "prune_runtime(staging)" in source
    assert "sentence_transformers" in source
    assert "torch.tensor" in source
