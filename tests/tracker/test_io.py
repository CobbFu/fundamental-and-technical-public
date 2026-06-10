"""Tests for load/save with backups and the file lock."""

from pathlib import Path

import pytest

from src.tracker.io import (
    TrackerLockedError,
    acquire_lock,
    load_tracker,
    save_tracker,
)
from src.tracker.models import Tracker, TrackerEntry


def test_load_missing_returns_empty_tracker(tmp_path: Path) -> None:
    tracker = load_tracker(tmp_path / "nope.yaml")
    assert tracker.version == 1
    assert tracker.entries == []


def test_load_empty_file_returns_empty_tracker(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("")
    tracker = load_tracker(path)
    assert tracker.entries == []


def test_save_creates_file_no_backup_first_time(tmp_path: Path) -> None:
    path = tmp_path / "tracker.yaml"
    tracker = Tracker(
        version=1, updated="2026-05-13", entries=[TrackerEntry(ticker="WDC")]
    )
    backup = save_tracker(tracker, path)
    assert path.exists()
    assert backup is None
    assert "WDC" in path.read_text()


def test_save_creates_backup_on_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "tracker.yaml"
    save_tracker(
        Tracker(version=1, updated="2026-05-13", entries=[TrackerEntry(ticker="WDC")]),
        path,
    )
    backup = save_tracker(
        Tracker(version=1, updated="2026-05-13", entries=[TrackerEntry(ticker="NBIS")]),
        path,
    )
    assert backup is not None and backup.exists()
    assert "WDC" in backup.read_text()
    assert "NBIS" in path.read_text()
    assert backup.name.startswith("tracker.yaml.bak-")
    # Backup lives in a subfolder, not next to the source.
    assert backup.parent == path.parent / "backups"


def test_save_prunes_old_backups_to_retention_limit(tmp_path: Path) -> None:
    """Save 7 times in a row — only the 5 newest backups should survive."""
    import time

    path = tmp_path / "tracker.yaml"
    save_tracker(
        Tracker(version=1, updated="2026-05-13", entries=[TrackerEntry(ticker="WDC")]),
        path,
    )
    for i in range(7):
        save_tracker(
            Tracker(
                version=1,
                updated="2026-05-13",
                entries=[TrackerEntry(ticker=f"T{i}")],
            ),
            path,
        )
        # Timestamps have second-level resolution — without a small delay
        # multiple backups in the same second overwrite each other and the
        # retention check becomes trivial.
        time.sleep(1.05)
    backups_dir = path.parent / "backups"
    surviving = sorted(backups_dir.glob("tracker.yaml.bak-*"))
    assert len(surviving) == 5
    # The 5 newest must include the latest pre-save snapshot (T5, after the 7th save).
    assert any("T5" in p.read_text() for p in surviving)


def test_lock_blocks_second_acquire(tmp_path: Path) -> None:
    path = tmp_path / "tracker.yaml"
    with acquire_lock(path):
        with pytest.raises(TrackerLockedError):
            with acquire_lock(path):
                pytest.fail("should not reach here — lock held")


def test_lock_releases_after_exit(tmp_path: Path) -> None:
    path = tmp_path / "tracker.yaml"
    with acquire_lock(path):
        pass
    # Acquiring again must succeed.
    with acquire_lock(path):
        pass


def test_save_updates_updated_field(tmp_path: Path) -> None:
    path = tmp_path / "tracker.yaml"
    tracker = Tracker(version=1, updated="1999-01-01", entries=[])
    save_tracker(tracker, path)
    loaded = load_tracker(path)
    assert loaded.updated != "1999-01-01"
    assert len(loaded.updated) == 10  # YYYY-MM-DD


def test_save_is_atomic_no_tmp_left_behind(tmp_path: Path) -> None:
    """After a successful write, no .tmp sibling should remain."""
    path = tmp_path / "tracker.yaml"
    tracker = Tracker(version=1, updated="2026-05-13", entries=[TrackerEntry(ticker="X")])
    save_tracker(tracker, path)
    assert path.exists()
    assert not (tmp_path / "tracker.yaml.tmp").exists()
