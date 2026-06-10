"""Cascade-specific signal functions — regime shift detection.

Pure pandas/numpy functions. No side effects, no API calls.
These signals detect early breakouts in supply chain cascades.

Academic foundations:
- Breadth thrust: coordinated breakouts within a tier
- Volume ratio: institutional accumulation (20d/60d)
- Base breakout: Minervini Stage 1→2 detection
- 52-week high proximity: breakout potential
"""

import numpy as np
import pandas as pd


def return_3m(df: pd.DataFrame) -> float | None:
    """3-month return (63 trading days).

    Catches moves 9 months before 12-month return does.
    Returns None if < 63 days of data.
    """
    close = df["Close"].values
    if len(close) < 63:
        return None
    if close[-63] <= 0:
        return None
    return float(close[-1] / close[-63] - 1)


def volume_ratio(df: pd.DataFrame, short: int = 20, long: int = 60) -> float | None:
    """Ratio of short-term to long-term average volume.

    >1.5x = significant institutional activity.
    Returns None if insufficient data.
    """
    vol = df["Volume"].values
    if len(vol) < long:
        return None
    short_avg = np.mean(vol[-short:])
    long_avg = np.mean(vol[-long:])
    if long_avg <= 0:
        return None
    return float(short_avg / long_avg)


def distance_from_52w_high(df: pd.DataFrame) -> float | None:
    """How far below 52-week high. 0.0 = at high, 0.20 = 20% below.

    Returns None if < 63 days (need meaningful history).
    """
    close = df["Close"].values
    if len(close) < 63:
        return None
    high_252 = float(np.max(close[-min(252, len(close)):]))
    if high_252 <= 0:
        return None
    current = float(close[-1])
    return max(0.0, (high_252 - current) / high_252)


def base_breakout(
    df: pd.DataFrame,
    consolidation_days: int = 126,
    volume_threshold: float = 1.5,
) -> str:
    """Minervini-inspired base breakout detection.

    Returns one of:
    - "broke_out": price above base range on elevated volume
    - "breaking": price at top of base range with rising volume
    - "near_top": price near top of range but no volume confirmation
    - "in_base": price within consolidation range, below prior high
    - "above": price well above any base (already running)
    - "no_base": insufficient data for consolidation detection
    """
    close = df["Close"].values
    vol = df["Volume"].values

    if len(close) < consolidation_days + 5:
        return "no_base"

    # Define the base: exclude last 5 days so current breakout doesn't inflate base_high
    base_window = close[-(consolidation_days + 5):-5]
    base_high = float(np.max(base_window))
    base_low = float(np.min(base_window))

    if base_high <= 0 or base_low <= 0:
        return "no_base"

    base_range = (base_high - base_low) / base_low
    current = float(close[-1])

    # If price range is too wide (>50%), it's not a consolidation
    if base_range > 0.50:
        return "no_base"

    # Check volume: is recent volume elevated vs base average?
    recent_vol_avg = float(np.mean(vol[-5:])) if len(vol) >= 5 else 0
    base_vol_avg = (
        float(np.mean(vol[-consolidation_days:])) if len(vol) >= consolidation_days else 0
    )
    vol_elevated = (
        recent_vol_avg > base_vol_avg * volume_threshold
        if base_vol_avg > 0
        else False
    )

    # Price position relative to base
    pct_from_base_high = (current - base_high) / base_high

    if pct_from_base_high > 0.05:
        # Price is >5% above the base high
        return "above" if not vol_elevated else "broke_out"

    if pct_from_base_high > -0.02:
        # Price within 2% of base high
        if vol_elevated:
            return "breaking"
        return "near_top"

    # Price below base high
    return "in_base"
