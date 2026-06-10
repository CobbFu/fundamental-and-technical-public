"""Emergent cohort detection + curated-cascade labeling.

Cohorts are an EMERGENT property of the bottom-up hits, not a pre-computed
clustering: when 2+ passing candidates share a cascade or an industry, that is a
cohort. Curated cascades (`.valuation/cascades.yaml`) are only a labeling overlay
— a matched cluster gets named + a confidence bonus; an unmatched cluster is
flagged "emerging" so a theme we never curated still surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.cascade.config import CascadeConfig

if TYPE_CHECKING:
    from src.early.scanner import EarlyCandidate

COHORT_BONUS = 10.0  # score boost for members of a confirmed (2+) cohort


@dataclass
class Cohort:
    label: str
    label_source: str  # "cascade" | "industry" | "unnamed"
    tickers: list[str] = field(default_factory=list)
    member_count: int = 0
    passing_count: int = 0
    confirmed: bool = False  # 2+ passing members -> coordinated move = real signal


def group_into_cohorts(
    candidates: list[EarlyCandidate], cascade_config: CascadeConfig
) -> list[Cohort]:
    """Bucket candidates into emergent cohorts and tag each `candidate.cohort`.

    Matched-to-cascade buckets are labeled with the cascade name; everything else
    is grouped by GICS industry. A bucket with 2+ members is `confirmed`.
    """
    casc_map: dict[str, str] = {}
    for c in cascade_config.cascades:
        for tier in c.tiers:
            for tk in tier.tickers:
                casc_map.setdefault(tk, c.name)

    buckets: dict[tuple[str, str], list[EarlyCandidate]] = {}
    for cand in candidates:
        if cand.ticker in casc_map:
            key = ("cascade", casc_map[cand.ticker])
        else:
            industry = cand.industry or cand.sector or "Unknown"
            key = ("industry", industry)
        buckets.setdefault(key, []).append(cand)

    cohorts: list[Cohort] = []
    for (source, label), members in buckets.items():
        passing = len(members)
        confirmed = passing >= 2
        # A lone industry-grouped name is an unlabeled singleton, not a cohort.
        label_source = "unnamed" if (source == "industry" and passing < 2) else source
        for m in members:
            m.cohort = label
        cohorts.append(
            Cohort(
                label=label,
                label_source=label_source,
                tickers=[m.ticker for m in members],
                member_count=passing,
                passing_count=passing,
                confirmed=confirmed,
            )
        )

    # Order: confirmed cascades, then confirmed industries, then singletons.
    order = {"cascade": 0, "industry": 1, "unnamed": 2}
    cohorts.sort(key=lambda c: (not c.confirmed, order.get(c.label_source, 3), -c.passing_count))
    return cohorts


def apply_cohort_bonus(
    candidates: list[EarlyCandidate], cohorts: list[Cohort], bonus: float = COHORT_BONUS
) -> None:
    """Add a score bonus to members of confirmed cohorts (coordinated = conviction).

    Keyed by ticker membership (not the label string) to avoid any cascade/industry
    label collision granting a bonus to an unrelated name.
    """
    by_ticker = {c.ticker: c for c in candidates}
    for cohort in cohorts:
        if not cohort.confirmed:
            continue
        for tk in cohort.tickers:
            cand = by_ticker.get(tk)
            if cand is not None:
                cand.early_score = min(100.0, cand.early_score + bonus)
