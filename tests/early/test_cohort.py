"""Unit tests for emergent cohort grouping + cascade labeling."""

from types import SimpleNamespace

from src.cascade.config import CascadeConfig, CascadeDef, TierDef
from src.early.cohort import apply_cohort_bonus, group_into_cohorts


def _cand(ticker: str, industry: str, score: float = 65.0) -> SimpleNamespace:
    return SimpleNamespace(
        ticker=ticker, industry=industry, sector="Tech", cohort=None, early_score=score
    )


def _cfg(tickers: list[str]) -> CascadeConfig:
    return CascadeConfig(
        version=1,
        cascades=[CascadeDef(
            name="AI Infra", demand_driver="AI capex",
            tiers=[TierDef(name="GPU", tickers=tickers)],
        )],
    )


def test_industry_cohort_confirmed_and_singleton_unnamed():
    cands = [_cand("A", "Semis"), _cand("B", "Semis"), _cand("C", "Software")]
    cohorts = group_into_cohorts(cands, _cfg([]))
    semis = next(c for c in cohorts if c.label == "Semis")
    soft = next(c for c in cohorts if c.label == "Software")
    assert semis.confirmed and semis.label_source == "industry" and semis.passing_count == 2
    assert not soft.confirmed and soft.label_source == "unnamed"


def test_cascade_label_applied():
    cands = [_cand("NVDA", "Semis")]
    cohorts = group_into_cohorts(cands, _cfg(["NVDA"]))
    assert cohorts[0].label == "AI Infra"
    assert cohorts[0].label_source == "cascade"
    assert cands[0].cohort == "AI Infra"


def test_confirmed_cohort_bonus_applied():
    cands = [_cand("A", "Semis", 65.0), _cand("B", "Semis", 70.0)]
    cohorts = group_into_cohorts(cands, _cfg([]))
    apply_cohort_bonus(cands, cohorts)
    assert cands[0].early_score == 75.0
    assert cands[1].early_score == 80.0


def test_singleton_gets_no_bonus():
    cands = [_cand("C", "Software", 65.0)]
    cohorts = group_into_cohorts(cands, _cfg([]))
    apply_cohort_bonus(cands, cohorts)
    assert cands[0].early_score == 65.0
