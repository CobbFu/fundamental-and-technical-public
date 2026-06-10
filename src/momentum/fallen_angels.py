"""Fallen Angel detection — quality companies in sustained decline.

Identifies stocks 25-40% off 52-week highs with intact fundamentals,
using simplified Piotroski F-Score and Altman Z-Score from yfinance data.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def drawdown_from_high(df: pd.DataFrame) -> float:
    """Percentage decline from 52-week high. Returns 0.0 to 1.0.

    0.0 = at high, 0.30 = 30% below high.
    """
    if len(df) < 1:
        return 0.0

    close = df["Close"].values
    high_252 = np.max(close[-min(252, len(close)):])

    if high_252 <= 0:
        return 0.0

    current = close[-1]
    return float(max(0.0, (high_252 - current) / high_252))


def simplified_piotroski_f_score(info: dict) -> int:
    """Simplified F-Score (0-9) from yfinance .info dict.

    Uses available fields for the 9 Piotroski signals.
    Unavailable signals score 0 (conservative).

    Signals:
    1. ROA > 0 (profitability)
    2. Operating CF > 0
    3. ROA increasing (vs prior year — approximated)
    4. Accruals: operating CF > net income (earnings quality)
    5. Leverage decreasing (debt/assets)
    6. Current ratio increasing
    7. No share dilution
    8. Gross margin increasing
    9. Asset turnover increasing
    """
    score = 0

    # 1. ROA > 0
    roa = info.get("returnOnAssets")
    if roa is not None and roa > 0:
        score += 1

    # 2. Operating CF > 0
    ocf = info.get("operatingCashflow")
    if ocf is not None and ocf > 0:
        score += 1

    # 3. ROA trend — can't easily get prior year from .info, skip (conservative)

    # 4. Accruals: OCF > Net Income (earnings quality)
    net_income = info.get("netIncomeToCommon")
    if ocf is not None and net_income is not None and ocf > net_income:
        score += 1

    # 5. Leverage: debt/assets ratio (lower = better, but we need trend)
    # Proxy: debtToEquity < 100% as a quality filter
    dte = info.get("debtToEquity")
    if dte is not None and dte < 100:
        score += 1

    # 6. Current ratio > 1.0
    cr = info.get("currentRatio")
    if cr is not None and cr > 1.0:
        score += 1

    # 7. No dilution: shares outstanding not increasing
    # Can't measure trend from .info, use float shares vs total shares as proxy
    float_shares = info.get("floatShares")
    total_shares = info.get("sharesOutstanding")
    if float_shares and total_shares and float_shares / total_shares > 0.85:
        score += 1  # high float ratio suggests minimal dilution/lockup

    # 8. Gross margin positive and healthy (> 30% as proxy for "good")
    gm = info.get("grossMargins")
    if gm is not None and gm > 0.30:
        score += 1

    # 9. Revenue per share growing (proxy: positive revenue growth)
    rg = info.get("revenueGrowth")
    if rg is not None and rg > 0:
        score += 1

    return score


def simplified_altman_z_score(info: dict) -> float | None:
    """Altman Z-Score = 1.2*WC/TA + 1.4*RE/TA + 3.3*EBIT/TA + 0.6*MktCap/TL + 1.0*Rev/TA.

    > 2.99 = safe zone, 1.81-2.99 = grey zone, < 1.81 = distress zone.
    Returns None if insufficient data.
    """
    total_assets = info.get("totalAssets")
    if not total_assets or total_assets <= 0:
        return None

    # Working Capital / Total Assets
    wc = _safe_get(info, "workingCapital", None)
    if wc is None:
        # Approximate: current assets - current liabilities
        ca = _safe_get(info, "totalCurrentAssets", None)
        cl = _safe_get(info, "totalCurrentLiabilities", None)
        if ca is not None and cl is not None:
            wc = ca - cl
        else:
            return None

    # Retained Earnings / Total Assets
    re = _safe_get(info, "retainedEarnings", None)
    if re is None:
        return None

    # EBIT / Total Assets (use ebitda as proxy)
    ebit = _safe_get(info, "ebitda", None)
    if ebit is None:
        return None

    # Market Cap / Total Liabilities (prefer totalLiabilities; fall back to totalDebt)
    mkt_cap = _safe_get(info, "marketCap", None)
    total_liabilities = _safe_get(info, "totalLiabilities", None)
    if total_liabilities is None:
        total_liabilities = _safe_get(info, "totalDebt", None)  # approximation
    if mkt_cap is None or total_liabilities is None or total_liabilities <= 0:
        return None

    # Revenue / Total Assets
    revenue = _safe_get(info, "totalRevenue", None)
    if revenue is None:
        return None

    ta = float(total_assets)
    z = (
        1.2 * (wc / ta)
        + 1.4 * (re / ta)
        + 3.3 * (ebit / ta)
        + 0.6 * (mkt_cap / total_liabilities)
        + 1.0 * (revenue / ta)
    )
    return float(z)


def is_fallen_angel(
    drawdown: float,
    f_score: int,
    z_score: float | None,
    market_cap: float | None,
    fcf: float | None,
    *,
    drawdown_min: float = 0.25,
    drawdown_max: float = 0.40,
    f_score_min: int = 6,
    z_score_min: float = 2.5,
    market_cap_min: float = 5e9,
) -> bool:
    """True if stock passes all fallen angel quality filters.

    Criteria:
    - Drawdown between 25-40% (deep enough to be interesting, not structural damage)
    - Piotroski F-Score >= 6 (fundamentals intact)
    - Altman Z-Score > 2.5 (not headed for bankruptcy)
    - Market cap > $5B (institutional quality)
    - Free cash flow positive (company can fund itself)
    """
    if not (drawdown_min <= drawdown <= drawdown_max):
        return False
    if f_score < f_score_min:
        return False
    if z_score is not None and z_score < z_score_min:
        return False
    if z_score is None:
        return False  # conservative: require z-score data
    if market_cap is not None and market_cap < market_cap_min:
        return False
    if market_cap is None:
        return False  # require market cap
    if fcf is not None and fcf <= 0:
        return False
    if fcf is None:
        return False  # require FCF data

    return True


def _safe_get(d: dict, key: str, default=None):
    """Get numeric value from dict, returning default if missing or non-numeric."""
    val = d.get(key)
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default
