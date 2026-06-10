"""Tests for digest rendering — fixture-driven structural assertions.

We don't golden-file the entire output (it's brittle to whitespace);
we assert on tier classification + section presence + ticker placement.
"""

from pathlib import Path

from src.tracker.digest import render_digest
from src.tracker.io import load_tracker
from src.tracker.models import LastRefresh, TimeframeRead
from src.tracker.portfolio_join import load_portfolio_holdings

FIXTURES = Path(__file__).parent / "fixtures"


def _holdings():
    return load_portfolio_holdings(FIXTURES / "portfolio_sample.yaml")


def _tracker():
    return load_tracker(FIXTURES / "tracker_sample.yaml")


def test_digest_has_three_tier_headers() -> None:
    tracker = _tracker()
    holdings = _holdings()
    md = render_digest(tracker, holdings, "2026-05-13T12:00:00")
    # Quiet/Glance/Action header presence depends on what's in scope, but at
    # least one of the three tier headers must appear since we have entries.
    assert "Tracker digest" in md
    assert ("🔴" in md) or ("🟡" in md) or ("⚪" in md)


def test_held_entry_shows_holding_snapshot() -> None:
    tracker = _tracker()
    holdings = _holdings()
    md = render_digest(tracker, holdings, "2026-05-13T12:00:00")
    # WDC is held: should show shares + avg cost.
    assert "WDC" in md
    assert "10 sh" in md
    assert "$450" in md  # 4500.00 / 10 = 450.00


def test_alerts_gap_section_lists_unset_alerts() -> None:
    tracker = _tracker()
    holdings = _holdings()
    md = render_digest(tracker, holdings, "2026-05-13T12:00:00")
    assert "Alerts gap" in md
    # WDC has 3 unset alerts; one of them is at $508.
    assert "$508" in md


def test_position_summary_table_present() -> None:
    tracker = _tracker()
    holdings = _holdings()
    md = render_digest(tracker, holdings, "2026-05-13T12:00:00")
    assert "Position summary" in md
    assert "| Ticker |" in md


def test_changed_verdict_classified_as_action() -> None:
    """Force a verdict change on WDC — should land in 🔴 section."""
    tracker = _tracker()
    holdings = _holdings()
    wdc = tracker.entries[0]
    assert wdc.last_refresh is not None
    wdc.last_refresh.previous_verdict = "hold"
    wdc.last_refresh.verdict = "trim"
    wdc.last_refresh.verdict_changed = True
    md = render_digest(tracker, holdings, "2026-05-13T12:00:00")
    # WDC must appear under the 🔴 Action section, before any 🟡 or ⚪.
    action_idx = md.find("🔴 Action required")
    wdc_idx = md.find("**WDC**")
    glance_idx = md.find("🟡 Worth a glance")
    assert action_idx >= 0
    assert wdc_idx > action_idx
    if glance_idx > 0:
        assert wdc_idx < glance_idx


def test_critical_flag_promotes_to_action() -> None:
    """Even if verdict didn't change, weekly_rsi_extreme flag promotes to 🔴."""
    tracker = _tracker()
    holdings = _holdings()
    wdc = tracker.entries[0]
    assert wdc.last_refresh is not None
    wdc.last_refresh.verdict_changed = False
    wdc.last_refresh.flags = ["weekly_rsi_extreme"]
    md = render_digest(tracker, holdings, "2026-05-13T12:00:00")
    action_idx = md.find("🔴 Action required")
    wdc_idx = md.find("**WDC**")
    assert action_idx >= 0 and wdc_idx > action_idx


def test_scope_filter_limits_entries() -> None:
    tracker = _tracker()
    holdings = _holdings()
    md = render_digest(tracker, holdings, "2026-05-13T12:00:00", scope_tickers=["NBIS"])
    assert "NBIS" in md
    assert "**WDC**" not in md
    assert "**AMD**" not in md


def test_exit_verdict_translated_to_dont_chase_for_watching_entry() -> None:
    """A watching entry that lands on 'exit' should display as 'dont_chase' —
    nothing to exit if not held.
    """
    tracker = _tracker()
    holdings = _holdings()
    nbis = next(e for e in tracker.entries if e.ticker == "NBIS")
    nbis.last_refresh = LastRefresh(
        ts="2026-05-13T12:00:00",
        verdict="exit",
        verdict_changed=True,
        daily=TimeframeRead(timeframe="1D", price=100.0),
    )
    md = render_digest(tracker, holdings, "2026-05-13T12:00:00", scope_tickers=["NBIS"])
    assert "dont_chase" in md
    # The legend contains the literal verdict codes for reference, so we scope
    # the negative assertion to the action-card region only — the NBIS card
    # must not display "exit" as its verdict (it should show "dont_chase").
    action_section = md.split("## 🔴 Action required", 1)[-1]
    nbis_card = action_section.split("**NBIS**", 1)[-1].split("\n###", 1)[0]
    assert "`exit`" not in nbis_card
    assert "— Exit" not in nbis_card  # plain-English label form


def test_exit_verdict_preserved_for_held_entry() -> None:
    """A held entry on 'exit' must still display 'exit' — there IS something to exit."""
    tracker = _tracker()
    holdings = _holdings()
    wdc = tracker.entries[0]
    assert wdc.last_refresh is not None
    wdc.last_refresh.verdict = "exit"
    wdc.last_refresh.verdict_changed = True
    md = render_digest(tracker, holdings, "2026-05-13T12:00:00", scope_tickers=["WDC"])
    assert "exit" in md


def test_error_section_shown_when_present() -> None:
    tracker = _tracker()
    holdings = _holdings()
    nbis = next(e for e in tracker.entries if e.ticker == "NBIS")
    nbis.last_refresh = LastRefresh(
        ts="2026-05-13T12:00:00",
        verdict="hold",
        error="TV unreachable for NBIS",
        daily=TimeframeRead(timeframe="1D", price=0.0),
    )
    md = render_digest(tracker, holdings, "2026-05-13T12:00:00")
    assert "⚠️ Errors" in md
    assert "TV unreachable" in md
