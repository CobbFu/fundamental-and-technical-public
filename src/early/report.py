"""Markdown report for the early scan — cohort-grouped digest.

Labeled cascades first, then unnamed emerging clusters, then singletons. Tables
are wrapped in code blocks for monospace rendering (Feishu/Telegram). Mirrors
src/momentum/report.py table style and src/tracker/cli.py digest-to-disk.
"""

from pathlib import Path

from src.early.scanner import EarlyCandidate, EarlyScanResult

_FEISHU_CHAR_LIMIT = 3500
DEFAULT_DIGESTS_DIR = ".valuation/early-digests"

_LEGEND = (
    "_Anti-momentum: trailing 12m <50%, not on momentum Tier 1/2, $1-20B headroom. "
    "Stage: STAGE1_2_TURN = markup beginning (best); STAGE1_BASE = still basing; "
    "REACCUM_BASE = ran then re-basing (next-leg setup). "
    "Watchlist (seeded) = always shown gate-free with an honest verdict. "
    "Confirmed cohort = 2+ peers basing together. Probe = 1-2% (5% rule)._"
)


def format_early_report(result: EarlyScanResult) -> str:
    """Full cohort-grouped early-scan report."""
    return "\n".join(_blocks(result))


def format_early_report_parts(result: EarlyScanResult) -> list[str]:
    """Split into Feishu-safe (~3500 char) parts at cohort boundaries."""
    header, *cohort_blocks = _blocks(result)
    parts: list[str] = []
    current = header
    for block in cohort_blocks:
        if len(current) + len(block) + 2 > _FEISHU_CHAR_LIMIT and current:
            parts.append(current)
            current = block
        else:
            current = f"{current}\n{block}"
    if current:
        parts.append(current)
    return parts


def write_digest(result: EarlyScanResult, digests_dir: str = DEFAULT_DIGESTS_DIR) -> Path:
    """Write the full report to a dated file, suffixing on collision (YYYY-MM-DD-2.md)."""
    d = Path(digests_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{result.date}.md"
    i = 2
    while path.exists():
        path = d / f"{result.date}-{i}.md"
        i += 1
    path.write_text(format_early_report(result))
    return path


# ─── Internals ───


def _blocks(result: EarlyScanResult) -> list[str]:
    confirmed = sum(1 for c in result.cohorts if c.confirmed)
    header = [
        f"# Early Scan — {result.date}  |  universe {result.universe_size}  |  "
        f"{len(result.candidates)} candidates, {confirmed} confirmed cohorts",
        "",
        _LEGEND,
        "",
    ]
    blocks: list[str] = ["\n".join(header)]

    # Watchlist (seeded) — always shown first, gate-free, with an honest verdict.
    if result.watchlist:
        blocks.append(_watchlist_block(result.watchlist))

    if not result.candidates:
        blocks.append("_No base-stage candidates cleared the gate today._")
        return blocks

    by_ticker = {c.ticker: c for c in result.candidates}
    singletons: list[EarlyCandidate] = []

    for cohort in result.cohorts:
        members = [by_ticker[t] for t in cohort.tickers if t in by_ticker]
        if not members:
            continue
        if cohort.label_source == "unnamed":
            singletons.extend(members)
            continue
        if cohort.label_source == "cascade":
            tag = " (confirmed cohort)" if cohort.confirmed else ""
            head = f"## {cohort.label} — {len(members)} candidate(s){tag}   [cascade]"
        else:  # industry
            head = f"## Emerging: {cohort.label} — {len(members)} cohering   [industry]"
        blocks.append(f"{head}\n\n{_table(members)}\n")

    if singletons:
        blocks.append(f"## Singletons   [unnamed]\n\n{_table(singletons)}\n")

    if result.dropped:
        blocks.append("**Dropped off:** " + ", ".join(result.dropped))
    return blocks


def _watchlist_block(entries: list[EarlyCandidate]) -> str:
    rows = [
        "## Watchlist (seeded) — always shown",
        "",
        "```",
        "| Name (Ticker) | Verdict | Stage | OffHigh | 12m | Price | MCap |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in sorted(entries, key=lambda c: c.early_score, reverse=True):
        rows.append(
            f"| {e.name} ({e.ticker}) | {e.verdict} | {e.stage} | {_dist(e.dist_from_high)} | "
            f"{e.trailing_12m:+.0%} | ${e.price:,.2f} | ${e.market_cap_b:.1f}B |"
        )
    rows.append("```")
    return "\n".join(rows)


def _table(entries: list[EarlyCandidate]) -> str:
    rows = [
        "| Name (Ticker) | Score | Stage | Why now | Price | MCap | 12m | DistBase | Probe |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for e in sorted(entries, key=lambda c: c.early_score, reverse=True):
        rows.append(
            f"| {e.name} ({e.ticker}) | {e.early_score:.0f} | {e.stage} | {e.why_now} | "
            f"${e.price:,.2f} | ${e.market_cap_b:.1f}B | {e.trailing_12m:+.0%} | "
            f"{_dist(e.dist_from_base)} | 1-2% |"
        )
    return "```\n" + "\n".join(rows) + "\n```"


def _dist(dist: float | None) -> str:
    return "—" if dist is None else f"{dist:+.0%}"
