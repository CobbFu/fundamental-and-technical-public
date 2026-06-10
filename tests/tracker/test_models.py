"""Round-trip dataclass <-> yaml fidelity."""

from dataclasses import asdict
from pathlib import Path

import yaml

from src.tracker.io import _tracker_from_dict, load_tracker, save_tracker
from src.tracker.models import (
    Alert,
    LastRefresh,
    Plan,
    Thesis,
    TimeframeRead,
    Tracker,
    TrackerEntry,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_constructs_minimal_tracker() -> None:
    t = Tracker(version=1, updated="2026-05-13", entries=[])
    assert t.version == 1
    assert t.entries == []


def test_dataclass_to_yaml_round_trip(tmp_path: Path) -> None:
    entry = TrackerEntry(
        ticker="WDC",
        state="held",
        added="2026-03-15",
        thesis=Thesis(
            cascade="AI Infra (storage tier)",
            summary="Memory cyclical.",
            conviction="medium",
            time_horizon="6-18m",
            target_size_pct=5.0,
            what_would_change_my_mind="Weekly RSI > 80 + 50-EMA close.",
        ),
        plan=Plan(
            entry_trigger="Pullback to 20-EMA.",
            stop_loss=366.0,
            add_zones=[429.0, 366.0],
            trim_zones=[],
        ),
        alerts=[
            Alert(price=429.0, type="crossing", note="20-EMA touch"),
            Alert(price=508.0, type="crossing", note="above rejection high"),
        ],
        last_refresh=LastRefresh(
            ts="2026-05-13T11:30:00",
            verdict="hold_tighten",
            previous_verdict="hold",
            verdict_changed=True,
            flags=["parabolic_weekly_trifecta"],
            daily=TimeframeRead(
                timeframe="1D",
                price=488.74,
                ema={20: 429.18, 50: 366.02, 200: 234.69},
                rsi=70.18,
                macd={"line": 43.19, "signal": 37.93, "hist": 5.26},
                bb={"upper": 513.68, "basis": 423.16, "lower": 332.63},
            ),
            weekly=None,
            notes="Daily parabolic-but-not-extreme.",
        ),
    )
    tracker = Tracker(version=1, updated="2026-05-13", entries=[entry])
    path = tmp_path / "tracker.yaml"
    save_tracker(tracker, path, backup=False)
    loaded = load_tracker(path)
    assert loaded.version == tracker.version
    assert len(loaded.entries) == 1
    e = loaded.entries[0]
    assert e.ticker == "WDC"
    assert e.thesis.cascade == "AI Infra (storage tier)"
    assert e.plan.add_zones == [429.0, 366.0]
    assert len(e.alerts) == 2
    assert e.last_refresh is not None
    assert e.last_refresh.verdict == "hold_tighten"
    assert e.last_refresh.daily is not None
    # EMA keys round-trip as int (YAML round-trips int keys as int when safe)
    assert e.last_refresh.daily.ema[20] == 429.18


def test_load_fixture_yaml() -> None:
    tracker = load_tracker(FIXTURES / "tracker_sample.yaml")
    assert tracker.version == 1
    assert len(tracker.entries) == 3
    wdc = tracker.entries[0]
    assert wdc.ticker == "WDC"
    assert wdc.state == "held"
    assert wdc.thesis.target_size_pct == 5.0
    assert wdc.last_refresh is not None
    assert wdc.last_refresh.daily is not None
    assert wdc.last_refresh.daily.ema[20] == 425.0
    assert wdc.last_refresh.weekly is not None
    assert wdc.last_refresh.weekly.rsi == 78.0


def test_asdict_yaml_safe_dump_roundtrip() -> None:
    """Ensure asdict() output is yaml.safe_dump-able with no custom representers."""
    tracker = load_tracker(FIXTURES / "tracker_sample.yaml")
    raw = asdict(tracker)
    serialised = yaml.safe_dump(raw, default_flow_style=False, sort_keys=False)
    redeserialised = yaml.safe_load(serialised)
    assert redeserialised["version"] == 1
    assert len(redeserialised["entries"]) == 3
    # Reconstruct via the loader and check key fields preserved
    rebuilt = _tracker_from_dict(redeserialised)
    assert rebuilt.entries[0].ticker == "WDC"
    assert rebuilt.entries[0].alerts[0].price == 429.0
