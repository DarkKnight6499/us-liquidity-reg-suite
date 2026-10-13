"""Seeded granular synthetic balance sheet and principal cash flows."""

import numpy as np
import pandas as pd

from .common import AS_OF, SEED


def generate_bank(seed: int = SEED) -> pd.DataFrame:
    """Generate a balanced synthetic bank without external data."""
    rng = np.random.default_rng(seed)
    as_of = AS_OF
    rows: list[dict] = []

    def add(product: str, side: str, total: float, counterparty: str,
            collateral: str = "none", count: int = 40, pledged: bool = False,
            insured: bool = False, operational: bool = False,
            relationship: bool = False, maturities: tuple = (15, 30, 90, 180, 365, 730)) -> list[dict]:
        weights = rng.dirichlet(np.ones(count)) * total
        group = []
        for amount in weights:
            day = int(rng.choice(maturities))
            row = dict(position_id=f"P{len(rows):05d}", side=side, product=product,
                       counterparty_type=counterparty, counterparty_id=f"{counterparty}_{rng.integers(1, 21):02d}",
                       balance=float(amount), maturity_date=pd.NaT if day < 0 else as_of + pd.Timedelta(days=day),
                       currency="USD", collateral_class=collateral, encumbered=pledged,
                       encumbrance_end=as_of + pd.Timedelta(days=20) if pledged else pd.NaT,
                       insured=insured, operational=operational, relationship=relationship,
                       performing=True, risk_weight=0.5 if product == "mortgage" else 1.0,
                       collateral_asset_id="")
            rows.append(row)
            group.append(row)
        return group

    add("cash", "asset", 12000, "central_bank", "L1", maturities=(-1,))
    add("treasury", "asset", 15000, "sovereign", "L1", maturities=(365, 730))
    add("agency", "asset", 6000, "corporate", "L2A", maturities=(365, 730))
    add("corporate_bond", "asset", 2000, "corporate", "L2B", maturities=(365, 730))
    for product, total, collateral, funding_fraction in [("treasury", 3000, "L1", .95),
                                                        ("agency", 4000, "L2A", .85),
                                                        ("corporate_bond", 2000, "L2B", .5)]:
        assets = add(product, "asset", total, "sovereign" if product == "treasury" else "corporate",
                     collateral, count=12, pledged=True, maturities=(730,))
        for asset in assets:
            repo = add("repo", "liability", asset["balance"] * funding_fraction,
                       "financial", collateral, count=1, maturities=(20,))[0]
            repo["collateral_asset_id"] = asset["position_id"]
    add("mortgage", "asset", 30000, "retail", "mortgage", maturities=(365, 730, 1825))
    add("mortgage", "asset", 6000, "retail", "mortgage", pledged=True, maturities=(1825,))
    for row in rows:
        if row["product"] == "mortgage" and row["encumbered"]:
            row["encumbrance_end"] = as_of + pd.Timedelta(days=730)
    add("loan", "asset", 24000, "corporate", "loan")
    add("loan", "asset", 8000, "financial", "loan")
    add("reverse_repo", "asset", 8000, "financial", "loan", maturities=(15, 30, 90))
    add("deposit", "liability", 35000, "retail", insured=True, relationship=True, maturities=(-1,))
    add("deposit", "liability", 20000, "retail", maturities=(-1,))
    add("deposit", "liability", 10000, "corporate", operational=True, maturities=(-1,))
    add("deposit", "liability", 15000, "corporate", maturities=(-1,))
    add("deposit", "liability", 5000, "financial", maturities=(-1,))
    add("debt", "liability", 15750, "financial")
    add("derivative", "liability", 1000, "financial", maturities=(10, 20, 30))
    add("other", "liability", 1000, "corporate", maturities=(10, 30, 90))
    add("equity", "equity", 10000, "corporate", maturities=(-1,))
    add("credit_facility", "off_balance", 14000, "corporate", maturities=(30,))
    add("credit_facility", "off_balance", 4000, "retail", maturities=(30,))
    add("liquidity_facility", "off_balance", 2000, "financial", maturities=(30,))
    return pd.DataFrame(rows)


def contractual_cashflows(positions: pd.DataFrame) -> pd.DataFrame:
    """Produce principal-only flows, excluding cash, capital, and undrawn commitments."""
    eligible = positions.side.isin(["asset", "liability"]) & positions["product"].ne("cash")
    result = positions.loc[eligible, ["position_id", "maturity_date", "balance", "side", "product", "currency"]].copy()
    result["flow_date"] = result.maturity_date.fillna(AS_OF)
    result["direction"] = np.where(result.side.eq("asset"), "inflow", "outflow")
    result["signed_amount"] = np.where(result.side.eq("asset"), result.balance, -result.balance)
    return result.drop(columns=["maturity_date", "side"]).reset_index(drop=True)
