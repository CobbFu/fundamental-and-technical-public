"""Shared rolling-backup helper for `.valuation/*.yaml` files.

Writes backups to a `backups/` subfolder next to the source file and prunes
older entries so the main directory doesn't fill with `.bak-*` clutter.
`src/tracker/io.py` (tracker.yaml) calls through here so the backup
pattern stays consistent across the project's YAML state files.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

DEFAULT_RETENTION = 5
BACKUP_SUBDIR = "backups"


def write_backup(source_path: Path, *, retention: int = DEFAULT_RETENTION) -> Path | None:
    """Copy `source_path` to `<parent>/backups/<name>.bak-<ts>` and prune older copies.

    Returns the new backup path. Returns None if `source_path` doesn't exist
    (nothing to back up — first-ever write).
    """
    if not source_path.exists():
        return None
    backup_dir = source_path.parent / BACKUP_SUBDIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{source_path.name}.bak-{datetime.now():%Y%m%d_%H%M%S}"
    shutil.copy(source_path, backup_path)
    _prune(backup_dir, source_path.name, retention)
    return backup_path


def _prune(backup_dir: Path, source_name: str, retention: int) -> None:
    """Keep the N newest `<source_name>.bak-*` files; delete the rest."""
    pattern = f"{source_name}.bak-*"
    matches = sorted(backup_dir.glob(pattern))  # filename embeds timestamp -> lex sort = chrono
    excess = matches[:-retention] if retention > 0 else matches
    for old in excess:
        try:
            old.unlink()
        except OSError:
            pass
