"""Tracker YAML IO — load/save with rolling backups + non-blocking file lock.

Backups go through `src.common.backups.write_backup`. Backups land in
`<path.parent>/backups/` and are pruned to the N newest entries.

Lock semantics: non-blocking exclusive (LOCK_EX | LOCK_NB). A second
concurrent caller fails fast with TrackerLockedError instead of hanging,
which matches the "fail fast, tell the user" posture from the plan.
"""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import yaml

from src.common.backups import write_backup
from src.tracker.models import (
    Alert,
    LastRefresh,
    Plan,
    Thesis,
    TimeframeRead,
    Tracker,
    TrackerEntry,
)


class TrackerLockedError(RuntimeError):
    """Another process holds the tracker lock."""


def today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_tracker(path: Path) -> Tracker:
    if not path.exists():
        return Tracker(version=1, updated=today_iso(), entries=[])
    raw = yaml.safe_load(path.read_text())
    if not raw:
        return Tracker(version=1, updated=today_iso(), entries=[])
    return _tracker_from_dict(raw)


def save_tracker(tracker: Tracker, path: Path, *, backup: bool = True) -> Path | None:
    """Write tracker to path atomically. Returns the backup path (or None if no prior file).

    Atomicity: write to <path>.tmp first, then os.replace -> path. On POSIX this
    is an atomic rename; a crash mid-write leaves the prior file intact.
    """
    backup_path: Path | None = None
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup:
        backup_path = write_backup(path)
    tracker.updated = today_iso()
    serialised = yaml.safe_dump(asdict(tracker), default_flow_style=False, sort_keys=False)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(serialised)
    os.replace(tmp_path, path)
    return backup_path


@contextmanager
def acquire_lock(path: Path) -> Iterator[None]:
    """Non-blocking exclusive lock on `<path>.lock`. Raises TrackerLockedError on contention."""
    lock_path = path.parent / f"{path.name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = open(lock_path, "w")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as e:
        fd.close()
        raise TrackerLockedError(f"tracker locked: {lock_path}") from e
    try:
        yield
    finally:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        finally:
            fd.close()


def _tracker_from_dict(raw: dict[str, Any]) -> Tracker:
    entries = [_entry_from_dict(e) for e in raw.get("entries") or []]
    return Tracker(
        version=int(raw.get("version", 1)),
        updated=str(raw.get("updated", "")),
        entries=entries,
    )


def _entry_from_dict(raw: dict[str, Any]) -> TrackerEntry:
    thesis_raw = raw.get("thesis") or {}
    plan_raw = raw.get("plan") or {}
    alerts_raw = raw.get("alerts") or []
    last_raw = raw.get("last_refresh")
    street_raw = raw.get("street_target")
    return TrackerEntry(
        ticker=str(raw["ticker"]),
        state=raw.get("state", "watching"),
        added=str(raw.get("added", "")),
        thesis=Thesis(**{k: v for k, v in thesis_raw.items() if v is not None}),
        plan=Plan(
            entry_trigger=plan_raw.get("entry_trigger", ""),
            stop_loss=plan_raw.get("stop_loss"),
            add_zones=list(plan_raw.get("add_zones") or []),
            trim_zones=list(plan_raw.get("trim_zones") or []),
        ),
        alerts=[Alert(**a) for a in alerts_raw],
        last_refresh=_last_refresh_from_dict(last_raw) if last_raw else None,
        street_target=dict(street_raw) if isinstance(street_raw, dict) else None,
    )


def _last_refresh_from_dict(raw: dict[str, Any]) -> LastRefresh:
    return LastRefresh(
        ts=str(raw["ts"]),
        verdict=raw["verdict"],
        previous_verdict=raw.get("previous_verdict"),
        verdict_changed=bool(raw.get("verdict_changed", True)),
        flags=list(raw.get("flags") or []),
        daily=_timeframe_from_dict(raw["daily"]) if raw.get("daily") else None,
        weekly=_timeframe_from_dict(raw["weekly"]) if raw.get("weekly") else None,
        notes=str(raw.get("notes", "")),
        error=raw.get("error"),
    )


def _timeframe_from_dict(raw: dict[str, Any]) -> TimeframeRead:
    # YAML may load int keys as str; normalise the EMA map keys back to int.
    ema_raw = raw.get("ema") or {}
    # Drop null-valued keys (e.g. weekly 200-EMA for short-history symbols) so
    # round-tripping a degraded read never raises; verdict.py guards each .get().
    ema = {int(k): float(v) for k, v in ema_raw.items() if v is not None}
    return TimeframeRead(
        timeframe=str(raw.get("timeframe", "")),
        price=float(raw["price"]),
        ema=ema,
        rsi=float(raw["rsi"]) if raw.get("rsi") is not None else 0.0,
        rsi_ma=raw.get("rsi_ma"),
        macd={k: float(v) for k, v in (raw.get("macd") or {}).items() if v is not None},
        bb={k: float(v) for k, v in (raw.get("bb") or {}).items() if v is not None},
        volume=raw.get("volume"),
    )
