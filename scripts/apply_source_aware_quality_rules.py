"""Apply rule-based quality processing to source-aware memories.

This script is intentionally additive:
- creates/updates memory_quality_reviews only;
- never deletes memory_units/source data;
- never merges memories;
- production apply requires explicit confirmation and creates a DB backup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memo.core.config import config
from memo.core.engine import engine
from memo.store.database import db


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def backup_db(label: str) -> dict:
    db_path = Path(config.db_path)
    backup_dir = db_path.parent / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = backup_dir / f'memo-before-{label}-{stamp}.db'
    shutil.copy2(db_path, backup)
    return {'backup': str(backup), 'sha256': sha256(backup)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='write memory_quality_reviews')
    parser.add_argument('--confirm', default='', help='required: APPLY_SOURCE_AWARE_QUALITY_RULES')
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()

    engine.init()
    backup = None
    if args.apply:
        if args.confirm != 'APPLY_SOURCE_AWARE_QUALITY_RULES':
            raise SystemExit('真实写库需要 --confirm APPLY_SOURCE_AWARE_QUALITY_RULES')
        db.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        backup = backup_db('apply-source-aware-quality-rules')

    result = engine.apply_source_aware_quality_rules(dry_run=not args.apply, limit=args.limit or None)
    result['db_path'] = str(config.db_path)
    result['backup'] = backup
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
