"""Fundamental signal extractors for momentum enrichment.

Pure functions that take yfinance data structures and return signals.
No API calls, no side effects. Called by scanner.py after fetching data.

Academic foundations:
- Novy-Marx (2015): earnings momentum explains price momentum
- Asness et al (2013): momentum + value combo improves Sharpe
- Daniel & Moskowitz (2016): momentum crashes forecastable via crowding
- Fu et al (2024): FCF yield nearly doubles Sharpe when combined with momentum
"""

import pandas as pd

# ─── Pass 1: Lightweight analyst signals (all 900 stocks) ───


def earnings_revision_score(eps_revisions: pd.DataFrame | None) -> float | None:
    """Net revision direction from yfinance eps_revisions DataFrame.

    Returns value in [-1.0, 1.0]: positive = more upward revisions.
    Uses current-year row ('0y') with 30-day window for stability.
    Falls back to current-quarter ('0q') if '0y' not available.
    """
    if eps_revisions is None or eps_revisions.empty:
        return None
    for period in ["0y", "0q"]:
        if period not in eps_revisions.index:
            continue
        row = eps_revisions.loc[period]
        up = row.get("upLast30days", 0) or 0
        down = row.get("downLast30days", 0) or 0
        total = up + down
        if total == 0:
            continue
        return float((up - down) / total)
    return None


def analyst_buy_percentage(recommendations: pd.DataFrame | None) -> float | None:
    """Percentage of analysts rating Buy or Strong Buy (current month).

    Returns 0.0-1.0. Higher = more bullish consensus.
    """
    if recommendations is None or recommendations.empty:
        return None
    current = recommendations.iloc[0]
    total = sum(current.get(col, 0) or 0
                for col in ["strongBuy", "buy", "hold", "sell", "strongSell"])
    if total == 0:
        return None
    buys = (current.get("strongBuy", 0) or 0) + (current.get("buy", 0) or 0)
    return float(buys / total)


def earnings_growth_estimate(earnings_estimate: pd.DataFrame | None) -> float | None:
    """Current-year EPS growth estimate from yfinance earnings_estimate.

    Returns as decimal (0.15 = 15% growth). Uses '0y' row.
    """
    if earnings_estimate is None or earnings_estimate.empty:
        return None
    for period in ["0y", "0q"]:
        if period not in earnings_estimate.index:
            continue
        growth = earnings_estimate.loc[period].get("growth")
        if growth is not None and pd.notna(growth):
            return float(growth)
    return None


# ─── Pass 2: Heavy signals (Tier 1+2 only, ~25-50 stocks) ───


def forward_pe(info: dict) -> float | None:
    """Forward P/E ratio from yfinance .info dict."""
    val = info.get("forwardPE")
    if val is not None and val > 0:
        return float(val)
    return None


def fcf_yield(info: dict) -> float | None:
    """Free cash flow yield = FCF / market cap. Returns as decimal."""
    fcf = info.get("freeCashflow")
    mcap = info.get("marketCap")
    if fcf is not None and mcap is not None and mcap > 0:
        return float(fcf / mcap)
    return None


def short_interest_pct(info: dict) -> float | None:
    """Short interest as percentage of float. Returns as decimal (0.01 = 1%)."""
    val = info.get("shortPercentOfFloat")
    if val is not None:
        return float(val)
    return None
