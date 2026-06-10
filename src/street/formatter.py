"""Render StreetRead into the digest card (3 lines) or detail card (full).

`render_street_markdown` produces a small markdown block for embedding into
the morning digest under each action-tier card.
"""

from typing import Any

from src.street.analyzer import StreetRead


# ─── Adaptive interpretation words ───────────────────────────────────────


def _disp_short(d_pct: float) -> str:
    if d_pct < 25:
        return "tight"
    if d_pct < 60:
        return "normal"
    if d_pct < 100:
        return "wide"
    return "huge"


def _vel_short(
    net: int, mag_up_pct: float, mag_dn_pct: float, n_up: int, n_dn: int
) -> str:
    if net >= 3 and mag_up_pct >= 25:
        return "bull wave"
    if net <= -3 and mag_dn_pct <= -20:
        return "bear wave"
    if net >= 2:
        return "tilting up"
    if net <= -2:
        return "tilting down"
    if n_up == 0 and n_dn == 0:
        return "quiet"
    return "mixed"


def _stale_short(pct: float, thin_coverage: bool = False) -> str:
    if thin_coverage:
        return "thin-cover"
    if pct < 30:
        return "fresh"
    if pct < 50:
        return "mixed"
    return "stale"


def _mm_words(mean: float, median: float) -> str:
    if median <= 0:
        return ""
    diff = (mean - median) / median
    if abs(diff) < 0.05:
        return "Mean and median within 5% — consensus is symmetric (bulls and bears balanced)."
    if diff > 0:
        return (
            f"Mean (${mean:,.0f}) is {diff*100:.0f}% above median (${median:,.0f}) — "
            "a few bulls with very high targets are pulling the simple average up. "
            "The median ignores them; that's why we prefer it."
        )
    return (
        f"Mean (${mean:,.0f}) is {-diff*100:.0f}% below median (${median:,.0f}) — "
        "a few bears with very low targets are pulling the simple average down. "
        "The median ignores them; that's why we prefer it."
    )


# ─── Cards ───────────────────────────────────────────────────────────────


def digest_card(r: StreetRead) -> str:
    """Three-line summary for the morning digest."""
    if r.error:
        return f"  {r.ticker:<8}  STREET: ⚠ {r.error}"

    cvp = r.central_vs_price_pct
    direction = "above today" if cvp >= 0 else "below today"
    cvp_abs = abs(cvp)

    thin = "data_coverage_thin" in r.flags
    disp_w = _disp_short(r.dispersion_pct)
    vel_w = _vel_short(
        r.velocity_30d,
        r.avg_magnitude_up_pct,
        r.avg_magnitude_down_pct,
        r.firms_up,
        r.firms_down,
    )
    stale_w = _stale_short(r.stale_mass_pct, thin)

    header = f"  {r.ticker} · {r.name}"
    price_str = f"${r.current_price:,.2f}"
    pad = max(2, 76 - len(header) - len(price_str))
    line1 = header + (" " * pad) + price_str

    line2 = (
        f"  ─ Central ${r.central:,.0f} ({cvp_abs:.0f}% {direction})   "
        f"Disp {r.dispersion_pct:.0f}% {disp_w}   "
        f"Vel {r.velocity_30d:+d} {vel_w}   "
        f"Stale {r.stale_mass_pct:.0f}% {stale_w}"
    )

    line3 = f"  → {r.verdict} — {r.verdict_short}"

    if thin:
        line3 += "  (NB: thin/stale coverage)"

    return "\n".join([line1, line2, line3])


def detail_card(r: StreetRead) -> str:
    """Full per-ticker card with the four blocks + plain-English explainers."""
    if r.error:
        return f"  STREET: ⚠ {r.error}"

    bar = "─" * 72
    dbl = "═" * 72

    method_explainer = (
        f"10% trimmed mean (drop most-extreme bull + bear, average the rest) because "
        f"N={r.n_active_120d} ≥ 12 fresh analysts. With <12 we'd use median. "
        "Either way the result ignores one rogue outlier."
        if r.central_method == "trimmed_mean_10pct"
        else f"median (the middle target) because N={r.n_active_120d} < 12 fresh "
        "analysts. With ≥12 we switch to a 10% trimmed mean. Either way it's "
        "robust to one outlier."
    )

    cvp_abs = abs(r.central_vs_price_pct)
    cvp_dir = "above today" if r.central_vs_price_pct >= 0 else "below today"
    hvp_abs = abs(r.haircut_vs_price_pct)
    hvp_dir = "above today" if r.haircut_vs_price_pct >= 0 else "below today"

    disp_w = _disp_short(r.dispersion_pct)
    thin = "data_coverage_thin" in r.flags
    vel_w = _vel_short(
        r.velocity_30d,
        r.avg_magnitude_up_pct,
        r.avg_magnitude_down_pct,
        r.firms_up,
        r.firms_down,
    )

    o: list[str] = []
    o.append("")
    o.append(dbl)
    o.append(
        f"  {r.ticker} · {r.name}".ljust(60)
        + f"${r.current_price:,.2f}".rjust(12)
    )
    o.append(dbl)

    # Block 1 — Where the street thinks
    o.append("")
    o.append("  WHERE THE STREET THINKS IT'S WORTH")
    o.append(bar)
    o.append("")
    o.append(f"     Low target          ${r.low:>10,.2f}    the bear case (lowest single target)")
    o.append(f"     Median              ${r.median:>10,.2f}    middle target of {r.n_active_120d} fresh prints")
    o.append(f"     Mean                ${r.mean:>10,.2f}    simple average of those same prints")
    method_word = "10% trimmed mean" if r.central_method == "trimmed_mean_10pct" else "median"
    o.append(f"     CENTRAL ★           ${r.central:>10,.2f}    {method_word} — the headline anchor")
    o.append(f"     Haircut             ${r.optimism_haircut_target:>10,.2f}    central × 0.90 (analysts overshoot ~10%)")
    o.append(f"     High target         ${r.high:>10,.2f}    the bull case (highest single target)")
    o.append("")
    o.append(f"  ► Median vs Mean. {_mm_words(r.mean, r.median)}")
    o.append("")
    o.append(f"  ► Why the central. {method_explainer}")
    o.append("")
    o.append("  ► Haircut. 12-month analyst targets overshoot realized prices by")
    o.append("    ~10% on average (Bradshaw / Dechow & You). The haircut is the")
    o.append("    realistic anchor; the raw central is the optimistic anchor.")
    o.append("")
    o.append(f"  ► Where today's ${r.current_price:,.0f} sits:")
    o.append(
        f"       CENTRAL  ${r.central:,.0f}  is  {cvp_abs:.1f}% {cvp_dir}'s price"
    )
    o.append(
        f"       HAIRCUT  ${r.optimism_haircut_target:,.0f}  is  {hvp_abs:.1f}% {hvp_dir}'s price"
    )

    # Block 2 — Disagreement
    o.append("")
    o.append("  HOW MUCH DO THEY DISAGREE?")
    o.append(bar)
    o.append("")
    o.append(f"     Range          ${r.low:,.0f}  to  ${r.high:,.0f}")
    o.append(f"     Spread         ${r.high - r.low:,.0f}")
    o.append(f"     Dispersion     {r.dispersion_pct:.0f}%        = (high − low) ÷ median")
    o.append("")
    o.append(f"  ► {disp_w} consensus — " + {
        "tight": "the street largely agrees on fair value.",
        "normal": "normal range for a growth name.",
        "wide": "bulls and bears disagree materially.",
        "huge": "bulls and bears are pricing very different companies.",
    }[disp_w])
    o.append("")
    o.append("  ► Reading guide:   <25% tight   |   25–60% normal")
    o.append("                     60–100% wide  |   >100% huge")

    # Block 3 — Direction of motion
    o.append("")
    o.append(f"  WHICH WAY ARE THEY MOVING?   (last 30 days, moves ≥10%)")
    o.append(bar)
    o.append("")
    o.append(f"     Firms raising      {r.firms_up:>2}      avg move  {r.avg_magnitude_up_pct:+.0f}%")
    o.append(f"     Firms cutting      {r.firms_down:>2}      avg move  {r.avg_magnitude_down_pct:+.0f}%")
    o.append(f"     Net velocity      {r.velocity_30d:+3d}")
    o.append("")

    vel_explain = {
        "bull wave": f"BULL STAMPEDE — {r.firms_up} firms raised by avg +{r.avg_magnitude_up_pct:.0f}%, no material downgrades. Rerating wave in progress.",
        "bear wave": f"BEAR STAMPEDE — {r.firms_down} firms cut by avg {r.avg_magnitude_down_pct:.0f}%. Downgrade wave in progress.",
        "tilting up": f"tilting up — {r.firms_up} firms moving but not yet a wave.",
        "tilting down": f"tilting down — {r.firms_down} firms cutting but not yet a wave.",
        "quiet": "quiet — no material moves in either direction.",
        "mixed": "mixed — small moves in both directions, no clear direction.",
    }[vel_w]
    o.append(f"  ► {vel_explain}")

    if r.recent_prints:
        o.append("")
        o.append("     Recent prints:")
        o.append("       date         firm                       from →      to       Δ%")
        for p in r.recent_prints[:6]:
            o.append(
                f"       {p['date']}   {p['firm'][:22]:<22}    "
                f"${p['from']:>6,.0f} → ${p['to']:>6,.0f}  {p['delta_pct']:+7.1f}%"
            )

    # Block 4 — Freshness
    o.append("")
    o.append("  HOW FRESH IS THE PICTURE?")
    o.append(bar)
    o.append("")
    o.append(f"     Covering analysts        {r.n_total_covering:>3}")
    o.append(f"     Refreshed (<120d)        {r.n_active_120d:>3}")
    o.append(f"     Stale mass               {r.stale_mass_pct:.0f}%")
    o.append(f"     Last analyst action      {r.data_days_since_last_action}d ago")
    o.append("")
    if thin:
        o.append("  ► THIN COVERAGE — yfinance shows few active analysts on this name.")
        o.append("    Common for international ADRs (ASML, etc.). Treat consensus as a")
        o.append("    weak signal — fall back to TA + own DCF.")
    elif r.stale_mass_pct >= 50:
        o.append("  ► MAJORITY STALE — the official central reflects last quarter, not today.")
    elif r.stale_mass_pct >= 30:
        o.append("  ► some stale prints but consensus is broadly current.")
    else:
        o.append("  ► fresh — most analysts have refreshed their targets recently.")

    # Verdict
    o.append("")
    o.append(dbl)
    o.append(f"  VERDICT     {r.verdict}")
    o.append(dbl)

    return "\n".join(o)


def render_street_markdown(d: dict[str, Any] | None) -> str:
    """Render a persisted street_target dict as a markdown block.

    Designed for embedding under an action-tier card in the morning digest.
    Returns empty string if no data — caller should handle.
    """
    if not d or d.get("error"):
        if d and d.get("error"):
            return f"\n**Street consensus:** ⚠ {d['error']}\n"
        return ""

    verdict = d.get("verdict", "")
    verdict_short = d.get("verdict_short", "")
    changed_arrow = ""
    if d.get("verdict_changed") and d.get("previous_verdict"):
        changed_arrow = f" _(was {d['previous_verdict']})_"

    central = d.get("central", 0)
    cvp = d.get("central_vs_price_pct", 0)
    direction = "above today" if cvp >= 0 else "below today"

    disp = d.get("dispersion_pct", 0)
    disp_w = _disp_short(disp)
    vel = d.get("velocity_30d", 0)
    vel_w = _vel_short(
        vel,
        d.get("avg_magnitude_up_pct", 0),
        d.get("avg_magnitude_down_pct", 0),
        d.get("firms_up", 0),
        d.get("firms_down", 0),
    )
    stale = d.get("stale_mass_pct", 0)
    thin = "data_coverage_thin" in (d.get("flags") or [])
    stale_w = _stale_short(stale, thin)

    lines: list[str] = []
    lines.append("")
    lines.append("**Street consensus:**")
    lines.append("")
    lines.append(
        f"- Central **${central:,.0f}** ({abs(cvp):.0f}% {direction}) · "
        f"Disp **{disp:.0f}%** {disp_w} · "
        f"Vel **{vel:+d}** {vel_w} · "
        f"Stale **{stale:.0f}%** {stale_w}"
    )
    lines.append(f"- → **{verdict}** — {verdict_short}{changed_arrow}")

    prints = d.get("recent_prints") or []
    if prints:
        sample = []
        for p in prints[:4]:
            sample.append(
                f"{p['firm']} ${p['from']:,.0f}→${p['to']:,.0f} ({p['date'][5:]})"
            )
        lines.append(f"- Recent prints: {' · '.join(sample)}")

    lines.append("")
    return "\n".join(lines)
