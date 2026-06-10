"""Compute street-target consensus and revision dynamics for one ticker.

Single source: yfinance. Snapshot via `analyst_price_targets` / `info`;
per-action time series via `upgrades_downgrades` (multi-year history,
same-day fresh on US large/mid caps).

Thresholds are calibrated from the literature on analyst-revision dynamics.
"""

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime

import pandas as pd
import yfinance as yf
from scipy import stats

logger = logging.getLogger(__name__)


# ─── Tunables (literature-calibrated) ────────────────────────────────────

RECENCY_DAYS = 120                 # IBES stale cutoff (Bloomberg desk norm)
VELOCITY_WINDOW_DAYS = 30          # Da-Schaumburg drift window
MATERIAL_PCT = 0.10                # Asquith 2005 materiality threshold
RERATING_COUNT_THRESHOLD = 3       # Loh-Stulz "needs >1 influential print"
RERATING_MAG_UP = 0.25             # Womack asymmetric drift (up)
RERATING_MAG_DOWN = -0.20          # Womack asymmetric drift (down)
HIGH_DISPERSION = 0.60             # >60% of median = noise
STALE_MASS_THRESHOLD = 0.50        # I/B/E/S stale-screen convention
OPTIMISM_HAIRCUT = 0.90            # Bradshaw/Dechow/You ~10% overshoot
FLAG_DECAY_DAYS = 45               # Brav-Lehavy long-horizon reversal
THIN_COVERAGE_N = 8                # ADR / international thin-coverage threshold
THIN_COVERAGE_STALE = 0.70


# ─── Result schema ───────────────────────────────────────────────────────


@dataclass
class StreetRead:
    """Full street-target read for one ticker, persistable to tracker.yaml."""

    ticker: str
    name: str
    current_price: float
    # Where the street thinks it's worth
    central: float
    central_method: str               # "trimmed_mean_10pct" or "median"
    median: float
    mean: float
    high: float
    low: float
    optimism_haircut_target: float
    central_vs_price_pct: float       # positive = central above price ("cheap")
    haircut_vs_price_pct: float
    # How much they disagree
    dispersion_pct: float
    # Coverage
    n_active_120d: int
    n_total_covering: int
    stale_mass_pct: float
    data_days_since_last_action: int
    # Direction of motion (30d)
    velocity_30d: int                 # signed (raises - cuts) of material moves
    firms_up: int
    firms_down: int
    avg_magnitude_up_pct: float
    avg_magnitude_down_pct: float
    # Composite
    flags: list[str]
    verdict: str
    verdict_detail: str
    verdict_short: str
    recent_prints: list[dict]
    last_pull: str                    # ISO date
    error: str | None = None
    snapshot_fallback: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Core analyzer ───────────────────────────────────────────────────────


def analyze(ticker: str) -> StreetRead:
    """Pull snapshot + time series from yfinance, compute the four diagnostics."""

    t = yf.Ticker(ticker)
    info = t.info or {}
    snap = t.analyst_price_targets or {}
    actions = t.upgrades_downgrades

    current = info.get("currentPrice") or snap.get("current")
    n_covering = info.get("numberOfAnalystOpinions") or 0
    name = info.get("shortName") or info.get("longName") or ticker
    today = datetime.utcnow().date().isoformat()

    if current is None:
        return _error_read(ticker, name, today, "no current price")
    if actions is None or len(actions) == 0:
        return _error_read(ticker, name, today, "no action history", current, snap)

    # ─── Normalize index ────────────────────────────────────────────────
    actions = actions.copy()
    if actions.index.tz is not None:
        actions.index = actions.index.tz_localize(None)

    now = pd.Timestamp.utcnow().tz_localize(None)
    cut_recency = now - pd.Timedelta(days=RECENCY_DAYS)
    cut_velocity = now - pd.Timedelta(days=VELOCITY_WINDOW_DAYS)

    # ─── Latest valid target per firm within recency window ────────────
    recent = actions[
        (actions.index >= cut_recency) & (actions["currentPriceTarget"] > 0)
    ]
    latest_per_firm = recent.sort_index().reset_index().groupby("Firm").last()
    n_active = len(latest_per_firm)

    if n_active == 0:
        return _error_read(
            ticker,
            name,
            today,
            "no active targets in last 120 days (likely yfinance cache staleness)",
            current,
            snap,
        )

    targets = latest_per_firm["currentPriceTarget"].astype(float)
    median_t = float(targets.median())
    mean_t = float(targets.mean())
    high_t = float(targets.max())
    low_t = float(targets.min())

    if n_active >= 12:
        central = float(stats.trim_mean(targets, 0.10))
        central_method = "trimmed_mean_10pct"
    else:
        central = median_t
        central_method = "median"

    dispersion = (high_t - low_t) / median_t if median_t > 0 else 0.0

    # ─── Velocity window: material moves in last 30 days ───────────────
    vel = actions[
        (actions.index >= cut_velocity)
        & (actions["priorPriceTarget"] > 0)
        & (actions["currentPriceTarget"] > 0)
    ].copy()
    vel["delta_pct"] = (vel["currentPriceTarget"] - vel["priorPriceTarget"]) / vel[
        "priorPriceTarget"
    ]
    up = vel[vel["delta_pct"] >= MATERIAL_PCT]
    down = vel[vel["delta_pct"] <= -MATERIAL_PCT]
    velocity = len(up) - len(down)
    mag_up = float(up["delta_pct"].mean()) if len(up) > 0 else 0.0
    mag_down = float(down["delta_pct"].mean()) if len(down) > 0 else 0.0

    # ─── Stale mass (% of covering analysts not refreshed in 120d) ─────
    if n_covering and n_covering > 0:
        stale_pct = max(0.0, (n_covering - n_active) / n_covering)
    else:
        stale_pct = 0.0

    # ─── Data freshness check (SMCI failure mode) ──────────────────────
    most_recent_action = actions.index.max()
    days_since_last = int((now - most_recent_action).days)
    data_source_stale = days_since_last > 30 and n_covering >= 5

    # ─── Thin coverage (ASML / ADR failure mode) ───────────────────────
    thin_coverage = (
        n_covering >= 5
        and n_active < THIN_COVERAGE_N
        and stale_pct > THIN_COVERAGE_STALE
    )

    # ─── Flags ─────────────────────────────────────────────────────────
    flags: list[str] = []
    if velocity >= RERATING_COUNT_THRESHOLD and mag_up >= RERATING_MAG_UP:
        flags.append("rerating_up")
    if velocity <= -RERATING_COUNT_THRESHOLD and mag_down <= RERATING_MAG_DOWN:
        flags.append("rerating_down")
    if dispersion > HIGH_DISPERSION:
        flags.append("high_dispersion")
    if stale_pct >= STALE_MASS_THRESHOLD:
        flags.append("stale_consensus")
    if data_source_stale:
        flags.append("data_source_stale")
    if thin_coverage:
        flags.append("data_coverage_thin")

    # Central-vs-price: positive means central is above price ("cheap" by street)
    central_vs_price = (central - current) / current
    haircut_target = central * OPTIMISM_HAIRCUT
    haircut_vs_price = (haircut_target - current) / current

    # ─── Verdict (rerating overrides static price-vs-target read) ──────
    verdict, detail, short = _decide_verdict(
        flags=flags,
        current=current,
        central=central,
        median_t=median_t,
        dispersion=dispersion,
        mag_up=mag_up,
        mag_down=mag_down,
        central_vs_price=central_vs_price,
        n_up=len(up),
        n_down=len(down),
    )

    # ─── Top recent material moves ─────────────────────────────────────
    recent_prints: list[dict] = []
    for date_, row in vel.sort_index(ascending=False).head(8).iterrows():
        recent_prints.append({
            "date": date_.strftime("%Y-%m-%d"),
            "firm": row["Firm"],
            "from": float(row["priorPriceTarget"]),
            "to": float(row["currentPriceTarget"]),
            "delta_pct": round(float(row["delta_pct"]) * 100, 1),
        })

    return StreetRead(
        ticker=ticker,
        name=name,
        current_price=round(float(current), 2),
        central=round(central, 2),
        central_method=central_method,
        median=round(median_t, 2),
        mean=round(mean_t, 2),
        high=round(high_t, 2),
        low=round(low_t, 2),
        optimism_haircut_target=round(haircut_target, 2),
        central_vs_price_pct=round(central_vs_price * 100, 1),
        haircut_vs_price_pct=round(haircut_vs_price * 100, 1),
        dispersion_pct=round(dispersion * 100, 1),
        n_active_120d=int(n_active),
        n_total_covering=int(n_covering),
        stale_mass_pct=round(stale_pct * 100, 1),
        data_days_since_last_action=days_since_last,
        velocity_30d=int(velocity),
        firms_up=int(len(up)),
        firms_down=int(len(down)),
        avg_magnitude_up_pct=round(mag_up * 100, 1),
        avg_magnitude_down_pct=round(mag_down * 100, 1),
        flags=flags,
        verdict=verdict,
        verdict_detail=detail,
        verdict_short=short,
        recent_prints=recent_prints,
        last_pull=today,
    )


# ─── Verdict logic ───────────────────────────────────────────────────────


def _decide_verdict(
    *,
    flags: list[str],
    current: float,
    central: float,
    median_t: float,
    dispersion: float,
    mag_up: float,
    mag_down: float,
    central_vs_price: float,
    n_up: int,
    n_down: int,
) -> tuple[str, str, str]:
    """Return (verdict, detail, short) — rerating overrides static reads."""

    if "rerating_up" in flags:
        detail = (
            f"Street rerating up: {n_up} firms raised by avg {mag_up*100:+.0f}% in "
            f"last {VELOCITY_WINDOW_DAYS}d. Consensus median ${median_t:.0f} is "
            f'stale; suppress "fully priced" read. Flag decays {FLAG_DECAY_DAYS}d '
            f"after last material print."
        )
        short = f"{n_up} firms raised by avg +{mag_up*100:.0f}% in 30d, central is stale"
        return "RERATING_UP", detail, short

    if "rerating_down" in flags:
        detail = (
            f"Street rerating down: {n_down} firms cut by avg {mag_down*100:+.0f}% in "
            f"last {VELOCITY_WINDOW_DAYS}d. Consensus is stale-high; suppress "
            f'"consensus supportive" read.'
        )
        short = f"{n_down} firms cut by avg {mag_down*100:.0f}% in 30d, support is melting"
        return "RERATING_DOWN", detail, short

    if "high_dispersion" in flags:
        detail = (
            f"Dispersion {dispersion*100:.0f}% > {HIGH_DISPERSION*100:.0f}% — "
            f"consensus too noisy to anchor. Rely on TA + own DCF."
        )
        short = (
            f"dispersion {dispersion*100:.0f}%, consensus too noisy, "
            "fall back to DCF + TA"
        )
        return "LOW_CONFIDENCE", detail, short

    if current >= 0.90 * central and dispersion < 0.25:
        detail = (
            f"Price ${current:.0f} >= 90% of central ${central:.0f}, dispersion "
            f"{dispersion*100:.0f}% tight. No fresh adds; trim if oversized."
        )
        short = "price at consensus, tight dispersion, no rerating wave"
        return "FULLY_PRICED", detail, short

    if (
        current <= 0.70 * central
        and dispersion < 0.40
        and "stale_consensus" not in flags
    ):
        detail = (
            f"Price ${current:.0f} <= 70% of central ${central:.0f}, dispersion "
            f"ok, fresh consensus. Entry is a TA question, not valuation."
        )
        short = (
            f"price {-central_vs_price*100:.0f}% below central, fresh data, entry is TA"
        )
        return "CONSENSUS_SUPPORTIVE", detail, short

    detail = "Price within neutral band; no consensus signal override fires."
    short = "no override fires; nothing material"
    return "NEUTRAL", detail, short


# ─── Helpers ─────────────────────────────────────────────────────────────


def _error_read(
    ticker: str,
    name: str,
    today: str,
    msg: str,
    current: float | None = None,
    snap: dict | None = None,
) -> StreetRead:
    """Return a sentinel StreetRead when we can't compute a real one."""
    return StreetRead(
        ticker=ticker,
        name=name,
        current_price=float(current) if current else 0.0,
        central=0.0,
        central_method="none",
        median=0.0,
        mean=0.0,
        high=0.0,
        low=0.0,
        optimism_haircut_target=0.0,
        central_vs_price_pct=0.0,
        haircut_vs_price_pct=0.0,
        dispersion_pct=0.0,
        n_active_120d=0,
        n_total_covering=0,
        stale_mass_pct=0.0,
        data_days_since_last_action=0,
        velocity_30d=0,
        firms_up=0,
        firms_down=0,
        avg_magnitude_up_pct=0.0,
        avg_magnitude_down_pct=0.0,
        flags=["data_missing"],
        verdict="NO_DATA",
        verdict_detail=msg,
        verdict_short=msg,
        recent_prints=[],
        last_pull=today,
        error=msg,
        snapshot_fallback=snap if snap else None,
    )
