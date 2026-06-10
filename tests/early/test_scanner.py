"""Offline integration tests for EarlyScanner (in-memory store, stubbed .info)."""

import numpy as np
import pandas as pd

from src.early.scanner import EarlyScanner, _seed_verdict


def _df(start: float, end: float, n: int = 320) -> pd.DataFrame:
    close = np.concatenate([np.full(n - 60, float(start)), np.linspace(start, end, 60)])
    vol = np.linspace(1e6, 4e6, n)
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": vol},
        index=idx,
    )


class _Stub(EarlyScanner):
    INFO = {
        "AAA": {"marketCap": 5e9, "sector": "Tech", "industry": "Semiconductors",
                "shortName": "Alpha"},
        "BBB": {"marketCap": 4e9, "sector": "Tech", "industry": "Semiconductors",
                "shortName": "Beta"},
        "CCC": {"marketCap": 400e9, "sector": "Tech", "industry": "Software",
                "shortName": "Mega"},
    }

    def _fetch_info(self, ticker: str) -> dict:
        return self.INFO.get(ticker, {})

    def _fetch_fundamentals(self, ticker: str):
        return 0.6, 0.25


def _seeded() -> _Stub:
    s = _Stub(":memory:")
    seed = {"AAA": _df(40, 46), "BBB": _df(55, 63), "CCC": _df(300, 360), "SPY": _df(400, 405)}
    for tk, df in seed.items():
        s.store._upsert_ohlcv(tk, df)
    return s


def test_finds_smallcap_cohort_excludes_megacap():
    s = _seeded()
    res = s.run_scan(universe=["AAA", "BBB", "CCC"], fetch=False, momentum_tier12=set())
    tickers = {c.ticker for c in res.candidates}
    assert {"AAA", "BBB"} <= tickers
    assert "CCC" not in tickers  # mega-cap gated out by headroom band
    assert any(c.confirmed and c.label == "Semiconductors" for c in res.cohorts)
    s.close()


def test_anti_momentum_exclusion():
    s = _seeded()
    res = s.run_scan(universe=["AAA", "BBB"], fetch=False, momentum_tier12={"AAA"})
    assert "AAA" not in {c.ticker for c in res.candidates}
    s.close()


def test_persist_and_change_detection():
    s = _seeded()
    r1 = s.run_scan(universe=["AAA", "BBB"], fetch=False, momentum_tier12=set(), persist=True)
    assert r1.candidates and all(c.change == "new" for c in r1.candidates)
    r2 = s.run_scan(universe=["AAA", "BBB"], fetch=False, momentum_tier12=set(), persist=True)
    assert all(c.change == "unchanged" for c in r2.candidates)
    assert all(c.weeks_on_list == 2 for c in r2.candidates)
    s.close()


# ─── v2 ───


class _ThemeStub(EarlyScanner):
    INFO = {
        "SEM": {"marketCap": 5e9, "sector": "Technology",
                "industry": "Semiconductors", "shortName": "SemiCo"},
        "SEM2": {"marketCap": 4e9, "sector": "Technology",
                 "industry": "Semiconductors", "shortName": "SemiTwo"},
        "BANK": {"marketCap": 5e9, "sector": "Financial Services",
                 "industry": "Banks - Regional", "shortName": "BankCo"},
    }

    def _fetch_info(self, ticker: str) -> dict:
        return self.INFO.get(ticker, {})

    def _fetch_fundamentals(self, ticker: str):
        return 0.6, 0.25


def test_theme_filter_excludes_financials():
    s = _ThemeStub(":memory:")
    seed = {"SEM": _df(40, 46), "SEM2": _df(55, 63),
            "BANK": _df(40, 46), "SPY": _df(400, 405)}
    for tk, df in seed.items():
        s.store._upsert_ohlcv(tk, df)
    res = s.run_scan(universe=["SEM", "SEM2", "BANK"], fetch=False, momentum_tier12=set())
    tickers = {c.ticker for c in res.candidates}
    assert {"SEM", "SEM2"} <= tickers  # non-financial theme names pass
    assert "BANK" not in tickers       # Financials dropped by the v2 theme filter
    s.close()


def test_seed_verdict_labels():
    assert _seed_verdict("STAGE2", 0.29, False) == "RECOVERING — not a base yet"
    assert _seed_verdict("STAGE2", 0.10, False) == "EXTENDED — momentum, not early"
    assert _seed_verdict("STAGE1_BASE", 0.30, False) == "BASE — early candidate"
    assert (
        _seed_verdict("STAGE1_BASE", 0.30, True)
        == "RE-BASE forming — watch for breakout trigger"
    )
    assert _seed_verdict("STAGE4", 0.40, False) == "DOWNTREND — avoid"
    assert _seed_verdict("STAGE1_BASE", None, False) == "watch — insufficient history"
