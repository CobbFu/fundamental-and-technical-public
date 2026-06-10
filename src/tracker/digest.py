"""Render the morning digest from a freshly-refreshed Tracker.

Three tiers, sorted by urgency:
- 🔴 Action: verdict_changed=True OR critical flag fired OR alert price crossed
- 🟡 Glance: |price change since previous read| > 5% OR within ±3% of an alert
- ⚪ Quiet: everything else (one-liner per ticker)

Final sections: alerts-gap report, position summary (joined from portfolio.yaml).
"""

from __future__ import annotations

from src.street import render_street_markdown
from src.tracker.models import Alert, Tracker, TrackerEntry
from src.tracker.portfolio_join import HoldingSnapshot

CRITICAL_FLAGS = {
    "parabolic_trifecta_1D",
    "parabolic_trifecta_1W",
    "weekly_rsi_extreme",
    "ema_stack_break_1D",
    "ema_stack_break_1W",
    # Trend-regime critical flags.
    "climax_top_1D",
    "climax_top_1W",
    "three_up_days_1D",
}

VERDICT_EMOJI = {
    "buy": "🛒",
    "vcp_buy": "🟢",
    "stage2_add": "🟢",
    "ep_probe": "🎯",
    "watch": "👀",
    "hold": "✋",
    "hold_tighten": "🤏",
    "trim": "✂️",
    "exit": "🚪",
    "dont_chase": "⛔",
}

# Plain-English verdict labels shown after the ticker in each card header.
# Internal verdict codes stay unchanged; only the surface phrasing softens.
VERDICT_LABEL = {
    "buy": "Buy",
    "vcp_buy": "Buy (VCP breakout)",
    "stage2_add": "Add (Stage 2 continuation)",
    "ep_probe": "Probe (episodic pivot)",
    "watch": "Watch",
    "hold": "Hold",
    "hold_tighten": "Hold, but tighten the grip",
    "trim": "Trim",
    "exit": "Exit",
    "dont_chase": "Don't chase",
}

REGIME_BANNER = {
    "stage2": "🟢 Stage 2 — trend-following",
    "mean_reversion": "🔵 Mean-reversion",
}

LEGEND = """\
## 📖 Legend

**Verdicts — what each one tells you to do:**

| | Code | In plain English |
|---|---|---|
| 🛒 | `buy` | Place an order at the named level today |
| 🟢 | `stage2_add` / `vcp_buy` | Trend-confirmed entry — full or progressive position |
| 🎯 | `ep_probe` | Catalyst-day probe — 1-2% of book, scale on confirmation |
| 👀 | `watch` | No action yet — monitor the named trigger |
| ✋ | `hold` | Don't touch it — no trim, no add |
| 🤏 | `hold_tighten` | Trend intact but stretched — lock partial gains, don't full-exit |
| ✂️ | `trim` | Sell some on the next pop |
| 🚪 | `exit` | Sell on the next strength (or immediately on rising-vol break) |
| ⛔ | `dont_chase` | Sit on your hands |

**Regime — which framework produced the verdict:**

- 🟢 **Stage 2 (trend-following)** — Price > 20-EMA > 50-EMA > 200-EMA, all rising. High-RSI is regime confirmation, not a sell. 12% becomes a "review", not a "trim".
- 🔵 **Mean-reversion** — Broken trend, choppy, bear, or post-spinoff. Classic 3 archetypes. RSI > 70 = don't-chase. 5/12/15 sizing is hard.

**Risk badge:**

- 🔴 **Action** — verdict changed, alert within 5%, climax veto, or 12/15% breach
- 🟡 **Heads-up** — cooling/expansion; monitor, no trade required
- ⚪ **Quiet** — in range, look again next week
"""


def _layer_letter(cascade: str) -> str:
    """Extract layer letter (A-Z) from a 'X — Description' cascade string."""
    if " — " in cascade:
        prefix = cascade.split(" — ", 1)[0].strip()
        if len(prefix) == 1 and prefix.isalpha():
            return prefix.upper()
    return "Z"  # unrecognised layers sort to the end


def _display_verdict(entry: TrackerEntry) -> str:
    """Translate verdict for display based on state.

    - 'exit' on a non-held entry → 'dont_chase' (nothing to exit).
    - 'trim' / 'hold_tighten' / 'hold' on a non-held entry in Stage 2 → 'watch'
      (these are held-position-language; watching wants 'no entry signal').

    Keeps verdict.py pure while letting the surface honour state + regime.
    """
    lr = entry.last_refresh
    if lr is None:
        return ""
    if lr.verdict == "exit" and entry.state != "held":
        return "dont_chase"
    # In Stage 2, hold-class verdicts on a non-held entry collapse to 'watch'.
    # They mean "framework engaged, no entry signal right now" — which is just
    # 'watch' from a watcher's perspective.
    if (
        entry.state != "held"
        and lr.regime == "stage2"
        and lr.verdict in ("hold", "hold_tighten", "trim")
    ):
        return "watch"
    return lr.verdict


def render_digest(
    tracker: Tracker,
    holdings: dict[str, HoldingSnapshot],
    refresh_ts: str,
    *,
    scope_tickers: list[str] | None = None,
) -> str:
    """Return the digest markdown.

    `scope_tickers` limits which entries are rendered (used by single-ticker refresh).
    Holdings is a join from portfolio.yaml; tickers not in holdings are watching/exited.
    """
    if scope_tickers is not None:
        entries = [e for e in tracker.entries if e.ticker in scope_tickers]
    else:
        entries = list(tracker.entries)

    action: list[TrackerEntry] = []
    glance: list[TrackerEntry] = []
    quiet: list[TrackerEntry] = []

    for entry in entries:
        if entry.last_refresh is None:
            quiet.append(entry)
            continue
        tier = _classify(entry)
        if tier == "action":
            action.append(entry)
        elif tier == "glance":
            glance.append(entry)
        else:
            quiet.append(entry)

    # Sort within action by severity (verdict change > critical flag > alert cross).
    action.sort(key=_action_severity, reverse=True)

    parts: list[str] = []
    parts.append(f"# Tracker digest — {refresh_ts}\n")
    parts.append(
        f"_Scope: {len(entries)} entries "
        f"({len(action)} 🔴 / {len(glance)} 🟡 / {len(quiet)} ⚪)_\n"
    )
    parts.append("\n" + LEGEND)

    errors = [e for e in entries if e.last_refresh and e.last_refresh.error]
    if errors:
        parts.append("\n## ⚠️ Errors")
        for e in errors:
            assert e.last_refresh is not None
            parts.append(f"- **{e.ticker}**: {e.last_refresh.error}")
        parts.append("")

    action_set = {e.ticker for e in action}
    glance_set = {e.ticker for e in glance}

    if action:
        parts.append("\n## 🔴 Action required\n")
        for e in action:
            parts.append(_render_full(e, holdings.get(e.ticker)))

    # Full book by layer — every entry shown under its cascade label, with a
    # tier marker (🔴/🟡/⚪) so urgency is visible inline.
    parts.append(_render_book_by_layer(entries, holdings, action_set, glance_set))

    # Alerts gap covers glance/quiet only — action tickers already have their
    # alerts inline in the per-card table.
    parts.append(_render_alerts_gap(entries, exclude=action_set))
    parts.append(_render_position_summary(entries, holdings))

    return "\n".join(parts)


def _render_book_by_layer(
    entries: list[TrackerEntry],
    holdings: dict[str, HoldingSnapshot],
    action_set: set[str],
    glance_set: set[str],
) -> str:
    """Render every entry grouped by cascade label, sorted by layer letter."""
    from collections import defaultdict

    groups: dict[str, list[TrackerEntry]] = defaultdict(list)
    for e in entries:
        groups[e.thesis.cascade].append(e)

    def _sort_key(label: str) -> tuple[str, str]:
        return (_layer_letter(label), label)

    sorted_labels = sorted(groups.keys(), key=_sort_key)

    lines = ["\n## 📚 Full book by layer\n"]
    for label in sorted_labels:
        bucket = sorted(groups[label], key=lambda e: e.ticker)
        lines.append(f"### {label}\n")
        for e in bucket:
            if e.ticker in action_set:
                tier = "🔴"
            elif e.ticker in glance_set:
                tier = "🟡"
            else:
                tier = "⚪"
            line = _render_one_liner(e, holdings.get(e.ticker))
            # _render_one_liner returns "- <emoji> **TICKER> ...". Insert tier
            # marker right after the leading "- ".
            if line.startswith("- "):
                line = f"- {tier} {line[2:]}"
            lines.append(line)
        lines.append("")
    return "\n".join(lines)


def _classify(entry: TrackerEntry) -> str:
    lr = entry.last_refresh
    assert lr is not None
    if lr.verdict_changed:
        return "action"
    if any(f in CRITICAL_FLAGS for f in lr.flags):
        return "action"
    if any(f.startswith("alert_crossed:") for f in lr.flags):
        return "action"
    # Street-target verdict change — catches the rerating-wave start.
    if (
        isinstance(entry.street_target, dict)
        and entry.street_target.get("verdict_changed")
    ):
        return "action"
    # Glance: within ±3% of any alert price (using daily price if present).
    price = lr.daily.price if lr.daily else (lr.weekly.price if lr.weekly else None)
    if price is not None:
        for alert in entry.alerts:
            if alert.price > 0 and abs(price - alert.price) / alert.price <= 0.03:
                return "glance"
    return "quiet"


def _action_severity(entry: TrackerEntry) -> int:
    lr = entry.last_refresh
    assert lr is not None
    score = 0
    if lr.verdict_changed:
        score += 100
    score += sum(10 for f in lr.flags if f in CRITICAL_FLAGS)
    score += sum(5 for f in lr.flags if f.startswith("alert_crossed:"))
    return score


def _render_full(entry: TrackerEntry, holding: HoldingSnapshot | None) -> str:
    """Render an action-tier card with the verbose-but-scannable v2 layout.

    Structure:
      1. Header — `### {emoji} TICKER — Plain-English label  ({state})`
      2. One-line context (held P/L or watching) + regime + verdict-change
      3. **Chart:** daily / weekly / flags as compact bullets
      4. **Do:** the entry_trigger paragraph from tracker.yaml
      5. **Key levels:** stop / add / trim as emoji-tagged bullets
      6. **Alerts to set in TradingView:** inline table with Δ-from-price
    """
    lr = entry.last_refresh
    assert lr is not None
    verdict = _display_verdict(entry)
    emoji = VERDICT_EMOJI.get(verdict, "")
    label = VERDICT_LABEL.get(verdict, verdict)
    state_tag = _state_tag(entry, holding)

    # 1. Header
    lines = [f"### {emoji} **{entry.ticker}** — {label}  {state_tag}", ""]

    # 2. One-line context (held detail + regime + verdict-change)
    context_bits: list[str] = []
    price = _current_price(lr)
    if entry.state == "held" and holding is not None:
        avg = holding.avg_cost_local
        avg_str = f"${avg:.2f}" if avg is not None else "—"
        last_str = f"${price:.2f}" if price is not None else "—"
        if price is not None and avg is not None and avg > 0:
            pl = (price - avg) / avg * 100
            context_bits.append(
                f"**Held:** {int(holding.total_shares)} sh @ {avg_str} · "
                f"cost £{int(holding.total_cost_gbp)} · last {last_str} · **{pl:+.1f}%**"
            )
        else:
            context_bits.append(
                f"**Held:** {int(holding.total_shares)} sh @ {avg_str} · "
                f"cost £{int(holding.total_cost_gbp)} · last {last_str}"
            )
    if lr.regime is not None and lr.regime in REGIME_BANNER:
        context_bits.append(REGIME_BANNER[lr.regime])
    if lr.previous_verdict is not None and lr.verdict_changed:
        prev_label = VERDICT_LABEL.get(lr.previous_verdict, lr.previous_verdict)
        context_bits.append(f"_Changed: {prev_label} → **{label}**_")
    for bit in context_bits:
        lines.append(bit)
    lines.append("")

    # 3. Chart
    chart_bullets: list[str] = []
    if lr.daily:
        chart_bullets.append(f"- **Daily:** {_read_oneline(lr.daily)}")
    if lr.weekly:
        chart_bullets.append(f"- **Weekly:** {_read_oneline(lr.weekly)}")
    if lr.flags:
        chart_bullets.append(
            f"- **Flags:** {', '.join('`' + f + '`' for f in lr.flags)}"
        )
    if chart_bullets:
        lines.append("**Chart:**")
        lines.extend(chart_bullets)
        lines.append("")

    # 4. Do — the entry_trigger text from tracker.yaml is already action-oriented
    if entry.plan.entry_trigger:
        lines.append("**Do:**")
        lines.append("")
        lines.append(entry.plan.entry_trigger.strip())
        lines.append("")

    # 5. Key levels — compact bullets with action-typed emoji
    level_bits: list[str] = []
    if entry.plan.stop_loss is not None:
        level_bits.append(f"- 🛑 **Stop:** ${entry.plan.stop_loss}")
    if entry.plan.add_zones:
        zones = ", ".join(f"${z}" for z in entry.plan.add_zones)
        level_bits.append(f"- ➕ **Add zones:** {zones}")
    if entry.plan.trim_zones:
        zones = ", ".join(f"${z}" for z in entry.plan.trim_zones)
        level_bits.append(f"- ✂️ **Trim zones:** {zones}")
    if level_bits:
        lines.append("**Key levels:**")
        lines.extend(level_bits)
        lines.append("")

    # 6. Alerts to set in TradingView — distance from current price
    open_alerts = [a for a in entry.alerts if not a.set_in_tv]
    if open_alerts:
        lines.append("**Alerts to set in TradingView:**")
        lines.append("")
        lines.append("| Price | Type | Δ from now | Note |")
        lines.append("|---|---|---|---|")
        for a in open_alerts:
            if price is not None and a.price > 0:
                delta = (a.price - price) / price * 100
                delta_str = f"{delta:+.1f}%"
            else:
                delta_str = "—"
            note = a.note.strip() if a.note else ""
            lines.append(f"| ${a.price} | {a.type} | {delta_str} | {note} |")
        lines.append("")

    if lr.notes:
        lines.append(lr.notes.strip())
        lines.append("")

    # Street-target block — included on every action-tier card so the
    # rerating-wave evidence sits next to the TA verdict.
    if isinstance(entry.street_target, dict):
        street_md = render_street_markdown(entry.street_target)
        if street_md:
            lines.append(street_md)

    return "\n".join(lines)


def _current_price(lr) -> float | None:
    if lr.daily and lr.daily.price:
        return lr.daily.price
    if lr.weekly and lr.weekly.price:
        return lr.weekly.price
    return None


def _render_one_liner(entry: TrackerEntry, holding: HoldingSnapshot | None) -> str:
    lr = entry.last_refresh
    state_tag = _state_tag(entry, holding)
    if lr is None:
        return f"- **{entry.ticker}** {state_tag} — _no read yet_"
    verdict = _display_verdict(entry)
    emoji = VERDICT_EMOJI.get(verdict, "")
    price = None
    if lr.daily:
        price = lr.daily.price
    elif lr.weekly:
        price = lr.weekly.price
    price_str = f"${price:.2f}" if price is not None else "—"
    return f"- {emoji} **{entry.ticker}** {state_tag} {price_str} — `{verdict}`"


def _read_oneline(read: object) -> str:
    # Imported lazily to avoid circular type concerns; we know the shape.
    from src.tracker.models import TimeframeRead

    assert isinstance(read, TimeframeRead)
    ema20 = read.ema.get(20)
    ema50 = read.ema.get(50)
    ema200 = read.ema.get(200)
    ema_parts = []
    if ema20 is not None:
        ema_parts.append(f"20={ema20:.2f}")
    if ema50 is not None:
        ema_parts.append(f"50={ema50:.2f}")
    if ema200 is not None:
        ema_parts.append(f"200={ema200:.2f}")
    ema_str = " ".join(ema_parts)
    return (
        f"price ${read.price:.2f}, RSI {read.rsi:.1f}, "
        f"MACD hist {read.macd.get('hist', 0):+.2f}, BB upper ${read.bb.get('upper', 0):.2f} "
        f"({ema_str})"
    )


def _state_tag(entry: TrackerEntry, holding: HoldingSnapshot | None) -> str:
    if entry.state == "held" and holding is not None:
        avg = holding.avg_cost_local
        avg_str = f" @ ${avg:.2f}" if avg is not None else ""
        return f"_(held: {int(holding.total_shares)} sh{avg_str})_"
    if entry.state == "held":
        return "_(held — not in portfolio.yaml)_"
    if entry.state == "watching":
        return "_(watching)_"
    return f"_({entry.state})_"


def _render_alerts_gap(
    entries: list[TrackerEntry], *, exclude: set[str] | None = None
) -> str:
    """Render alerts NOT yet set in TV. Action-tier tickers are excluded since
    their alerts already appear inline in the per-card table."""
    exclude = exclude or set()
    rows: list[tuple[str, Alert]] = []
    for e in entries:
        if e.ticker in exclude:
            continue
        for a in e.alerts:
            if not a.set_in_tv:
                rows.append((e.ticker, a))
    if not rows:
        return "\n## Alerts gap\n\n_All quiet/heads-up alerts marked as set in TV._\n"
    lines = [
        "\n## Alerts gap (quiet & heads-up tier)\n",
        "_Action-tier alerts are inline above. These are the remaining standing-alert gaps._",
        "",
    ]
    for ticker, a in rows:
        note = f" — {a.note}" if a.note else ""
        lines.append(f"- **{ticker}**: ${a.price} ({a.type}){note}")
    lines.append("")
    return "\n".join(lines)


def _render_position_summary(
    entries: list[TrackerEntry], holdings: dict[str, HoldingSnapshot]
) -> str:
    held = [e for e in entries if e.state == "held" and e.ticker in holdings]
    if not held:
        return "\n## Position summary\n\n_No held entries in scope._\n"
    lines = [
        "\n## Position summary\n",
        "| Ticker | Shares | Avg cost (local) | Cost (£) | Last price | P/L (local) |",
        "|--------|--------|------------------|----------|------------|-------------|",
    ]
    for e in held:
        h = holdings[e.ticker]
        lr = e.last_refresh
        last_price = None
        if lr and lr.daily:
            last_price = lr.daily.price
        elif lr and lr.weekly:
            last_price = lr.weekly.price
        avg = h.avg_cost_local
        if last_price is not None and avg is not None and avg > 0:
            pl_pct = (last_price - avg) / avg * 100
            pl_str = f"{pl_pct:+.1f}%"
        else:
            pl_str = "—"
        avg_str = f"${avg:.2f}" if avg is not None else "—"
        last_str = f"${last_price:.2f}" if last_price is not None else "—"
        lines.append(
            f"| {e.ticker} | {int(h.total_shares)} | {avg_str} "
            f"| £{int(h.total_cost_gbp)} | {last_str} | {pl_str} |"
        )
    lines.append("")
    return "\n".join(lines)
