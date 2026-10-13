"""Internal stress assumptions, daily survival paths, and contingent risk inventory."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .collateral import inventory, waterfall
from .common import days_to, nonnegative
from .fr2052a import validate_positions
from .lcr import HAIRCUT_VALUE, retail_stable


@dataclass(frozen=True)
class Scenario:
    name: str
    severity: float
    wholesale_rollover: float
    haircut_shock: float
    drawdown: float
    collection_rate: float

    def __post_init__(self) -> None:
        nonnegative((self.severity, self.wholesale_rollover, self.haircut_shock, self.drawdown, self.collection_rate))
        if any(value > 1 for value in (self.wholesale_rollover, self.haircut_shock, self.drawdown, self.collection_rate)):
            raise ValueError("Scenario fractions exceed one")


SCENARIOS = (Scenario("idiosyncratic", 1.0, .60, .05, .25, .98),
             Scenario("market_wide", 1.4, .30, .15, .40, .90),
             Scenario("combined", 2.0, .00, .25, .70, .80))
BASE_RUNOFF = {"retail_stable": .03, "retail_less_stable": .12, "operational": .25,
               "corporate_nonoperational": .45, "financial_nonoperational": .75}


def deposit_segment(row: pd.Series) -> str:
    """Resolve deposit segments before applying internal stress assumptions."""
    if row.counterparty_type == "retail":
        return "retail_stable" if retail_stable(row) else "retail_less_stable"
    if row.operational:
        return "operational"
    return "financial_nonoperational" if row.counterparty_type in {"financial", "bank"} else "corporate_nonoperational"


def assumption_table(scenarios: tuple[Scenario, ...] = SCENARIOS) -> pd.DataFrame:
    """Expose every scenario coefficient and horizon runoff assumption."""
    rows = []
    for scenario in scenarios:
        for horizon, multiplier in [(30, 1.0), (90, 1.8), (365, 3.0)]:
            for segment, runoff in BASE_RUNOFF.items():
                rows.append((scenario.name, horizon, segment, min(1.0, runoff * scenario.severity * multiplier),
                             scenario.wholesale_rollover, scenario.haircut_shock, scenario.drawdown,
                             scenario.collection_rate, "stylized/unverified"))
    return pd.DataFrame(rows, columns=["scenario", "horizon", "deposit_segment", "cumulative_runoff",
                                      "wholesale_rollover", "haircut_shock", "facility_drawdown", "collection_rate", "status"])


def clri(positions: pd.DataFrame) -> pd.DataFrame:
    """Inventory undrawn facilities, derivative margin, and short wholesale rollover exposures."""
    rows = []
    for row in positions.itertuples():
        if row.product in {"credit_facility", "liquidity_facility"}:
            rows.append((row.position_id, "off_balance", "borrower liquidity demand", row.balance, 1, 30))
        elif row.product == "derivative":
            rows.append((row.position_id, "contingent_margin", "downgrade or valuation shock", row.balance * 2, 1, 30))
        elif row.product in {"debt", "repo"} and days_to(row.maturity_date) <= 365:
            rows.append((row.position_id, "refinancing", "market closure", row.balance,
                         max(1, days_to(row.maturity_date)), max(1, days_to(row.maturity_date))))
    return pd.DataFrame(rows, columns=["position_id", "exposure_type", "trigger", "size", "earliest_day", "latest_day"])


@dataclass
class StressResult:
    summary: dict[str, float | str | bool]
    daily: pd.DataFrame
    horizons: pd.DataFrame
    resources: pd.DataFrame
    usage_waterfall: pd.DataFrame


def stress(positions: pd.DataFrame, scenario: Scenario, horizon: int = 365) -> StressResult:
    """Evaluate daily cash after immediate monetization and exclusive collateral borrowing."""
    if horizon < 1 or horizon > 365:
        raise ValueError("Supported stress horizon is one through 365 calendar days")
    if not validate_positions(positions).empty:
        raise ValueError("Invalid positions")
    collateral = inventory(positions, shock=scenario.haircut_shock)
    borrowed = collateral.set_index("position_id").lendable_value.to_dict()
    assets = positions.loc[positions.side.eq("asset")]
    cash = float(assets.loc[assets["product"].eq("cash"), "balance"].sum())
    liquid = assets.loc[assets["product"].isin(["treasury", "agency", "corporate_bond"]) & ~assets.encumbered]
    sales = sum(row.balance * max(0.0, HAIRCUT_VALUE[row.collateral_class] - scenario.haircut_shock)
                for row in liquid.itertuples())
    fhlb = float(collateral.loc[collateral.allocated_venue.eq("FHLB"), "lendable_value"].sum())
    dw = float(collateral.loc[collateral.allocated_venue.eq("discount_window"), "lendable_value"].sum())
    resources = pd.DataFrame([("cash", cash), ("securities", sales), ("FHLB", fhlb), ("discount_window", dw)],
                             columns=["resource", "capacity"])
    cbc = float(resources.capacity.sum())
    days = np.arange(1, horizon + 1)
    deposit = np.zeros(horizon)
    wholesale = np.zeros(horizon)
    collections = np.zeros(horizon)
    released = np.zeros(horizon)
    facilities = np.zeros(horizon)
    margin = np.zeros(horizon)
    other = np.zeros(horizon)
    scale = np.interp(days, [0, 30, 90, 365], [0.0, 1.0, 1.8, 3.0])
    indexed = positions.set_index("position_id")
    for _, row in positions.iterrows():
        product, due = row["product"], max(1, days_to(row.maturity_date))
        if product == "deposit":
            deposit += row.balance * np.minimum(1.0, BASE_RUNOFF[deposit_segment(row)] * scenario.severity * scale)
        elif product in {"debt", "repo"}:
            wholesale += (days >= due) * row.balance * (1 - scenario.wholesale_rollover)
            if product == "repo":
                asset = indexed.loc[row.collateral_asset_id]
                value = asset.balance * max(0.0, HAIRCUT_VALUE.get(asset.collateral_class, .5) - scenario.haircut_shock)
                released += (days >= due) * value * (1 - scenario.wholesale_rollover)
        elif product in {"credit_facility", "liquidity_facility"}:
            facilities += row.balance * scenario.drawdown * np.minimum(days / 30, 1.0)
        elif product == "derivative":
            other += (days >= due) * row.balance
            margin += row.balance * 2 * min(scenario.severity / 2, 1.0) * np.minimum(days / 30, 1.0)
        elif row.side == "liability":
            other += (days >= due) * row.balance
        elif row.side == "asset" and product in {"mortgage", "loan", "reverse_repo"}:
            # Immediate borrowing must be repaid as its pledged loans mature.
            free_proceeds = not row.encumbered or days_to(row.encumbrance_end) <= due
            collection = row.balance * scenario.collection_rate if row.performing and free_proceeds else 0.0
            collections += (days >= due) * (collection - borrowed.get(row.position_id, 0.0))
    cumulative_out = deposit + wholesale + facilities + margin + other
    cumulative_in = collections + released
    net_need = cumulative_out - cumulative_in
    daily = pd.DataFrame(dict(day=days, deposit_runoff=deposit, wholesale_repayment=wholesale,
                              facility_draws=facilities, margin_calls=margin, other_outflows=other,
                              net_asset_collections=collections, released_collateral= released,
                              cumulative_outflows=cumulative_out, cumulative_inflows=cumulative_in,
                              net_need=net_need, liquidity_balance=cbc - net_need))
    failures = daily.loc[daily.liquidity_balance.lt(0), "day"]
    survival = int(failures.iloc[0] - 1) if not failures.empty else horizon
    peak_need = max(0.0, float(daily.net_need.max()))
    summary = dict(scenario=scenario.name, counterbalancing_capacity=cbc, survival_days=survival,
                   censored=failures.empty, peak_net_need=peak_need, maximum_shortfall=max(0.0, peak_need - cbc))
    snapshots = daily.loc[daily.day.isin([30, 90, 365])].copy()
    snapshots.insert(0, "scenario", scenario.name)
    return StressResult(summary, daily, snapshots, resources, waterfall(peak_need, cash, sales, fhlb, dw))
