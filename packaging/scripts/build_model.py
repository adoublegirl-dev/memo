"""Build a deterministic offline BGE model payload for Memo Full.

The generated models/ directory is ignored by Git. The manifest records the
exact Hugging Face revision and every file hash so installer builds can prove
that a clean machine receives a complete local model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "models" / "bge-small-zh-v1.5"
MODEL_ID = "BAAI/bge-small-zh-v1.5"
MODEL_REVISION = "7999e1d3359715c523056ef9478215996d62a620"
REQUIRED_FILES = {
    "config.json",
    "config_sentence_transformers.json",
    "model.safetensors",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "1_Pooling/config.json",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_for(model_dir: Path) -> dict:
    files = []
    aggregate = hashlib.sha256()
    for path in sorted(item for item in model_dir.rglob("*") if item.is_file() and item.name != "model-manifest.json"):
        relative = path.relative_to(model_dir).as_posix()
        digest = sha256_file(path)
        size = path.stat().st_size
        files.append({"path": relative, "size": size, "sha256": digest})
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(str(size).encode("ascii"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\n")
    return {
        "schemaVersion": 1,
        "modelId": MODEL_ID,
        "revision": MODEL_REVISION,
        "fingerprint": aggregate.hexdigest(),
        "size": sum(item["size"] for item in files),
        "files": files,
    }


def validate_model(model_dir: Path) -> dict:
    missing = sorted(relative for relative in REQUIRED_FILES if not (model_dir / relative).is_file())
    if missing:
        raise RuntimeError(f"Offline model is incomplete; missing: {', '.join(missing)}")
    manifest = manifest_for(model_dir)
    if manifest["size"] < 50 * 1024 * 1024:
        raise RuntimeError(f"Offline model is unexpectedly small: {manifest['size']} bytes")
    return manifest


def cached_snapshot() -> Path | None:
    hub = Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    candidate = hub / "models--BAAI--bge-small-zh-v1.5" / "snapshots" / MODEL_REVISION
    return candidate if candidate.is_dir() else None


def resolve_source(explicit: str, offline: bool) -> Path:
    if explicit:
        source = Path(explicit).expanduser().resolve()
        if not source.is_dir():
            raise RuntimeError(f"Model source does not exist: {source}")
        return source
    cached = cached_snapshot()
    if cached:
        return cached
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("huggingface_hub is required when the pinned model is not cached") from exc
    return Path(snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION, local_files_only=offline)).resolve()


def build(source: Path, output: Path, force: bool = False) -> dict:
    if output.is_dir() and not force:
        try:
            existing = json.loads((output / "model-manifest.json").read_text(encoding="utf-8"))
            current = validate_model(output)
            if existing.get("fingerprint") == current["fingerprint"] and existing.get("revision") == MODEL_REVISION:
                print(f"Using cached offline model: {output}")
                return current
        except (OSError, ValueError, RuntimeError):
            pass

    staging = output.with_name(f"{output.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, staging, symlinks=False)
    manifest = validate_model(staging)
    (staging / "model-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    previous = output.with_name(f"{output.name}.previous")
    if previous.exists():
        shutil.rmtree(previous)
    if output.exists():
        output.replace(previous)
    try:
        staging.replace(output)
    except PermissionError:
        # Microsoft Store Python and some antivirus filters can reject an
        # otherwise valid directory rename. Copying the already-validated
        # staging tree preserves the same all-or-nothing source boundary.
        shutil.copytree(staging, output)
        shutil.rmtree(staging)
    if previous.exists():
        shutil.rmtree(previous)
    print(f"Offline model ready: {output} ({manifest['size'] / 1024 / 1024:.2f} MB)")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="", help="Existing Hugging Face snapshot directory")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--offline", action="store_true", help="Fail instead of downloading when cache is missing")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    source = resolve_source(args.source, args.offline)
    build(source, Path(args.output).resolve(), force=args.force)


if __name__ == "__main__":
    main()
