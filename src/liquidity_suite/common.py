"""Shared validation and calendar conventions."""

import math
from typing import Iterable

import pandas as pd

AS_OF = pd.Timestamp("2026-09-30")
SEED = 2052
COUNTERPARTIES = {"retail", "corporate", "financial", "sovereign", "central_bank", "bank"}
PRODUCTS = {"cash", "treasury", "agency", "corporate_bond", "mortgage", "loan",
            "reverse_repo", "deposit", "debt", "repo", "other", "equity",
            "credit_facility", "liquidity_facility", "derivative"}
COLLATERAL = {"L1", "L2A", "L2B", "mortgage", "loan", "none"}
SIDES = {"asset", "liability", "equity", "off_balance"}
REQUIRED = ["position_id", "side", "product", "counterparty_type", "counterparty_id",
            "balance", "maturity_date", "currency", "collateral_class", "encumbered",
            "encumbrance_end", "insured", "operational", "relationship", "performing",
            "risk_weight", "collateral_asset_id"]


def nonnegative(values: Iterable[float]) -> None:
    """Reject negative and nonfinite monetary inputs."""
    if any(not math.isfinite(float(v)) or float(v) < 0 for v in values):
        raise ValueError("Amounts must be finite and nonnegative")


def ratio(numerator: float, denominator: float) -> float:
    """Return infinity for positive resources with no requirement, NaN for empty ratios."""
    return numerator / denominator if denominator else (math.inf if numerator else math.nan)


def days_to(date: object, as_of: pd.Timestamp = AS_OF) -> int:
    """Use calendar days and treat demand balances as immediately payable."""
    return 0 if pd.isna(date) else (pd.Timestamp(date) - as_of).days


def year_end(as_of: pd.Timestamp = AS_OF) -> pd.Timestamp:
    """Use calendar anniversaries rather than fixed day counts for NSFR."""
    return as_of + pd.DateOffset(years=1)


def markdown_table(frame: pd.DataFrame) -> str:
    """Render a dependency-free Markdown table."""
    def cell(value: object) -> str:
        if isinstance(value, float):
            return f"{value:,.6f}"
        return str(value).replace("|", "/").replace("\n", " ")
    headers = list(frame.columns)
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(":-:" for _ in headers) + " |"]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in frame.itertuples(index=False, name=None)]
    return "\n".join(lines) + "\n"
