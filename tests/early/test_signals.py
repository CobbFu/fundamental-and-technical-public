"""Unit tests for early-stage signal functions (pure, no network)."""

import numpy as np
import pandas as pd

from src.early import signals as sig


def _df(close: np.ndarray, vol: np.ndarray | None = None) -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    n = len(close)
    vol = vol if vol is not None else np.full(n, 1e6)
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": vol},
        index=idx,
    )


def test_returns_none_on_short_history():
    short = _df(np.linspace(10, 11, 30))
    assert sig.base_proximity(short) is None
    assert sig.rs_line(short, _df(np.linspace(400, 401, 30))) is None
    assert sig.rs_line_new_high(short, _df(np.linspace(400, 401, 30))) is None


def test_rs_line_none_without_benchmark():
    df = _df(np.linspace(100, 101, 200))
    assert sig.rs_line(df, None) is None
    assert sig.rs_line_new_high(df, None) is None


def test_accumulation_zero_when_price_not_flat():
    # doubled over the window — not a base
    assert sig.accumulation_score(_df(np.linspace(50, 100, 120))) == 0.0


def test_accumulation_positive_on_flat_rising_obv():
    close = np.linspace(100, 108, 120)  # flat-ish (<20%), all up-days
    vol = np.linspace(1e6, 3e6, 120)
    score = sig.accumulation_score(_df(close, vol))
    assert 0.0 < score <= 1.0


def test_weinstein_stage_flags_extended_as_stage2():
    df = _df(np.linspace(50, 220, 300))  # strong long uptrend
    assert sig.weinstein_stage(df) == "STAGE2"


def test_weinstein_stage_flat_is_base():
    df = _df(np.full(300, 100.0))
    assert sig.weinstein_stage(df) == "STAGE1_BASE"


def test_weinstein_stage_short_history_is_base():
    assert sig.weinstein_stage(_df(np.linspace(10, 12, 100))) == "STAGE1_BASE"


def test_rs_line_new_high_true_when_rs_leads_price():
    # price made its high early then settled; benchmark collapses -> RS at new high
    close = np.concatenate([np.linspace(100, 110, 50), np.full(100, 100.0)])
    bench = np.concatenate([np.full(50, 400.0), np.linspace(400, 300, 100)])
    assert sig.rs_line_new_high(_df(close), _df(bench)) is True


def test_base_proximity_sign():
    # ends ~6% above a flat base
    close = np.concatenate([np.full(140, 100.0), np.linspace(100, 106, 5)])
    dist = sig.base_proximity(_df(close))
    assert dist is not None and 0.0 < dist < 0.10


# ─── v2: re-accumulation base (Door-2) ───


def test_reaccumulation_true_when_ran_then_rebased():
    up = np.linspace(50, 200, 200)      # the run
    down = np.linspace(200, 150, 20)    # ~25% pullback
    flat = np.full(80, 150.0)           # consolidating (vol contracts)
    assert sig.reaccumulation_base(_df(np.concatenate([up, down, flat]))) is True


def test_reaccumulation_false_at_new_highs():
    # monotonic uptrend, still making highs -> momentum, not a re-base
    assert sig.reaccumulation_base(_df(np.linspace(50, 220, 300))) is False


def test_reaccumulation_false_when_collapsed():
    up = np.linspace(50, 200, 200)
    crash = np.linspace(200, 50, 100)   # ~75% pullback -> Stage 4, not a base
    assert sig.reaccumulation_base(_df(np.concatenate([up, crash]))) is False


def test_reaccumulation_false_on_short_history():
    assert sig.reaccumulation_base(_df(np.linspace(50, 100, 150))) is False
