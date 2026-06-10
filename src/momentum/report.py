"""Markdown report formatters for Telegram delivery.

Generates formatted reports matching the Session 86 design:
- Weekly momentum radar (tiered, with change indicators)
- Weekly fallen angel report
- Daily new-highs signal

Tables are wrapped in code blocks for monospace rendering on Telegram.
"""

from src.momentum.scanner import (
    DailyHighsResult,
    FallenAngelResult,
    ScanResult,
    TierEntry,
)


def _universe_label(universe: str) -> str:
    """Return human-readable universe label."""
    if universe == "eu":
        return "Europe (STOXX 600 approx.)"
    return "US (Russell 1000)"


def format_momentum_report(
    result: ScanResult, universe: str = "us",
) -> str:
    """Format weekly momentum radar report for Feishu delivery."""
    lines: list[str] = []

    # Header
    label = _universe_label(universe)
    lines.append(f"# Momentum Radar ({label}) — Week of {result.date}")
    lines.append("")
    lines.append(
        f"Universe: {result.universe_size} stocks scanned | "
        f"Market regime: **{result.market_regime.upper()}**"
    )
    lines.append("")

    # Tier 1
    if result.tier1:
        lines.append("## Tier 1 (Top conviction)")
        lines.append("")
        lines.append("### Momentum Signals")
        lines.append(_price_table(result.tier1))
        lines.append("")
        fund_table = _fundamentals_table(result.tier1)
        if fund_table:
            lines.append("### Fundamental Signals")
            lines.append(fund_table)
            lines.append("")

    # Tier 2
    if result.tier2:
        lines.append("## Tier 2 (Emerging)")
        lines.append("")
        lines.append("### Momentum Signals")
        lines.append(_price_table(result.tier2))
        lines.append("")
        fund_table = _fundamentals_table(result.tier2)
        if fund_table:
            lines.append("### Fundamental Signals")
            lines.append(fund_table)
            lines.append("")

    # Tier 3
    if result.tier3:
        lines.append("## Tier 3 (Watchlist)")
        lines.append("")
        lines.append(_price_table(result.tier3))
        lines.append("")

    # Stage summary
    all_entries = result.tier1 + result.tier2 + result.tier3
    early = [e for e in all_entries if e.stage == "EARLY"]
    mid = [e for e in all_entries if e.stage == "MID"]
    late = [e for e in all_entries if e.stage == "LATE"]

    lines.append(
        f"**Stages:** {len(early)} early, {len(mid)} mid, {len(late)} late"
    )
    lines.append("")

    # Fresh Momentum Spotlight
    if early:
        lines.append("### Fresh Momentum Spotlight")
        lines.append(
            "New trends with accelerating momentum — "
            "highest alpha potential for new entries."
        )
        lines.append("")
        for e in early:
            accel_str = (
                f", accelerating at {e.acceleration:.1f}x"
                if e.acceleration is not None
                else ""
            )
            lines.append(f"- **{e.name}** ({e.ticker}){accel_str}")
        lines.append("")

    # Stale Momentum Warning
    if late:
        lines.append("### Stale Momentum Warning")
        lines.append(
            "Trends running 2+ years or decelerating — "
            "reversal risk elevated, avoid new entries."
        )
        lines.append("")
        for e in late:
            reasons = _explain_late(e)
            lines.append(f"- **{e.name}** ({e.ticker}) — {reasons}")
        lines.append("")

    # Changes this week
    changes = []
    if result.promotions:
        for e in result.promotions:
            changes.append(f"- **{e.name}** ({e.ticker}) promoted to Tier {e.tier}")
    if result.new_entries:
        for e in result.new_entries:
            changes.append(
                f"- **{e.name}** ({e.ticker}) new on radar "
                f"(12m {_pct(e.return_12m)}, stage {e.stage})"
            )
    if result.demotions:
        for e in result.demotions:
            changes.append(f"- **{e.name}** ({e.ticker}) demoted to Tier {e.tier}")
    if result.drops:
        lines_drop = ", ".join(result.drops)
        changes.append(
            f"- **Dropped off:** {lines_drop} — "
            "composite score fell below Tier 3 threshold "
            "(momentum weakened or reversal detected)"
        )

    if changes:
        lines.append("### Changes This Week")
        lines.extend(changes)
        lines.append("")

    # Risk-off warning
    if result.market_regime == "risk-off":
        benchmark = "STOXX 600" if universe == "eu" else "S&P 500"
        lines.append(
            f"> **RISK-OFF:** {benchmark} 12-month return is below T-bill rate. "
            "Momentum positions carry elevated crash risk."
        )
        lines.append("")

    return "\n".join(lines)


# Feishu message limit ~4K chars. Split at natural boundaries.
_FEISHU_CHAR_LIMIT = 3500


def format_momentum_report_parts(
    result: ScanResult, universe: str = "us",
) -> list[str]:
    """Format report as a list of Feishu-safe message parts.

    Splits at tier boundaries to avoid mid-table breaks.
    Each part stays under ~3500 chars (Feishu safe margin).
    """
    parts: list[str] = []
    label = _universe_label(universe)

    # Part 1: Header + Tier 1
    p1: list[str] = []
    p1.append(f"# Momentum Radar ({label}) — Week of {result.date}")
    p1.append("")
    p1.append(
        f"Universe: {result.universe_size} stocks scanned | "
        f"Market regime: **{result.market_regime.upper()}**"
    )
    p1.append("")
    if result.tier1:
        p1.append("## Tier 1 (Top conviction)")
        p1.append("")
        p1.append("### Momentum Signals")
        p1.append(_price_table(result.tier1))
        p1.append("")
        fund_table = _fundamentals_table(result.tier1)
        if fund_table:
            p1.append("### Fundamental Signals")
            p1.append(fund_table)
            p1.append("")
    parts.append("\n".join(p1))

    # Part 2+3: Tier 2 — split momentum and fundamentals into separate
    # messages since 15 stocks × 2 tables exceeds Feishu's ~4K limit
    if result.tier2:
        p2: list[str] = []
        p2.append("## Tier 2 (Emerging)")
        p2.append("")
        p2.append("### Momentum Signals")
        p2.append(_price_table(result.tier2))
        p2.append("")
        parts.append("\n".join(p2))

        fund_table = _fundamentals_table(result.tier2)
        if fund_table:
            p2f: list[str] = []
            p2f.append("### Tier 2 — Fundamental Signals")
            p2f.append(fund_table)
            p2f.append("")
            parts.append("\n".join(p2f))

    # Part 4+: Tier 3 — up to 50 stocks, split into chunks for Feishu
    if result.tier3:
        # Split tier 3 into chunks that fit Feishu's ~3500 char limit
        chunk_size = 15
        for i in range(0, len(result.tier3), chunk_size):
            chunk = result.tier3[i:i + chunk_size]
            pt3: list[str] = []
            if i == 0:
                pt3.append("## Tier 3 (Watchlist)")
            else:
                pt3.append("## Tier 3 (continued)")
            pt3.append("")
            pt3.append(_price_table(chunk))
            pt3.append("")
            parts.append("\n".join(pt3))

    # Final part: Stages, Spotlight, Warnings, Changes
    p3: list[str] = []
    all_entries = result.tier1 + result.tier2 + result.tier3
    early = [e for e in all_entries if e.stage == "EARLY"]
    mid = [e for e in all_entries if e.stage == "MID"]
    late = [e for e in all_entries if e.stage == "LATE"]

    p3.append(
        f"**Stages:** {len(early)} early, {len(mid)} mid, {len(late)} late"
    )
    p3.append("")

    if early:
        p3.append("### Fresh Momentum Spotlight")
        p3.append(
            "New trends with accelerating momentum — "
            "highest alpha potential for new entries."
        )
        p3.append("")
        for e in early:
            accel_str = (
                f", accelerating at {e.acceleration:.1f}x"
                if e.acceleration is not None
                else ""
            )
            p3.append(f"- **{e.name}** ({e.ticker}){accel_str}")
        p3.append("")

    if late:
        p3.append("### Stale Momentum Warning")
        p3.append(
            "Trends running 2+ years or decelerating — "
            "reversal risk elevated, avoid new entries."
        )
        p3.append("")
        for e in late:
            reasons = _explain_late(e)
            p3.append(f"- **{e.name}** ({e.ticker}) — {reasons}")
        p3.append("")

    changes = []
    if result.promotions:
        for e in result.promotions:
            changes.append(f"- **{e.name}** ({e.ticker}) promoted to Tier {e.tier}")
    if result.new_entries:
        for e in result.new_entries:
            changes.append(
                f"- **{e.name}** ({e.ticker}) new on radar "
                f"(12m {_pct(e.return_12m)}, stage {e.stage})"
            )
    if result.demotions:
        for e in result.demotions:
            changes.append(f"- **{e.name}** ({e.ticker}) demoted to Tier {e.tier}")
    if result.drops:
        lines_drop = ", ".join(result.drops)
        changes.append(
            f"- **Dropped off:** {lines_drop} — "
            "composite score fell below Tier 3 threshold "
            "(momentum weakened or reversal detected)"
        )
    if changes:
        p3.append("### Changes This Week")
        p3.extend(changes)
        p3.append("")

    if result.market_regime == "risk-off":
        benchmark = "STOXX 600" if universe == "eu" else "S&P 500"
        p3.append(
            f"> **RISK-OFF:** {benchmark} 12-month return is below T-bill rate. "
            "Momentum positions carry elevated crash risk."
        )
        p3.append("")

    if p3:
        parts.append("\n".join(p3))

    return parts


def format_fallen_angel_report(result: FallenAngelResult) -> str:
    """Format weekly fallen angel report for Feishu delivery."""
    lines: list[str] = []

    lines.append(f"# Fallen Angel Scanner — {result.date}")
    lines.append("")
    lines.append(
        f"Candidates scanned: {result.candidates_scanned} | "
        f"Quality passes: {len(result.angels)}"
    )
    lines.append("")

    if not result.angels:
        lines.append("No stocks currently meet all fallen angel criteria.")
        return "\n".join(lines)

    lines.append("```")
    lines.append("| Name | Ticker | Drawdown | F-Score | Z-Score | MCap | Weeks |")
    lines.append("|------|--------|----------|---------|---------|------|-------|")
    for a in result.angels:
        z_str = f"{a.z_score:.1f}" if a.z_score is not None else "N/A"
        lines.append(
            f"| {a.name} | {a.ticker} | {_pct(a.drawdown_pct)} | "
            f"{a.f_score}/9 | {z_str} | ${a.market_cap_b:.0f}B | "
            f"{a.weeks_on_list} |"
        )
    lines.append("```")

    lines.append("")
    lines.append(
        "> Fallen angel = quality on sale, not value trap. "
        "Verify recovery catalyst before acting."
    )
    return "\n".join(lines)


def format_daily_signal(result: DailyHighsResult) -> str:
    """Format daily new-highs alert (max 1 name)."""
    radar_note = " (already on Tier 1/2)" if result.on_radar else " (not currently on radar)"
    return (
        f"**Daily Signal** — {result.date}\n\n"
        f"**{result.name}** ({result.ticker}) hit its "
        f"{_ordinal(result.new_high_count_20d)} "
        f"new 52-week high in 20 trading days.\n"
        f"12m return {_pct(result.return_12m)}{radar_note}"
    )


# ─── Helpers ───


def _price_table(entries: list[TierEntry]) -> str:
    """Build a markdown table showing stage and all underlying signals."""
    rows = [
        "| Name | View | 12m Return | Stage | Acceleration | Freshness "
        "| MA Slope | Market State |"
    ]
    rows.append(
        "|------|------|-----------|-------|-------------|----------"
        "|----------|--------------|"
    )
    for e in entries:
        accel = f"{e.acceleration:.1f}x" if e.acceleration is not None else "—"
        freshness = e.freshness or "—"
        slope = f"{e.ma_slope_200d:.3f}" if e.ma_slope_200d is not None else "—"
        view = _consensus_display(e.buy_pct) if e.buy_pct is not None else "—"
        rows.append(
            f"| {e.name} ({e.ticker}) | {view} | {_pct(e.return_12m)} | "
            f"**{e.stage}** | {accel} | {freshness} | {slope} | {e.slow_fast} |"
        )
    return "```\n" + "\n".join(rows) + "\n```"


def _fundamentals_table(entries: list[TierEntry]) -> str:
    """Build markdown table for fundamental signals (Phase 17 enrichment)."""
    has_data = any(
        e.revision_score is not None or e.forward_pe is not None
        for e in entries
    )
    if not has_data:
        return ""

    rows = ["| Name | View | Revisions | Fwd P/E | FCF Yield | Short % | F-Score |"]
    rows.append("|------|------|-----------|---------|-----------|---------|---------|")
    for e in entries:
        rev = _revision_display(e.revision_score) if e.revision_score is not None else "—"
        pe = f"{e.forward_pe:.1f}" if e.forward_pe is not None else "—"
        fcf = f"{e.fcf_yield:.1%}" if e.fcf_yield is not None else "—"
        short = f"{e.short_pct:.1%}" if e.short_pct is not None else "—"
        f_score = f"{e.piotroski_f}/9" if e.piotroski_f is not None else "—"
        consensus = _consensus_display(e.buy_pct) if e.buy_pct is not None else "—"
        rows.append(
            f"| {e.name} ({e.ticker}) | {consensus} | {rev} | {pe} | {fcf} | {short} | {f_score} |"
        )
    return "```\n" + "\n".join(rows) + "\n```"


def _revision_display(score: float) -> str:
    """Convert revision score [-1,1] to human-readable display."""
    if score > 0.5:
        return "Strong Up"
    if score > 0:
        return "Up"
    if score == 0:
        return "Neutral"
    if score > -0.5:
        return "Down"
    return "Strong Down"


def _consensus_display(buy_pct: float) -> str:
    """Convert buy percentage to consensus label."""
    if buy_pct >= 0.8:
        return "Strong Buy"
    if buy_pct >= 0.6:
        return "Buy"
    if buy_pct >= 0.4:
        return "Hold"
    return "Sell"


def _explain_late(e: TierEntry) -> str:
    """Build a human-readable explanation of why a stock is classified LATE."""
    reasons = []
    if e.freshness == "stale":
        reasons.append("strong prior year (stale — running 2+ years)")
    if e.acceleration is not None and e.acceleration < 0.6:
        reasons.append(f"decelerating ({e.acceleration:.1f}x)")
    if e.slow_fast == "correction":
        reasons.append("short-term reversal (correction)")
    if e.ma_slope_200d is not None and e.ma_slope_200d < 0.0:
        reasons.append("200-day MA declining")
    return "; ".join(reasons) if reasons else "multiple signals weakening"


def _pct(value: float) -> str:
    """Format float as percentage string."""
    return f"{value:+.0%}" if abs(value) >= 0.01 else f"{value:+.1%}"


def _change_icon(change: str) -> str:
    """Map change type to text indicator."""
    return {
        "new": "NEW",
        "promoted": "UP",
        "demoted": "DOWN",
        "dropped": "OUT",
        "unchanged": "",
    }.get(change, "")


def _ordinal(n: int) -> str:
    """Convert integer to ordinal string (1st, 2nd, 3rd, etc.)."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
