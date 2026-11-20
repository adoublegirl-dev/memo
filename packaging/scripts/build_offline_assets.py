"""Pack the pruned Runtime and pinned BGE model into one verified Full asset."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = ROOT / "runtime-staging"
DEFAULT_MODEL = ROOT / "models" / "bge-small-zh-v1.5"
DEFAULT_OUTPUT = ROOT / "runtime-package" / "memo-offline-assets.zip"
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Required asset manifest is invalid: {path}") from exc


def asset_identity(runtime: Path, model: Path) -> dict:
    runtime_manifest = load_json(runtime / ".memo-runtime-manifest.json")
    model_manifest = load_json(model / "model-manifest.json")
    fingerprint = hashlib.sha256(
        f"runtime={runtime_manifest.get('fingerprint', '')}\nmodel={model_manifest.get('fingerprint', '')}\n".encode("ascii")
    ).hexdigest()
    return {
        "schemaVersion": 1,
        "fingerprint": fingerprint,
        "runtimeFingerprint": runtime_manifest.get("fingerprint", ""),
        "modelFingerprint": model_manifest.get("fingerprint", ""),
        "modelId": model_manifest.get("modelId", ""),
        "modelRevision": model_manifest.get("revision", ""),
    }


def add_file(bundle: zipfile.ZipFile, source: Path, archive_name: str) -> None:
    info = zipfile.ZipInfo(archive_name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    with source.open("rb") as input_stream, bundle.open(info, "w", force_zip64=True) as output_stream:
        shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)


def build(runtime: Path, model: Path, output: Path, force: bool = False) -> dict:
    if not (runtime / "python.exe").is_file():
        raise RuntimeError(f"Pruned runtime is missing: {runtime}")
    identity = asset_identity(runtime, model)
    sidecar = output.with_suffix(".manifest.json")
    if output.is_file() and sidecar.is_file() and not force:
        existing = load_json(sidecar)
        if existing.get("fingerprint") == identity["fingerprint"] and existing.get("sha256") == sha256_file(output):
            print(f"Using cached offline asset archive: {output}")
            return existing

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".zip.tmp")
    if temporary.exists():
        temporary.unlink()
    file_count = 0
    unpacked_size = 0
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as bundle:
        for prefix, source_root in (("runtime", runtime), ("models/bge-small-zh-v1.5", model)):
            for source in sorted(item for item in source_root.rglob("*") if item.is_file()):
                relative = source.relative_to(source_root).as_posix()
                add_file(bundle, source, f"{prefix}/{relative}")
                file_count += 1
                unpacked_size += source.stat().st_size
        bundle.writestr("offline-assets-manifest.json", json.dumps(identity, indent=2) + "\n")

    temporary.replace(output)
    manifest = {
        **identity,
        "sha256": sha256_file(output),
        "size": output.stat().st_size,
        "unpackedSize": unpacked_size,
        "fileCount": file_count,
    }
    sidecar.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"Offline asset archive ready: {output} "
        f"({manifest['size'] / 1024 / 1024:.2f} MB compressed, {file_count} files)"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    build(Path(args.runtime).resolve(), Path(args.model).resolve(), Path(args.output).resolve(), force=args.force)


if __name__ == "__main__":
    main()
