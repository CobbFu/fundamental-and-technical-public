"""Momentum signal calculators — pure pandas functions.

Each function takes an OHLCV DataFrame and returns a single value.
No side effects, no API calls, no state. Mirrors src/calculators/beta.py pattern.

Academic foundations:
- Jegadeesh & Titman (1993): 2-12 month return
- Da, Gurun, Warachka: Frog-in-the-Pan (FIP) — smooth vs spiky momentum
- On-Balance Volume (OBV): volume confirming price trend
- Antonacci: Absolute momentum (market regime filter)
"""

import numpy as np
import pandas as pd


def momentum_return_2_12(df: pd.DataFrame) -> float | None:
    """12-month return excluding most recent month (Jegadeesh/Titman 2-12).

    Requires >= 252 trading days.
    Return = (price[t-21] / price[t-252]) - 1
    Skips last ~21 trading days to avoid short-term reversal effect.
    """
    if len(df) < 252:
        return None

    close = df["Close"].values
    # price ~1 month ago (skip last 21 days)
    price_recent = close[-22]  # ~1 month ago
    # price ~12 months ago
    price_old = close[-252]

    if price_old <= 0:
        return None

    return float((price_recent / price_old) - 1)


def frog_in_pan(df: pd.DataFrame) -> float:
    """FIP score: sign(12m_return) * (pct_negative_days - pct_positive_days).

    More negative FIP = smoother climb = higher quality momentum.
    NVDA 2023 had ~57% positive days — steady grind that flies under the radar.

    For ranking purposes, more negative = better momentum quality.
    """
    close = df["Close"].values
    if len(close) < 2:
        return 0.0

    # Use up to 252 days
    window = close[-min(252, len(close)):]
    daily_returns = np.diff(window) / window[:-1]

    positive_days = np.sum(daily_returns > 0)
    negative_days = np.sum(daily_returns < 0)
    total_days = len(daily_returns)

    if total_days == 0:
        return 0.0

    pct_positive = positive_days / total_days
    pct_negative = negative_days / total_days

    # Cumulative return over the window
    cumulative_return = (window[-1] / window[0]) - 1
    sign = 1.0 if cumulative_return >= 0 else -1.0

    return float(sign * (pct_negative - pct_positive))


def obv_trend(df: pd.DataFrame, ma_period: int = 20) -> bool:
    """True if OBV > its 20-day moving average (volume confirming price).

    OBV = cumulative sum where: close > prev → +volume, close < prev → -volume.
    Bullish when OBV is above its own moving average (institutional accumulation).
    """
    if len(df) < ma_period + 1:
        return False

    close = df["Close"].values
    volume = df["Volume"].values

    # Compute OBV
    price_changes = np.diff(close)
    obv_direction = np.sign(price_changes)
    obv_values = np.concatenate([[0], np.cumsum(obv_direction * volume[1:])])

    # Compare current OBV to its MA
    obv_ma = np.mean(obv_values[-ma_period:])
    return bool(obv_values[-1] > obv_ma)


def relative_strength_vs_sector(
    stock_df: pd.DataFrame,
    sector_df: pd.DataFrame,
    period: int = 63,
) -> float:
    """Stock return / sector return over trailing 3 months (63 trading days).

    Returns ratio > 1.0 means stock outperforms sector.
    """
    if len(stock_df) < period or len(sector_df) < period:
        return 1.0  # neutral if insufficient data

    stock_close = stock_df["Close"].values
    sector_close = sector_df["Close"].values

    stock_return = (stock_close[-1] / stock_close[-period]) - 1
    sector_return = (sector_close[-1] / sector_close[-period]) - 1

    # Avoid division by zero
    if abs(sector_return) < 1e-10:
        return 1.0 if stock_return >= 0 else 0.0

    # Return ratio: stock_return / sector_return
    # Both positive: ratio > 1 = outperforming
    # Sector negative, stock positive: strong outperformance → cap at 3.0
    # Sector positive, stock negative: underperforming → 0.0
    if sector_return < 0 and stock_return > 0:
        return 3.0
    if sector_return > 0 and stock_return < 0:
        return 0.0
    if sector_return < 0 and stock_return < 0:
        # Both declining: less decline = better, invert ratio
        return float(sector_return / stock_return) if stock_return != 0 else 0.0

    return float(stock_return / sector_return)


def ma_position(df: pd.DataFrame) -> tuple[bool, bool]:
    """Returns (above_50dma, above_200dma).

    Basic trend confirmation filter: price above both moving averages = uptrend.
    """
    close = df["Close"].values
    current = close[-1]

    above_50 = bool(current > np.mean(close[-50:])) if len(close) >= 50 else False
    above_200 = bool(current > np.mean(close[-200:])) if len(close) >= 200 else False

    return (above_50, above_200)


def absolute_momentum_check(spy_df: pd.DataFrame, tbill_rate: float) -> bool:
    """True if S&P 500 12-month return > T-bill rate (risk-on regime).

    Antonacci's absolute momentum filter: if the broad market isn't beating
    risk-free, avoid long equity momentum positions.
    """
    if len(spy_df) < 252:
        return True  # default to risk-on if insufficient data

    close = spy_df["Close"].values
    spy_return = (close[-1] / close[-252]) - 1

    return bool(spy_return > tbill_rate)


def composite_momentum_score(
    return_2_12: float | None,
    fip: float,
    obv: bool,
    rel_str: float,
    above_50: bool,
    above_200: bool,
) -> float:
    """Equal-weighted composite score. Returns 0-100.

    Components are normalized to [0, 1] then averaged:
    - return_2_12: clamped to [-1, 2] then scaled to [0, 1]
    - fip: inverted (more negative = better), clamped to [-0.3, 0.1] → [0, 1]
    - obv: 1.0 if True, 0.0 if False
    - rel_str: clamped to [0, 3] then scaled to [0, 1]
    - above_50, above_200: 1.0 if True, 0.0 if False
    """
    components: list[float] = []

    # Return 2-12: higher = better, clamp to [-1, 2]
    if return_2_12 is not None:
        r = max(-1.0, min(2.0, return_2_12))
        components.append((r + 1.0) / 3.0)  # map [-1, 2] → [0, 1]
    else:
        components.append(0.0)

    # FIP: more negative = better for uptrending stocks
    # Range roughly [-0.3, 0.1], invert so more negative → higher score
    fip_norm = max(0.0, min(1.0, (0.1 - fip) / 0.4))  # map [0.1, -0.3] → [0, 1]
    components.append(fip_norm)

    # Binary signals
    components.append(1.0 if obv else 0.0)
    components.append(1.0 if above_50 else 0.0)
    components.append(1.0 if above_200 else 0.0)

    # Relative strength: clamp [0, 3] → [0, 1]
    rs_norm = max(0.0, min(1.0, rel_str / 3.0))
    components.append(rs_norm)

    return float(np.mean(components) * 100)


def momentum_acceleration(
    df: pd.DataFrame, short_period: int = 63, long_period: int = 252
) -> float | None:
    """Ratio of annualized short-term return to long-term return."""
    close = df["Close"].values
    if len(close) < long_period:
        return None
    short_ret = close[-1] / close[-short_period] - 1
    long_ret = close[-1] / close[-long_period] - 1
    if long_ret <= 0:
        return None  # can't compute ratio for negative/zero 12m return
    if short_ret <= -1.0:
        return None  # 100%+ loss in short window — data error territory
    annualized_short = (1 + short_ret) ** (252 / short_period) - 1
    return annualized_short / long_ret


def fresh_stale_momentum(df: pd.DataFrame) -> str | None:
    """Classify momentum as fresh, maturing, or stale (Research Affiliates)."""
    close = df["Close"].values
    if len(close) < 504:
        return None  # need 2 years
    current_year_ret = close[-1] / close[-252] - 1
    if current_year_ret <= 0:
        return None  # not in momentum
    prior_year_ret = close[-252] / close[-504] - 1
    if prior_year_ret > 0.15:
        return "stale"
    if prior_year_ret < 0.05:
        return "fresh"
    return "maturing"


def ma_slope_200(df: pd.DataFrame) -> float | None:
    """Slope of 200-day MA over last 60 days, as pct per day (Weinstein stage)."""
    close = df["Close"].values
    if len(close) < 260:
        return None
    ma_200 = pd.Series(close).rolling(200).mean().values
    recent = ma_200[-60:]
    if np.isnan(recent[0]):
        return None
    coeffs = np.polyfit(np.arange(60), recent, 1)
    return float(coeffs[0] / recent[-1] * 100)  # pct per day


def slow_fast_agreement(df: pd.DataFrame) -> str:
    """Slow/fast momentum agreement (Goulding/Harvey/Mazzoleni 2023)."""
    close = df["Close"].values
    if len(close) < 252:
        return "bull"  # default to risk-on with insufficient data
    slow = close[-1] / close[-252] - 1  # 12-month
    fast = close[-1] / close[-22] - 1   # 1-month
    if slow >= 0 and fast >= 0:
        return "bull"
    if slow < 0 and fast < 0:
        return "bear"
    if slow >= 0 > fast:
        return "correction"
    return "rebound"
