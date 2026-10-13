"""Selected US NSFR factors with calendar maturity and encumbrance treatment."""

from dataclasses import dataclass

import pandas as pd

from .common import AS_OF, ratio, year_end
from .fr2052a import validate_positions
from .lcr import retail_stable


def maturity_term(date: object, as_of: pd.Timestamp = AS_OF) -> str:
    """Classify maturities at calendar six-month and one-year boundaries."""
    if pd.isna(date) or pd.Timestamp(date) < as_of + pd.DateOffset(months=6):
        return "short"
    return "medium" if pd.Timestamp(date) < year_end(as_of) else "long"


def asf_factor(row: pd.Series) -> tuple[float, str]:
    """Assign ASF for supported nonbrokered liabilities and synthetic capital."""
    product = row["product"]
    term = maturity_term(row.maturity_date)
    if product == "derivative":
        return 0.0, "249.107(c)"
    if row.side == "equity" or (term == "long" and product != "deposit"):
        return 1.0, "249.104(a)"
    if product == "deposit" and row.counterparty_type == "retail":
        return (.95 if retail_stable(row) else .90), "249.104(b),(c)"
    if term == "long":
        return 1.0, "249.104(a)"
    if product == "deposit" and row.operational:
        return .50, "249.104(d)(6)"
    if term == "medium" or (product != "debt" and row.counterparty_type in {"corporate", "sovereign"}):
        return .50, "249.104(d)"
    return 0.0, "249.104(e)"


def rsf_factor(row: pd.Series) -> tuple[float, str]:
    """Assign RSF, then apply nonperformance and encumbrance overrides."""
    product, level, term = row["product"], row.collateral_class, maturity_term(row.maturity_date)
    if row.side == "off_balance":
        return .05, "249.106(a)(2)"
    if not row.performing:
        return 1.0, "249.106(b)"
    if product == "cash" or product == "treasury":
        factor = 0.0
    elif product == "agency":
        factor = .15
    elif product == "corporate_bond":
        factor = .50
    elif row.counterparty_type in {"financial", "bank"}:
        if term == "short":
            factor = 0.0 if product == "reverse_repo" and level == "L1" else .15
        else:
            factor = .50 if term == "medium" else 1.0
    elif term != "long":
        factor = .50
    elif product == "mortgage" and row.risk_weight <= .50:
        factor = .65
    else:
        factor = .65 if row.risk_weight <= .20 else .85
    if row.encumbered:
        encumbrance = maturity_term(row.encumbrance_end)
        if encumbrance == "long":
            factor = 1.0
        elif encumbrance == "medium":
            factor = max(.50, factor)
    return factor, "249.106(a),(c)"


@dataclass
class NSFRResult:
    summary: dict[str, float]
    contributions: pd.DataFrame


def calculate_nsfr(positions: pd.DataFrame) -> NSFRResult:
    """Calculate ASF/RSF with a separately traced derivative valuation add-on."""
    if not validate_positions(positions).empty:
        raise ValueError("Invalid positions")
    records = []
    for _, row in positions.iterrows():
        measure = "ASF" if row.side in {"liability", "equity"} else "RSF"
        factor, reference = asf_factor(row) if measure == "ASF" else rsf_factor(row)
        records.append((row.position_id, row["product"], measure, row.balance, factor, row.balance * factor, reference))
        if row["product"] == "derivative" and row.side == "liability":
            records.append((row.position_id, "derivative_valuation", "RSF", row.balance, .05,
                            row.balance * .05, "249.107(b)(5)"))
    detail = pd.DataFrame(records, columns=["position_id", "product", "measure", "balance", "factor", "amount", "reference"])
    asf = float(detail.loc[detail.measure.eq("ASF"), "amount"].sum())
    rsf = float(detail.loc[detail.measure.eq("RSF"), "amount"].sum())
    return NSFRResult(dict(asf=asf, rsf=rsf, nsfr=ratio(asf, rsf)), detail)
