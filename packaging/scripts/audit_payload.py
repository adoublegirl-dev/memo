"""Fail the installer build if payload contains user data or secrets."""
from __future__ import annotations

import sys
from pathlib import Path

FORBIDDEN_DIRS = {"data", "logs", "backups", ".venv", "node_modules", "release", "install_output"}
FORBIDDEN_NAMES = {".env", ".env.local", ".env.production"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".pem", ".key"}


def audit(root: Path) -> list[str]:
    violations = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        parts = set(rel.parts)
        if parts & FORBIDDEN_DIRS or path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            violations.append(str(rel))
    return violations


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("payload")
    problems = audit(root)
    if problems:
        print("Forbidden payload files detected:")
        print("\n".join(problems))
        raise SystemExit(1)
    print(f"Payload audit passed: {root}")
