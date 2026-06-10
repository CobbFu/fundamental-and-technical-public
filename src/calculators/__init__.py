"""Company-specific valuation calculators (Damodaran methodology).

Each calculator replicates the logic of a Damodaran support spreadsheet,
taking company/industry/macro data and producing a calculated value
with a full DerivationTrace for auditability.
"""

from src.calculators.beta import BetaCalculator
from src.calculators.black_scholes import BlackScholesCalculator
from src.calculators.lease_converter import LeaseConverter
from src.calculators.rd_capitalizer import RDCapitalizer
from src.calculators.synthetic_rating import SyntheticRating
from src.calculators.terminal_sanity import TerminalSanityCheck
from src.calculators.wacc import WACCBuilder

__all__ = [
    "BetaCalculator",
    "BlackScholesCalculator",
    "LeaseConverter",
    "RDCapitalizer",
    "SyntheticRating",
    "TerminalSanityCheck",
    "WACCBuilder",
]
