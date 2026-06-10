"""Markdown report formatters for cascade monitor Telegram delivery.

Generates one message per cascade + one cross-cascade summary.
Uses regime shift detection signal columns from session 87/89a design:
- 3m Return, Vol Ratio, vs 52w High, Rel Str, Base, Signal
- Breadth thrust as per-tier header metric

Tables are wrapped in code blocks for monospace rendering on Telegram.
Message limit ~4K chars — split at tier boundaries if needed.
"""

from src.cascade.scanner import CascadeResult, CascadeScanResult, StockSignals, TierResult

_FEISHU_CHAR_LIMIT = 3500


def format_cascade_report(result: CascadeResult) -> str:
    """Format single cascade report for Feishu delivery."""
    lines: list[str] = []

    lines.append(f"# {result.name} Cascade")
    lines.append("")
    lines.append(f"**Demand:** {result.demand_driver}")
    lines.append("")

    for i, tier in enumerate(result.tiers, 1):
        status_label = f" — {tier.status}" if tier.status != "QUIET" else ""
        lines.append(
            f"### Tier {i}: {tier.name}{status_label} "
            f"(Breadth: {tier.breadth}/{tier.breadth_total} above 50d MA)"
        )
        lines.append("")

        if tier.stocks:
            lines.append(_signal_table(tier.stocks))
            lines.append("")
        else:
            lines.append("*No OHLCV data available for tier tickers.*")
            lines.append("")

    # Cross-cascade notes
    if result.cross_cascade_tickers:
        lines.append("### Cross-Cascade")
        for ticker in result.cross_cascade_tickers:
            lines.append(f"- **{ticker}** also tracked in other cascades")
        lines.append("")

    # Status summary
    active_tiers = [t for t in result.tiers if t.status == "ACTIVE"]
    next_tiers = [t for t in result.tiers if t.status == "NEXT"]
    if active_tiers and next_tiers:
        lines.append(
            f"**Status:** {active_tiers[0].name} active → "
            f"watching {next_tiers[0].name}."
        )
    elif active_tiers:
        lines.append(f"**Status:** {active_tiers[0].name} active.")
    else:
        lines.append("**Status:** No tiers currently active.")
    lines.append("")

    return "\n".join(lines)


def format_cascade_report_parts(result: CascadeResult) -> list[str]:
    """Split cascade report into Feishu-safe parts (~3500 chars).

    Splits at tier boundaries to avoid mid-table breaks.
    """
    full = format_cascade_report(result)

    if len(full) <= _FEISHU_CHAR_LIMIT:
        return [full]

    # Split: header + first few tiers, then remaining tiers
    parts: list[str] = []
    current: list[str] = []

    # Header
    header_lines = [
        f"# {result.name} Cascade",
        "",
        f"**Demand:** {result.demand_driver}",
        "",
    ]
    current.extend(header_lines)

    for i, tier in enumerate(result.tiers, 1):
        tier_block = _format_tier_block(tier, tier_number=i)
        candidate = "\n".join(current) + "\n" + tier_block

        # Never flush header without at least one tier
        if len(candidate) > _FEISHU_CHAR_LIMIT and current != header_lines:
            parts.append("\n".join(current))
            current = [tier_block]
        else:
            current.append(tier_block)

    # Flush remaining
    if current:
        parts.append("\n".join(current))

    return parts if parts else [full]


def format_cross_cascade_summary(scan_result: CascadeScanResult) -> str:
    """Format cross-cascade summary showing multi-cascade stocks."""
    lines: list[str] = []

    lines.append("# Cross-Cascade Summary")
    lines.append("")

    if not scan_result.cross_cascade:
        lines.append("No stocks appear in multiple cascades.")
        return "\n".join(lines)

    lines.append("Stocks tracked across multiple supply chain cascades "
                  "carry higher conviction — multiple demand drivers.")
    lines.append("")
    lines.append("```")
    lines.append("| Stock | Cascades | Count |")
    lines.append("|-------|----------|-------|")

    for ticker, cascades in sorted(
        scan_result.cross_cascade.items(),
        key=lambda x: len(x[1]),
        reverse=True,
    ):
        cascades_str = ", ".join(cascades)
        lines.append(f"| {ticker} | {cascades_str} | {len(cascades)} |")
    lines.append("```")

    lines.append("")

    # Overall status summary
    lines.append("### Cascade Status Overview")
    lines.append("")
    for cascade in scan_result.cascades:
        active = [t for t in cascade.tiers if t.status == "ACTIVE"]
        next_t = [t for t in cascade.tiers if t.status == "NEXT"]
        if active:
            status = f"{active[0].name} active"
            if next_t:
                status += f" → {next_t[0].name} next"
        else:
            status = "Quiet"
        lines.append(f"- **{cascade.name}:** {status}")

    lines.append("")
    return "\n".join(lines)


def format_all_cascade_parts(scan_result: CascadeScanResult) -> list[str]:
    """Format all cascades + cross-cascade as list of Feishu messages.

    Returns one message per cascade + 1 cross-cascade summary.
    Each message under 3500 chars.
    """
    parts: list[str] = []

    for cascade in scan_result.cascades:
        cascade_parts = format_cascade_report_parts(cascade)
        parts.extend(cascade_parts)

    # Cross-cascade summary
    summary = format_cross_cascade_summary(scan_result)
    parts.append(summary)

    return parts


# ─── Helpers ───


def _signal_table(stocks: list[StockSignals]) -> str:
    """Build markdown table with regime shift detection signal columns."""
    rows = [
        "| Stock | Signal | Base | 3m Ret | Vol Ratio | vs 52w High | Rel Str |"
    ]
    rows.append(
        "|-------|--------|------|--------|-----------|-------------|---------|"
    )
    for s in stocks:
        ret = f"{s.return_3m:+.0%}" if s.return_3m is not None else "—"
        vol = f"{s.volume_ratio:.1f}x" if s.volume_ratio is not None else "—"
        dist = _format_dist(s.dist_52w_high) if s.dist_52w_high is not None else "—"
        rel = f"{s.rel_strength:.1f}" if s.rel_strength is not None else "—"
        base = s.base_status.replace("_", " ").title() if s.base_status else "—"
        rows.append(
            f"| {s.name} ({s.ticker}) | {s.signal} | {base} | {ret} | {vol} | {dist} | {rel} |"
        )
    return "```\n" + "\n".join(rows) + "\n```"


def _format_dist(dist: float) -> str:
    """Format distance from 52w high."""
    if dist < 0.01:
        return "At high"
    return f"-{dist:.0%}"


def _format_tier_block(tier: TierResult, tier_number: int = 0) -> str:
    """Format a single tier as a string block."""
    lines: list[str] = []
    status_label = f" — {tier.status}" if tier.status != "QUIET" else ""
    num_prefix = f"{tier_number}: " if tier_number else ""
    lines.append(
        f"### Tier {num_prefix}{tier.name}{status_label} "
        f"(Breadth: {tier.breadth}/{tier.breadth_total} above 50d MA)"
    )
    lines.append("")
    if tier.stocks:
        lines.append(_signal_table(tier.stocks))
    else:
        lines.append("*No OHLCV data available for tier tickers.*")
    lines.append("")
    return "\n".join(lines)
