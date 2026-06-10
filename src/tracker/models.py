"""Dataclasses for tracker.yaml entries.

Keep fields and ordering stable; the YAML round-trips through
`dataclasses.asdict` so renames here are renames in the file.
"""

from dataclasses import dataclass, field
from typing import Literal

Verdict = Literal[
    "buy",
    "vcp_buy",
    "stage2_add",
    "ep_probe",
    "watch",
    "hold",
    "hold_tighten",
    "trim",
    "exit",
    "dont_chase",
]

# More conservative verdicts have lower indices. Used by verdict.compose_verdict
# to take the worse of two timeframes when in mean-reversion regime.
# Trend-regime verdicts sit between watch and buy: they are aggressive entries
# but conditioned on a tight base + climax veto, not naked breakouts.
VERDICT_CONSERVATISM: list[Verdict] = [
    "exit",
    "trim",
    "dont_chase",
    "hold_tighten",
    "hold",
    "watch",
    "ep_probe",
    "stage2_add",
    "vcp_buy",
    "buy",
]

# Regime label — which framework produced the verdict.
Regime = Literal["stage2", "mean_reversion"]

Flag = str  # machine-readable tag, e.g. "parabolic_trifecta_1W"


@dataclass
class Alert:
    price: float
    type: str  # "crossing", "less_than", "greater_than"
    note: str = ""
    set_in_tv: bool = False  # best-effort flag — refresh updates this


@dataclass
class Plan:
    entry_trigger: str = ""
    stop_loss: float | None = None
    add_zones: list[float] = field(default_factory=list)
    trim_zones: list[float] = field(default_factory=list)


@dataclass
class Thesis:
    cascade: str = ""
    summary: str = ""
    conviction: Literal["high", "medium", "low"] = "medium"
    time_horizon: Literal["tactical", "6-18m", "multi-year"] = "6-18m"
    target_size_pct: float = 5.0
    what_would_change_my_mind: str = ""


@dataclass
class TimeframeRead:
    timeframe: str  # "1D" or "1W"
    price: float
    ema: dict[int, float] = field(default_factory=dict)  # {20: ..., 50: ..., 200: ...}
    rsi: float = 0.0
    rsi_ma: float | None = None
    macd: dict[str, float] = field(default_factory=dict)  # line / signal / hist
    bb: dict[str, float] = field(default_factory=dict)  # upper / basis / lower
    volume: float | None = None
    # Trend-following derived fields. All optional — verdict.py gates each
    # archetype on the data being present, so old entries without these
    # simply route to mean-reversion. Populated by /ta-read and /track-refresh
    # from OHLCV history at read time.
    # v2 derived fields (kept for back-compat; verdict.py falls back to these
    # when v4 fields are absent on older entries).
    return_4w_pct: float | None = None        # for climax-top veto
    return_12m_pct: float | None = None       # legacy regime-gate input (v4 uses 26w + 30-WMA)
    base_range_pct: float | None = None       # range of last 15-25 bars / price
    consecutive_up_days: int | None = None    # legacy (v4 dropped the 3-up-days veto)
    volume_ratio: float | None = None         # today's vol / 20-day avg (v4 uses z-score/notional)
    range_atr_ratio: float | None = None      # intraday range / ATR (v4 uses gap-aware version)
    close_in_top_quartile: bool | None = None # legacy ≥0.75 (v4 uses close_position_in_range)
    # ---- v4 derived fields (2026-05-15 — see methodology-v4.md for evidence) ----
    return_26w_pct: float | None = None              # emergence test (post-drawdown Stage 1→2)
    sma_30w: float | None = None                     # 30-week SMA of weekly closes (Weinstein)
    sma_30w_rising: bool | None = None               # today's 30-WMA > 30-WMA 4 weeks ago
    volume_z_score: float | None = None              # scale-invariant catalyst-volume test
    volume_dollar_notional: float | None = None      # today_close × today_volume (absolute floor)
    gap_aware_range_atr_ratio: float | None = None   # includes overnight gap — earnings-gap EP
    close_position_in_range: float | None = None     # (close − low) / (high − low) ∈ [0, 1]
    # ---- v5 derived fields (2026-05-15 — methodology-gaps-v5.md) ----
    # Minervini VCP morphology — list of pullback percentages from most recent
    # to oldest swing-high. Populated by /ta-read from OHLCV peaks-and-troughs
    # analysis. Three or more progressively tighter contractions (each ≤ 70%
    # of the previous) signals a textbook VCP setup BEFORE the breakout fires.
    # None = not computed (older entries fall back to v4 stub behaviour).
    vcp_contractions: list[float] | None = None
    # Pivot high for the VCP setup — the most recent swing high the breakout
    # would clear. Used together with `vcp_contractions` by is_vcp_breakout.
    vcp_pivot_high: float | None = None


@dataclass
class LastRefresh:
    ts: str  # ISO datetime
    verdict: Verdict
    previous_verdict: Verdict | None = None
    verdict_changed: bool = True
    flags: list[Flag] = field(default_factory=list)
    daily: TimeframeRead | None = None
    weekly: TimeframeRead | None = None
    notes: str = ""
    error: str | None = None  # populated if the read for this entry failed
    # Which framework produced the verdict. None = legacy entry (pre-regime-gate).
    regime: Regime | None = None


@dataclass
class TrackerEntry:
    ticker: str
    state: Literal["held", "watching", "exited"] = "watching"
    added: str = ""  # ISO date — when first added
    thesis: Thesis = field(default_factory=Thesis)
    plan: Plan = field(default_factory=Plan)
    alerts: list[Alert] = field(default_factory=list)
    last_refresh: LastRefresh | None = None
    # Street-target intelligence (analyst consensus + revision dynamics).
    # Stored as dict for YAML-friendly round-trip — schema documented in
    # `src.street.analyzer.StreetRead.to_dict()`. Two extra keys added by the
    # tracker layer for delta detection: `previous_verdict`, `verdict_changed`.
    street_target: dict | None = None


@dataclass
class Tracker:
    version: int = 1
    updated: str = ""  # ISO date — last write
    entries: list[TrackerEntry] = field(default_factory=list)
