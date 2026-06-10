"""End-to-end CLI tests via subprocess.

Uses --dry-run for the no-side-effects check, and a tmp-path real run for
the digest-file collision check.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"


def _run(args: list[str], stdin: str | None = None) -> tuple[int, dict, str]:
    proc = subprocess.run(
        ["uv", "run", "python", "-m", "src", *args],
        cwd=REPO,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = proc.stdout
    parsed: dict = {}
    if out.strip():
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            parsed = {"_raw": out}
    return proc.returncode, parsed, proc.stderr


def test_track_add_dry_run(tmp_path: Path) -> None:
    tracker_path = tmp_path / "tracker.yaml"
    payload = {
        "ticker": "TEST",
        "state": "watching",
        "thesis": {"summary": "test ticker"},
        "plan": {"entry_trigger": "trigger", "stop_loss": 100.0},
        "alerts": [{"price": 110.0, "type": "crossing", "note": "test"}],
        "last_refresh": {
            "ts": "2026-05-13T12:00:00",
            "verdict": "watch",
            "verdict_changed": True,
            "flags": [],
            "daily": {
                "timeframe": "1D", "price": 105.0,
                "ema": {"20": 100, "50": 95, "200": 80},
                "rsi": 55.0,
                "macd": {"line": 1, "signal": 0.8, "hist": 0.2},
                "bb": {"upper": 115, "basis": 105, "lower": 95},
            },
        },
    }
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload))

    code, out, err = _run(
        ["track-add", "--tracker-path", str(tracker_path),
         "--payload", str(payload_path), "--dry-run"]
    )
    assert code == 0, f"stderr: {err}"
    assert out["status"] == "ok"
    assert out["ticker"] == "TEST"
    assert out["dry_run"] is True
    assert not tracker_path.exists()


def test_track_refresh_writes_digest_and_uses_collision_suffix(tmp_path: Path) -> None:
    # Seed tracker.yaml from the fixture so the refresh has entries to update.
    tracker_path = tmp_path / "tracker.yaml"
    portfolio_path = tmp_path / "portfolio.yaml"
    digests_dir = tmp_path / "digests"
    shutil.copy(FIXTURES / "tracker_sample.yaml", tracker_path)
    shutil.copy(FIXTURES / "portfolio_sample.yaml", portfolio_path)

    payload_path = FIXTURES / "read_payload_sample.json"

    code, out, err = _run(
        ["track-refresh",
         "--tracker-path", str(tracker_path),
         "--portfolio-path", str(portfolio_path),
         "--digests-dir", str(digests_dir),
         "--payload", str(payload_path)]
    )
    assert code == 0, f"stderr: {err}"
    assert out["status"] == "ok"
    assert "WDC" in out["updated"]
    assert out["digest_path"] is not None
    assert Path(out["digest_path"]).exists()
    assert "Tracker digest" in out["digest_md"]

    # Re-run -> collision suffix
    code2, out2, err2 = _run(
        ["track-refresh",
         "--tracker-path", str(tracker_path),
         "--portfolio-path", str(portfolio_path),
         "--digests-dir", str(digests_dir),
         "--payload", str(payload_path)]
    )
    assert code2 == 0, f"stderr: {err2}"
    p1 = Path(out["digest_path"])
    p2 = Path(out2["digest_path"])
    assert p1 != p2
    assert p2.name.endswith("-2.md")


def test_track_add_rejects_duplicate_without_replace(tmp_path: Path) -> None:
    tracker_path = tmp_path / "tracker.yaml"
    shutil.copy(FIXTURES / "tracker_sample.yaml", tracker_path)
    payload = {"ticker": "WDC", "state": "held"}
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload))
    code, out, _ = _run(
        ["track-add", "--tracker-path", str(tracker_path),
         "--payload", str(payload_path)]
    )
    assert code == 1
    assert out["status"] == "error"
    assert "already exists" in out["message"]


def test_track_add_overwrites_skill_supplied_verdict(tmp_path: Path) -> None:
    """Hard rule self-enforcement: even if the skill claims verdict='buy' for a
    weekly-parabolic-trifecta WDC payload, the CLI recomputes via compose_verdict.
    Post 2026-05-14 regime-gate: WDC is in Stage 2 (price 488 > 200-EMA 234,
    +108% over EMA), trend-following path fires the weekly-trifecta late-stage
    warning → persisted verdict is `hold_tighten` (not `dont_chase`). The skill's
    'buy' lie is still overruled — that's the rule being tested.
    """
    tracker_path = tmp_path / "tracker.yaml"
    payload = {
        "ticker": "WDC",
        "state": "watching",
        "thesis": {"summary": "test"},
        "plan": {},
        "alerts": [],
        "last_refresh": {
            "ts": "2026-05-13T12:00:00",
            "verdict": "buy",  # the skill lies
            "verdict_changed": True,
            "flags": [],
            "daily": {
                "timeframe": "1D", "price": 488.74,
                "ema": {"20": 429.18, "50": 366.02, "200": 234.69},
                "rsi": 70.18,
                "macd": {"line": 43.19, "signal": 37.93, "hist": 5.26},
                "bb": {"upper": 513.68, "basis": 423.16, "lower": 332.63},
            },
            "weekly": {
                "timeframe": "1W", "price": 488.74,
                "ema": {"20": 322.73, "50": 223.73, "200": 106.21},
                "rsi": 87.43, "rsi_ma": 80.03,
                "macd": {"line": 75.67, "signal": 58.26, "hist": 17.42},
                "bb": {"upper": 475.69, "basis": 306.34, "lower": 136.99},
            },
        },
    }
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload))
    code, out, err = _run(
        ["track-add", "--tracker-path", str(tracker_path),
         "--payload", str(payload_path)]
    )
    assert code == 0, f"stderr: {err}"
    # Read back the tracker and confirm verdict was recomputed
    saved = json.loads(json.dumps(out))  # noqa: S301 — already trusted
    assert saved["ticker"] == "WDC"
    # Now load tracker.yaml and check the persisted verdict
    code2, list_out, _ = _run(["track-list", "--tracker-path", str(tracker_path)])
    assert code2 == 0
    # The CLI doesn't expose verdict via track-list; confirm by reading the YAML directly.
    import yaml as _yaml
    raw = _yaml.safe_load(tracker_path.read_text())
    persisted_verdict = raw["entries"][0]["last_refresh"]["verdict"]
    persisted_regime = raw["entries"][0]["last_refresh"].get("regime")
    assert persisted_verdict == "hold_tighten", (
        f"Skill lied with 'buy', CLI must recompute under Stage 2 framework "
        f"to 'hold_tighten' (weekly trifecta late-stage warning); got {persisted_verdict}"
    )
    assert persisted_regime == "stage2", (
        f"WDC is in confirmed Stage 2; expected regime='stage2', got {persisted_regime}"
    )


def test_track_list(tmp_path: Path) -> None:
    tracker_path = tmp_path / "tracker.yaml"
    shutil.copy(FIXTURES / "tracker_sample.yaml", tracker_path)
    code, out, _ = _run(["track-list", "--tracker-path", str(tracker_path)])
    assert code == 0
    assert out["count"] == 3
    tickers = [e["ticker"] for e in out["entries"]]
    assert "WDC" in tickers and "NBIS" in tickers


@pytest.mark.integration
def test_track_refresh_via_stdin(tmp_path: Path) -> None:
    """Smoke: payload comes from stdin, not a file."""
    tracker_path = tmp_path / "tracker.yaml"
    portfolio_path = tmp_path / "portfolio.yaml"
    digests_dir = tmp_path / "digests"
    shutil.copy(FIXTURES / "tracker_sample.yaml", tracker_path)
    shutil.copy(FIXTURES / "portfolio_sample.yaml", portfolio_path)
    payload_text = (FIXTURES / "read_payload_sample.json").read_text()
    code, out, err = _run(
        ["track-refresh",
         "--tracker-path", str(tracker_path),
         "--portfolio-path", str(portfolio_path),
         "--digests-dir", str(digests_dir),
         "--payload-stdin"],
        stdin=payload_text,
    )
    assert code == 0, f"stderr: {err}"
    assert out["status"] == "ok"
    assert "Tracker digest" in out["digest_md"]
