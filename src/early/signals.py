"""Early-stage signal calculators — the accumulation footprint.

Pure pandas/numpy functions (mirrors src/momentum/signals.py): each takes an
OHLCV DataFrame (+ a benchmark for relative-strength) and returns a single value.
No side effects, no API calls. These detect the *base* before the run — the
opposite of momentum's trailing-return ranking.

Leading tells:
- O'Neil: relative-strength line makes a new high BEFORE price.
- Wyckoff/OBV: quiet accumulation — OBV rising while price is flat.
- Minervini: volatility contraction (the coiled spring).
- Weinstein: Stage 1 base -> Stage 2 markup transition (200-MA turn).
"""

import numpy as np
import pandas as pd

from src.cascade.signals import base_breakout, distance_from_52w_high
from src.momentum.signals import ma_slope_200


def rs_line(
    stock_df: pd.DataFrame, bench_df: pd.DataFrame | None, lookback: int = 126
) -> float | None:
    """Slope of the relative-strength line (close / benchmark) over `lookback`.

    Positive while price is flat = the stock is quietly outperforming — the
    leading tell that precedes a breakout. Returns pct-per-bar, or None.
    """
    if bench_df is None or len(stock_df) < lookback:
        return None
    s = stock_df["Close"].astype(float)
    b = bench_df["Close"].astype(float).reindex(stock_df.index).ffill()
    rs = (s / b).dropna().to_numpy()
    if len(rs) < lookback:
        return None
    recent = rs[-lookback:]
    slope = float(np.polyfit(np.arange(lookback), recent, 1)[0])
    last = float(recent[-1]) if recent[-1] != 0 else 1e-9
    return float(slope / last * 100)


def rs_line_new_high(
    stock_df: pd.DataFrame, bench_df: pd.DataFrame | None, window: int = 126
) -> bool | None:
    """True if the RS line is at a `window` high WHILE price is not (RS leads price).

    O'Neil's highest-quality early tell: relative strength breaks out before the
    chart does. Returns None if insufficient data or no benchmark.
    """
    if bench_df is None or len(stock_df) < window:
        return None
    s = stock_df["Close"].astype(float)
    b = bench_df["Close"].astype(float).reindex(stock_df.index).ffill()
    rs = (s / b).dropna().to_numpy()
    price = s.to_numpy()
    if len(rs) < window or len(price) < window:
        return None
    rs_high = float(rs[-1]) >= float(np.max(rs[-window:])) * 0.999
    price_high = float(price[-1]) >= float(np.max(price[-window:])) * 0.999
    return bool(rs_high and not price_high)


def accumulation_score(df: pd.DataFrame, flat_window: int = 60) -> float:
    """OBV rising while price is flat (quiet institutional accumulation) -> [0, 1].

    Zero unless price is roughly flat over `flat_window` (a base) AND OBV slopes up.
    """
    close = df["Close"].to_numpy(dtype=float)
    vol = df["Volume"].to_numpy(dtype=float)
    if len(close) < flat_window + 1:
        return 0.0
    if close[-flat_window] <= 0:
        return 0.0
    if abs(close[-1] / close[-flat_window] - 1) > 0.20:
        return 0.0  # not a base — price has already moved
    obv = np.concatenate([[0.0], np.cumsum(np.sign(np.diff(close)) * vol[1:])])
    slope = float(np.polyfit(np.arange(flat_window), obv[-flat_window:], 1)[0])
    if slope <= 0:
        return 0.0
    avg_vol = float(np.mean(vol[-flat_window:])) + 1e-9
    return float(np.clip(slope / avg_vol * 0.5 + 0.5, 0.0, 1.0))


def volatility_contraction(df: pd.DataFrame, window: int = 60) -> float:
    """Bollinger-band width contracting over `window` -> [0, 1] (1 = strong squeeze)."""
    close = pd.Series(df["Close"].to_numpy(dtype=float))
    if len(close) < window + 20:
        return 0.0
    basis = close.rolling(20).mean()
    sd = close.rolling(20).std()
    width = (4 * sd) / basis  # normalized BB width (upper-lower)/basis
    recent = width.dropna().to_numpy()
    if len(recent) < window:
        return 0.0
    recent = recent[-window:]
    slope = float(np.polyfit(np.arange(window), recent, 1)[0])
    mean_w = float(np.mean(recent)) + 1e-9
    return float(np.clip(-slope / mean_w * 10, 0.0, 1.0))  # contracting -> positive


def weinstein_stage(df: pd.DataFrame) -> str:
    """Classify Weinstein stage via daily 200-MA slope (30-WMA proxy) + base state.

    Returns: "STAGE1_BASE" (basing — buyable zone), "STAGE1_2_TURN" (markup
    beginning — best entry), "STAGE2" (already running — disqualify),
    "STAGE4" (downtrend — avoid).
    """
    close = df["Close"].to_numpy(dtype=float)
    if len(close) < 260:
        return "STAGE1_BASE"  # too little history -> treat as basing
    ma200 = pd.Series(close).rolling(200).mean().to_numpy()
    slope = ma_slope_200(df)  # pct/day over last 60d
    if slope is None or np.isnan(ma200[-1]):
        return "STAGE1_BASE"
    above = close[-1] > ma200[-1]
    bp = base_breakout(df)
    if slope < -0.02 and not above:
        return "STAGE4"
    if slope > 0.05 and above:
        return "STAGE2"  # already extended
    if slope > 0.02 and above and bp in ("breaking", "broke_out", "near_top"):
        return "STAGE1_2_TURN"
    return "STAGE1_BASE"


def recent_return(df: pd.DataFrame, lookback: int = 126) -> float | None:
    """Trailing return over `lookback` bars. Used as a short-history ceiling proxy
    when the 12-month return is unavailable (recent spins/IPOs), so a name that has
    ALREADY ripped in its first months is not mistaken for a base.
    """
    close = df["Close"].to_numpy(dtype=float)
    if len(close) < lookback or close[-lookback] <= 0:
        return None
    return float(close[-1] / close[-lookback] - 1)


def reaccumulation_base(
    df: pd.DataFrame,
    *,
    min_pullback: float = 0.15,
    max_pullback: float = 0.55,
    min_bars_since_high: int = 30,
) -> bool:
    """Door-2 (v2): a name that RAN, then re-based — the next-leg setup.

    True when price has pulled back a meaningful (but not collapse-level) amount
    from its 52-week high, has been off that high for weeks, and is now
    consolidating (volatility contracting OR a clean Stage-1 read). The pullback +
    "off the high for weeks" conditions are what stop this from re-admitting a
    name that is simply making new highs (that is momentum, handled elsewhere).
    """
    close = df["Close"].to_numpy(dtype=float)
    if len(close) < 200:
        return False
    pullback = distance_from_52w_high(df)  # 0.0 at high, positive below
    if pullback is None or pullback < min_pullback or pullback > max_pullback:
        return False
    window = close[-min(252, len(close)):]
    bars_since_high = len(window) - 1 - int(np.argmax(window))
    if bars_since_high < min_bars_since_high:
        return False
    return volatility_contraction(df) > 0.0 or weinstein_stage(df) == "STAGE1_BASE"


def base_proximity(df: pd.DataFrame, consolidation_days: int = 126) -> float | None:
    """Distance of price above its multi-month base high. 0.0 = at base high.

    Positive = above the base (e.g. 0.06 = 6% above). Negative = still inside the
    base. Used by the gate to reject names that have run >30% past their base.
    Returns None if insufficient history (recent IPOs handled via the recency path).
    """
    close = df["Close"].to_numpy(dtype=float)
    if len(close) < consolidation_days + 5:
        return None
    base_window = close[-(consolidation_days + 5):-5]
    base_high = float(np.max(base_window))
    if base_high <= 0:
        return None
    current = float(close[-1])
    return float((current - base_high) / base_high)
