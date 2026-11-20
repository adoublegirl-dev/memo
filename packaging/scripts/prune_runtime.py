"""Prune non-runtime files from the embedded Python runtime.

This removes development/linker artifacts and caches that are not required for
running Memo. It must be followed by smoke tests for torch, sentence-transformers
and Memo database initialization.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"

REMOVE_DIR_NAMES = {
    "__pycache__",
    "tests",
    "test",
    # Do not remove directories named "testing": torch.testing is imported at runtime.
    "docs",
    "doc",
    "examples",
    "example",
    "benchmarks",
    "benchmark",
}
REMOVE_SUFFIXES = {
    ".lib",   # MSVC link libraries; runtime uses .dll/.pyd
    ".pyc",
    ".pyo",
    ".c",
    ".cpp",
    ".cc",
    ".h",
    ".hpp",
    ".pyx",
    ".pxd",
}

# Keep package metadata mostly intact. RECORD files can be large and are not used at runtime.
REMOVE_EXACT_FILENAMES = {"RECORD", "INSTALLER", "REQUESTED"}


def size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def prune(runtime: Path, dry_run: bool = False, verbose: bool = True) -> dict:
    removed_files = 0
    removed_dirs = 0
    freed = 0

    # Remove directories bottom-up by matching safe disposable names.
    dirs = sorted((p for p in runtime.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True)
    for folder in dirs:
        if folder.name.lower() in REMOVE_DIR_NAMES:
            folder_size = size_bytes(folder)
            removed_dirs += 1
            freed += folder_size
            if verbose:
                print(f"DIR  {folder} ({folder_size / 1024 / 1024:.2f} MB)")
            if not dry_run:
                shutil.rmtree(folder, ignore_errors=True)

    for file in list(runtime.rglob("*")):
        if not file.is_file():
            continue
        if file.suffix.lower() in REMOVE_SUFFIXES or file.name in REMOVE_EXACT_FILENAMES:
            try:
                file_size = file.stat().st_size
            except OSError:
                continue
            removed_files += 1
            freed += file_size
            if verbose:
                print(f"FILE {file} ({file_size / 1024 / 1024:.2f} MB)")
            if not dry_run:
                try:
                    file.unlink()
                except OSError:
                    pass

    return {"removed_files": removed_files, "removed_dirs": removed_dirs, "freed_mb": round(freed / 1024 / 1024, 2)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", default=str(RUNTIME))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    runtime = Path(args.runtime)
    before = size_bytes(runtime)
    result = prune(runtime, dry_run=args.dry_run, verbose=not args.quiet)
    after = before if args.dry_run else size_bytes(runtime)
    print({**result, "before_mb": round(before / 1024 / 1024, 2), "after_mb": round(after / 1024 / 1024, 2)})


if __name__ == "__main__":
    main()
