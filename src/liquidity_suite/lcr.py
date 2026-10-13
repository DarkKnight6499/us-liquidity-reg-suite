"""Selected US LCR rules with exact CFR cap coefficients and flow lineage."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .common import AS_OF, days_to, nonnegative, ratio
from .fr2052a import validate_positions

HAIRCUT_VALUE = {"L1": 1.0, "L2A": .85, "L2B": .5}
SECURED_RATE = {"L1": 0.0, "L2A": .15, "L2B": .5, "mortgage": 1.0, "loan": 1.0, "none": 1.0}


@dataclass(frozen=True)
class HQLAResult:
    level1: float
    level2a: float
    level2b: float
    unadjusted_excess: float
    adjusted_excess: float
    amount: float


def cap_excess(level1: float, level2a: float, level2b: float) -> float:
    """Apply section 249.21(d),(e) using the prescribed rounded coefficients."""
    nonnegative((level1, level2a, level2b))
    level2_excess = max(level2a + level2b - .6667 * level1, 0.0)
    level2b_excess = max(level2b - level2_excess - .1765 * (level1 + level2a), 0.0)
    return level2_excess + level2b_excess


def hqla(level1: float, level2a_fair_value: float, level2b_fair_value: float,
         adjusted_fair_values: tuple[float, float, float] | None = None) -> HQLAResult:
    """Deduct the larger current or post-unwind cap excess from current holdings."""
    nonnegative((level1, level2a_fair_value, level2b_fair_value))
    current = (level1, .85 * level2a_fair_value, .5 * level2b_fair_value)
    adjusted = current if adjusted_fair_values is None else (
        adjusted_fair_values[0], .85 * adjusted_fair_values[1], .5 * adjusted_fair_values[2])
    excess, adjusted_excess = cap_excess(*current), cap_excess(*adjusted)
    amount = sum(current) - max(excess, adjusted_excess)
    if amount < -1e-9:
        raise ValueError("Unwind creates cap deductions above current holdings")
    return HQLAResult(*current, excess, adjusted_excess, max(0.0, amount))


def retail_stable(row: pd.Series) -> bool:
    """Synthetic stable deposits require full insurance and an established relationship."""
    return bool(row.insured and row.relationship and row.counterparty_type == "retail")


def outflow_rate(row: pd.Series) -> tuple[float, str]:
    """Return the supported product's runoff rate and CFR reference."""
    product, cp = row["product"], row.counterparty_type
    if product == "deposit":
        if cp == "retail":
            return (.03 if retail_stable(row) else .10), "249.32(a)(1),(2)"
        if row.operational:
            return (.05 if row.insured else .25), "249.32(h)(3),(4)"
        if cp in {"corporate", "sovereign"}:
            return (.20 if row.insured else .40), "249.32(h)(1)"
        return 1.0, "249.32(h)(2)"
    if product == "repo":
        if cp == "sovereign" and row.collateral_class not in {"L1", "L2A"}:
            return .25, "249.32(j)(1)(iii)"
        return SECURED_RATE[row.collateral_class], "249.32(j)(1)"
    if product in {"credit_facility", "liquidity_facility"}:
        if cp == "retail":
            value = .05
        elif cp == "bank":
            value = .50
        elif cp == "financial":
            value = .40 if product == "credit_facility" else 1.0
        else:
            value = .10 if product == "credit_facility" else .30
        return value, "249.32(e)(1)"
    return 1.0, "249.32(c)" if product == "derivative" else "249.32(h)(2),(l)"


def inflow_rate(row: pd.Series) -> tuple[float, str]:
    """Exclude nonperforming assets and liquid securities counted in HQLA."""
    if not row.performing or row["product"] == "cash":
        return 0.0, "249.33(a)"
    if row["product"] in {"treasury", "agency", "corporate_bond"}:
        return (0.0 if not row.encumbered else 1.0), "249.33(a)(4),(e)"
    if row["product"] == "reverse_repo":
        return SECURED_RATE[row.collateral_class], "249.33(f)(1)"
    return (1.0 if row.counterparty_type in {"financial", "bank", "central_bank"} else .5), "249.33(c),(d)"


def net_outflows(outflows: float, inflows: float, mismatch: float = 0.0) -> tuple[float, float]:
    """Apply the inflow cap and a nonnegative maturity mismatch add-on."""
    nonnegative((outflows, inflows, mismatch))
    allowed = min(inflows, .75 * outflows)
    return outflows - allowed + mismatch, allowed


@dataclass
class LCRResult:
    summary: dict[str, float]
    contributions: pd.DataFrame
    unwind: pd.DataFrame
    daily_mismatch: pd.DataFrame


def calculate_lcr(positions: pd.DataFrame) -> LCRResult:
    """Calculate a full calibration LCR for the deliberately limited synthetic universe."""
    if not validate_positions(positions).empty:
        raise ValueError("Invalid positions")
    securities = positions.loc[positions.side.eq("asset") & positions["product"].isin(
        ["cash", "treasury", "agency", "corporate_bond"]) & ~positions.encumbered]
    current = {level: float(securities.loc[securities.collateral_class.eq(level), "balance"].sum())
               for level in HAIRCUT_VALUE}
    adjusted = current.copy()
    unwind = []
    by_id = positions.set_index("position_id")
    for row in positions.loc[positions["product"].eq("repo")].itertuples():
        if days_to(row.maturity_date) <= 30 and row.collateral_class in HAIRCUT_VALUE:
            asset = by_id.loc[row.collateral_asset_id]
            adjusted["L1"] -= row.balance
            adjusted[row.collateral_class] += asset.balance
            unwind.append((row.position_id, asset.name, row.collateral_class, row.balance, asset.balance))
    liquid = hqla(current["L1"], current["L2A"], current["L2B"],
                  (adjusted["L1"], adjusted["L2A"], adjusted["L2B"]))
    contributions = []
    for _, row in positions.iterrows():
        day = days_to(row.maturity_date)
        product = row["product"]
        if row.side == "asset":
            rate, reference = inflow_rate(row)
            rate = rate if 0 <= day <= 30 and not pd.isna(row.maturity_date) else 0.0
            direction = "inflow"
            mismatch_eligible = rate > 0
        elif row.side in {"liability", "off_balance"}:
            rate, reference = outflow_rate(row)
            regardless_maturity = product in {"credit_facility", "liquidity_facility"} or (
                product == "deposit" and row.counterparty_type == "retail")
            rate = rate if regardless_maturity or 0 <= day <= 30 else 0.0
            direction = "outflow"
            mismatch_eligible = product in {"repo", "debt", "other"} or (
                product == "deposit" and not row.operational and row.counterparty_type != "retail" and
                (not pd.isna(row.maturity_date) or row.counterparty_type in {"financial", "bank"}))
        else:
            continue
        contributions.append((row.position_id, product, direction, row.balance, rate, row.balance * rate,
                              max(day, 1), mismatch_eligible, reference))
    detail = pd.DataFrame(contributions, columns=["position_id", "product", "direction", "balance", "rate",
                                                 "amount", "day", "mismatch_eligible", "reference"])
    out = float(detail.loc[detail.direction.eq("outflow"), "amount"].sum())
    incoming = float(detail.loc[detail.direction.eq("inflow"), "amount"].sum())
    daily = []
    for day in range(1, 31):
        selected = detail.loc[detail.mismatch_eligible & detail.day.le(day)]
        cumulative = float((selected.amount * np.where(selected.direction.eq("outflow"), 1, -1)).sum())
        daily.append((day, cumulative))
    curve = pd.DataFrame(daily, columns=["day", "net_cumulative_maturity_outflow"])
    mismatch = max(0.0, float(curve.net_cumulative_maturity_outflow.max())) - max(0.0, daily[-1][1])
    net, allowed = net_outflows(out, incoming, mismatch)
    summary = dict(hqla=liquid.amount, level1=liquid.level1, level2a=liquid.level2a, level2b=liquid.level2b,
                   unadjusted_excess=liquid.unadjusted_excess, adjusted_excess=liquid.adjusted_excess,
                   outflows=out, inflows=incoming, allowed_inflows=allowed, mismatch_addon=mismatch,
                   net_outflows=net, lcr=ratio(liquid.amount, net))
    return LCRResult(summary, detail, pd.DataFrame(unwind, columns=["repo_id", "asset_id", "level", "cash_paid",
                                                                 "collateral_returned"]), curve)
