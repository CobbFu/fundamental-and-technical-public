"""CLI handlers for `track-add` and `track-refresh`.

The skill (model side) does all TradingView orchestration because only the
model has the MCP tools. It hands the gathered reads to this CLI as a JSON
payload via --payload (file) or --payload-stdin. The CLI persists, computes
verdicts, renders the digest, and emits a structured JSON response.

Convention from src/__main__.py: JSON to stdout, logs to stderr, exit 1 on
error with status="error" payload.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

import logging

from src.tracker.digest import render_digest
from src.tracker.io import (
    TrackerLockedError,
    acquire_lock,
    load_tracker,
    save_tracker,
)
from src.tracker.models import (
    Alert,
    LastRefresh,
    Plan,
    Thesis,
    TimeframeRead,
    TrackerEntry,
)
from src.tracker.portfolio_join import load_portfolio_holdings
from src.tracker.verdict import compose_verdict_full, verdict_changed

logger = logging.getLogger(__name__)

DEFAULT_TRACKER_PATH = Path(".valuation/tracker.yaml")
DEFAULT_PORTFOLIO_PATH = Path(".valuation/portfolio.yaml")
DEFAULT_DIGESTS_DIR = Path(".valuation/digests")


def _json_out(data: dict) -> None:
    json.dump(data, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def _json_error(message: str) -> NoReturn:
    _json_out({"status": "error", "message": message})
    sys.exit(1)


def _read_payload(args: argparse.Namespace) -> Any:
    if getattr(args, "payload_stdin", False):
        return json.load(sys.stdin)
    payload_path = getattr(args, "payload", None)
    if not payload_path:
        _json_error("either --payload <file> or --payload-stdin is required")
    return json.loads(Path(payload_path).read_text())


def _entry_from_payload(payload: dict[str, Any]) -> TrackerEntry:
    """Build a TrackerEntry from the JSON payload the skill emits.

    When the payload includes a `last_refresh` block with daily/weekly reads,
    we authoritatively recompute the verdict + flags via compose_verdict and
    overwrite whatever the skill claimed. This makes the "never compute verdict
    yourself" rule self-enforcing — the CLI is the single source of truth.
    """
    thesis_raw = payload.get("thesis") or {}
    plan_raw = payload.get("plan") or {}
    alerts_raw = payload.get("alerts") or []
    return TrackerEntry(
        ticker=str(payload["ticker"]),
        state=payload.get("state", "watching"),
        added=payload.get("added") or datetime.now().strftime("%Y-%m-%d"),
        thesis=Thesis(**{k: v for k, v in thesis_raw.items() if v is not None}),
        plan=Plan(
            entry_trigger=plan_raw.get("entry_trigger", ""),
            stop_loss=plan_raw.get("stop_loss"),
            add_zones=list(plan_raw.get("add_zones") or []),
            trim_zones=list(plan_raw.get("trim_zones") or []),
        ),
        alerts=[Alert(**a) for a in alerts_raw],
        last_refresh=_last_refresh_from_payload(payload.get("last_refresh")),
    )


def _last_refresh_from_payload(raw: dict[str, Any] | None) -> LastRefresh | None:
    if not raw:
        return None
    daily = _tf_from_payload(raw.get("daily"))
    weekly = _tf_from_payload(raw.get("weekly"))
    # Authoritative recomputation when the skill provided readings.
    regime = None
    if daily is not None or weekly is not None:
        verdict, flags, regime = compose_verdict_full(daily, weekly)
    else:
        verdict = raw.get("verdict", "hold")
        flags = list(raw.get("flags") or [])
    return LastRefresh(
        ts=raw.get("ts") or datetime.now().isoformat(timespec="seconds"),
        verdict=verdict,
        previous_verdict=raw.get("previous_verdict"),
        verdict_changed=bool(raw.get("verdict_changed", True)),
        flags=flags,
        daily=daily,
        weekly=weekly,
        notes=raw.get("notes", ""),
        error=raw.get("error"),
        regime=regime,
    )


def _tf_from_payload(raw: dict[str, Any] | None) -> TimeframeRead | None:
    if not raw:
        return None

    def _opt_float(key: str) -> float | None:
        v = raw.get(key)
        return float(v) if v is not None else None

    def _opt_int(key: str) -> int | None:
        v = raw.get(key)
        return int(v) if v is not None else None

    def _opt_bool(key: str) -> bool | None:
        v = raw.get(key)
        return bool(v) if v is not None else None

    return TimeframeRead(
        timeframe=str(raw.get("timeframe", "")),
        price=float(raw["price"]),
        # Drop null-valued indicator keys rather than coercing them — e.g. a
        # weekly 200-EMA is null for symbols with <200 weeks of history. The
        # verdict layer reads every key via .get() and degrades gracefully when
        # one is absent, so a missing value must never raise here.
        ema={int(k): float(v) for k, v in (raw.get("ema") or {}).items() if v is not None},
        rsi=float(raw["rsi"]) if raw.get("rsi") is not None else 0.0,
        rsi_ma=raw.get("rsi_ma"),
        macd={k: float(v) for k, v in (raw.get("macd") or {}).items() if v is not None},
        bb={k: float(v) for k, v in (raw.get("bb") or {}).items() if v is not None},
        volume=raw.get("volume"),
        # Trend-following derived fields (all optional).
        return_4w_pct=_opt_float("return_4w_pct"),
        return_12m_pct=_opt_float("return_12m_pct"),
        base_range_pct=_opt_float("base_range_pct"),
        consecutive_up_days=_opt_int("consecutive_up_days"),
        volume_ratio=_opt_float("volume_ratio"),
        range_atr_ratio=_opt_float("range_atr_ratio"),
        close_in_top_quartile=_opt_bool("close_in_top_quartile"),
    )


def _next_digest_path(dir_path: Path, date_str: str) -> Path:
    """First write of the day -> YYYY-MM-DD.md; subsequent -> -2.md, -3.md, etc."""
    dir_path.mkdir(parents=True, exist_ok=True)
    base = dir_path / f"{date_str}.md"
    if not base.exists():
        return base
    n = 2
    while True:
        candidate = dir_path / f"{date_str}-{n}.md"
        if not candidate.exists():
            return candidate
        n += 1


def cmd_track_add(args: argparse.Namespace) -> None:
    """Add or replace one entry. Payload contains thesis/plan/alerts/last_refresh."""
    tracker_path = Path(args.tracker_path)
    payload = _read_payload(args)
    if not isinstance(payload, dict):
        _json_error("track-add payload must be a single entry object")

    try:
        with acquire_lock(tracker_path):
            tracker = load_tracker(tracker_path)
            new_entry = _entry_from_payload(payload)
            existing_idx = next(
                (i for i, e in enumerate(tracker.entries) if e.ticker == new_entry.ticker),
                None,
            )
            if existing_idx is not None and not args.replace:
                _json_error(
                    f"ticker {new_entry.ticker} already exists; pass --replace to overwrite"
                )
            if existing_idx is not None:
                # Carry forward the prior street_target so verdict_changed works.
                prior = tracker.entries[existing_idx].street_target
                if prior and new_entry.street_target is None:
                    new_entry.street_target = prior
                tracker.entries[existing_idx] = new_entry
                action = "replaced"
            else:
                tracker.entries.append(new_entry)
                action = "added"
            # Pull a fresh street-target read for the new/replaced entry.
            _apply_street(new_entry, new_entry.ticker)
            backup_path: Path | None = None
            if not args.dry_run:
                backup_path = save_tracker(tracker, tracker_path)
    except TrackerLockedError as e:
        _json_error(str(e))

    _json_out(
        {
            "status": "ok",
            "action": action,
            "ticker": new_entry.ticker,
            "tracker_path": str(tracker_path),
            "backup_path": str(backup_path) if backup_path else None,
            "dry_run": args.dry_run,
            "street_target": new_entry.street_target,
        }
    )


def cmd_track_refresh(args: argparse.Namespace) -> None:
    """Refresh one or many entries. Payload is a list of {ticker, daily, weekly, ...}."""
    tracker_path = Path(args.tracker_path)
    portfolio_path = Path(args.portfolio_path)
    digests_dir = Path(args.digests_dir)

    payload = _read_payload(args)
    if not isinstance(payload, list):
        _json_error("track-refresh payload must be a list of read objects")

    try:
        with acquire_lock(tracker_path):
            tracker = load_tracker(tracker_path)
            updated: list[str] = []
            errors: list[dict[str, str]] = []
            scope_tickers: list[str] = []

            for read_obj in payload:
                if not isinstance(read_obj, dict):
                    errors.append({"ticker": "?", "error": "payload entry not a dict"})
                    continue
                ticker = read_obj.get("ticker")
                if not ticker:
                    errors.append({"ticker": "?", "error": "payload missing ticker"})
                    continue
                scope_tickers.append(ticker)
                entry = next((e for e in tracker.entries if e.ticker == ticker), None)
                if entry is None:
                    errors.append({"ticker": ticker, "error": "no tracker entry"})
                    continue
                # Snapshot the prior state so a failed read can restore it.
                prior_refresh = entry.last_refresh
                try:
                    _apply_read(entry, read_obj)
                    updated.append(ticker)
                except Exception as e:
                    errors.append({"ticker": ticker, "error": str(e)})
                    if prior_refresh is None:
                        entry.last_refresh = LastRefresh(
                            ts=datetime.now().isoformat(timespec="seconds"),
                            verdict="hold",
                            error=str(e),
                        )
                    else:
                        # Restore the prior read but flag the failure for this run.
                        prior_refresh.error = str(e)
                        entry.last_refresh = prior_refresh
                # Refresh the street-target read alongside the TA read.
                # Non-fatal on failure (leaves prior street_target in place).
                _apply_street(entry, ticker)

            holdings = load_portfolio_holdings(portfolio_path)
            refresh_ts = datetime.now().isoformat(timespec="seconds")
            digest_md = render_digest(
                tracker, holdings, refresh_ts, scope_tickers=scope_tickers or None
            )

            digest_path: Path | None = None
            backup_path: Path | None = None
            if not args.dry_run:
                backup_path = save_tracker(tracker, tracker_path)
                digest_path = _next_digest_path(digests_dir, datetime.now().strftime("%Y-%m-%d"))
                digest_path.write_text(digest_md)
    except TrackerLockedError as e:
        _json_error(str(e))

    _json_out(
        {
            "status": "ok",
            "updated": updated,
            "errors": errors,
            "tracker_path": str(tracker_path),
            "backup_path": str(backup_path) if backup_path else None,
            "digest_path": str(digest_path) if digest_path else None,
            "digest_md": digest_md,
            "dry_run": args.dry_run,
        }
    )


def _apply_street(entry: TrackerEntry, ticker: str) -> None:
    """Refresh entry.street_target with a fresh yfinance pull + delta detection.

    The street analyzer is stateless (just yfinance); this helper adds the two
    tracker-level metadata keys the digest uses to flag rerating-wave changes:
    `previous_verdict` and `verdict_changed`. Failure here is non-fatal — we
    log and leave the prior street_target in place so a flaky yfinance call
    doesn't corrupt the tracker.
    """
    # Lazy import: keeps yfinance off the tracker import path.
    from src.street import analyze

    try:
        new = analyze(ticker)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("street_target refresh failed for %s: %s", ticker, e)
        return

    new_dict = new.to_dict()
    prior = entry.street_target if isinstance(entry.street_target, dict) else None
    prior_verdict = prior.get("verdict") if prior else None
    new_dict["previous_verdict"] = prior_verdict
    new_dict["verdict_changed"] = bool(
        prior_verdict and prior_verdict != new_dict["verdict"]
    )
    entry.street_target = new_dict


def _apply_read(entry: TrackerEntry, read_obj: dict[str, Any]) -> None:
    """Apply a fresh read to an entry, computing verdict + flags + regime + diff.

    Builds the new LastRefresh in a local first; only assigns to entry on success
    so a partial failure can't leave the entry in a half-updated state.
    """
    daily = _tf_from_payload(read_obj.get("daily"))
    weekly = _tf_from_payload(read_obj.get("weekly"))
    new_verdict, flags, regime = compose_verdict_full(daily, weekly)
    prev_verdict = entry.last_refresh.verdict if entry.last_refresh else None
    changed = verdict_changed(new_verdict, prev_verdict)
    new_refresh = LastRefresh(
        ts=read_obj.get("ts") or datetime.now().isoformat(timespec="seconds"),
        verdict=new_verdict,
        previous_verdict=prev_verdict,
        verdict_changed=changed,
        flags=flags,
        daily=daily,
        weekly=weekly,
        notes=read_obj.get("notes", ""),
        regime=regime,
    )
    entry.last_refresh = new_refresh


def list_tracker(args: argparse.Namespace) -> None:
    """Emit the list of tracker entries (for the skill to know what to refresh)."""
    tracker = load_tracker(Path(args.tracker_path))
    _json_out(
        {
            "status": "ok",
            "entries": [
                {"ticker": e.ticker, "state": e.state} for e in tracker.entries
            ],
            "count": len(tracker.entries),
        }
    )


