"""Tests for the point-in-time backtest harness (offline + one integration)."""

import numpy as np
import pandas as pd
import pytest

from src.early.backtest import replay_one, validate_known_winners
from src.early.data import EarlyDataStore


def _ohlcv(close: np.ndarray, idx: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": np.linspace(1e6, 3e6, len(close))},
        index=idx,
    )


def _seed_flat_then_explode():
    """250 flat bars at 50, then a ramp to 500 — a SanDisk-shaped curve."""
    n = 350
    close = np.concatenate([np.full(250, 50.0), np.linspace(50, 500, 100)])
    idx = pd.date_range("2024-06-01", periods=n, freq="D")
    store = EarlyDataStore(":memory:")
    store._upsert_ohlcv("WIN", _ohlcv(close, idx))
    store._upsert_ohlcv("SPY", _ohlcv(np.full(n, 400.0), idx))
    return store, idx


def test_replay_passes_in_base_rejects_when_extended():
    store, idx = _seed_flat_then_explode()
    bench = store.load_cached_ohlcv("SPY", days=2000)

    # In the base (still flat) -> should pass the technical gate.
    early = replay_one(store, "WIN", idx[240].strftime("%Y-%m-%d"), bench)
    assert early["gate_pass"] is True
    assert early["stage"] in ("STAGE1_BASE", "STAGE1_2_TURN")

    # After the run (extended) -> anti-momentum ceiling must reject it.
    late = replay_one(store, "WIN", idx[-1].strftime("%Y-%m-%d"), bench)
    assert late["gate_pass"] is False
    assert late["trailing_12m"] is not None and late["trailing_12m"] >= 0.50
    store.close()


def test_replay_no_lookahead():
    # Truncation must ignore the future explosion entirely.
    store, idx = _seed_flat_then_explode()
    bench = store.load_cached_ohlcv("SPY", days=2000)
    r = replay_one(store, "WIN", idx[240].strftime("%Y-%m-%d"), bench)
    assert r["bars"] == 241  # only data up to as_of
    store.close()


def test_replay_handles_missing_ticker():
    store = EarlyDataStore(":memory:")
    r = replay_one(store, "NONE", "2025-01-01", None)
    assert r["gate_pass"] is False
    store.close()


@pytest.mark.integration
def test_validate_known_winners_runs():
    store = EarlyDataStore(":memory:")
    out = validate_known_winners(store, fetch=True)
    assert out["total"] == 5 and "verdict" in out
    store.close()
