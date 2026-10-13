"""Stylized collateral eligibility and exclusive venue allocation."""

from collections.abc import Mapping

import pandas as pd

from .common import nonnegative
from .fr2052a import validate_positions

# These are scenario assumptions, not published venue haircut schedules.
STYLIZED_HAIRCUTS = {"FHLB": {"mortgage": .25, "L2A": .12},
                     "discount_window": {"mortgage": .30, "loan": .40, "L1": .03, "L2A": .15, "L2B": .50}}


def inventory(positions: pd.DataFrame, haircuts: Mapping | None = None, shock: float = 0.0,
              exclude_hqla: bool = True) -> pd.DataFrame:
    """Tag alternatives but allocate each free asset to exactly one borrowing venue."""
    nonnegative((shock,))
    if shock > 1:
        raise ValueError("Haircut shock exceeds one")
    if not validate_positions(positions).empty:
        raise ValueError("Invalid positions")
    schedules = STYLIZED_HAIRCUTS if haircuts is None else haircuts
    if set(schedules) != {"FHLB", "discount_window"}:
        raise ValueError("Both borrowing venues must be specified")
    for schedule in schedules.values():
        nonnegative(schedule.values())
        if any(value > 1 for value in schedule.values()):
            raise ValueError("Haircuts exceed one")
    assets = positions.loc[positions.side.eq("asset") & positions["product"].isin(
        ["mortgage", "loan", "treasury", "agency", "corporate_bond"])]
    rows = []
    for row in assets.itertuples():
        fhlb_eligible = row.collateral_class in schedules["FHLB"] and row.performing
        dw_eligible = row.collateral_class in schedules["discount_window"] and row.performing
        available = not row.encumbered and (not exclude_hqla or row.collateral_class not in {"L1", "L2A", "L2B"})
        alternatives = {venue: row.balance * (1 - min(1.0, schedule[row.collateral_class] + shock))
                        for venue, schedule in schedules.items()
                        if row.collateral_class in schedule and row.performing}
        venue = max(alternatives, key=alternatives.get) if alternatives and available else "unavailable"
        rows.append((row.position_id, row.collateral_class, row.balance, row.encumbered, fhlb_eligible, dw_eligible,
                     venue, alternatives.get("FHLB", 0.0), alternatives.get("discount_window", 0.0),
                     alternatives.get(venue, 0.0) if available else 0.0, "stylized/unverified"))
    return pd.DataFrame(rows, columns=["position_id", "collateral_class", "balance", "encumbered", "fhlb_eligible",
                                      "discount_window_eligible", "allocated_venue", "fhlb_alternative_value",
                                      "discount_window_alternative_value", "lendable_value", "parameter_status"])


def capacity(inventory_table: pd.DataFrame) -> float:
    """Sum only mutually exclusive allocation values."""
    return float(inventory_table.lendable_value.sum())


def waterfall(required: float, cash: float, securities: float, fhlb: float, discount_window: float) -> pd.DataFrame:
    """Consume resources once in liquidity order and expose any residual shortfall."""
    nonnegative((required, cash, securities, fhlb, discount_window))
    remaining = required
    rows = []
    for name, available in [("cash", cash), ("securities", securities), ("FHLB", fhlb), ("discount_window", discount_window)]:
        used = min(remaining, available)
        remaining -= used
        rows.append((name, available, used, available - used, remaining))
    return pd.DataFrame(rows, columns=["resource", "capacity", "used", "unused", "remaining_need"])
