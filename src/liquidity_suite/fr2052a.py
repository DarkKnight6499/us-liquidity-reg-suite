"""FR 2052a-style partitions with local codes and source reconciliation."""

import numpy as np
import pandas as pd
from numbers import Real

from .common import AS_OF, COLLATERAL, COUNTERPARTIES, PRODUCTS, REQUIRED, SIDES, days_to

TABLE_NAMES = {"I.A": "Inflows-Assets", "I.U": "Inflows-Unsecured", "I.S": "Inflows-Secured",
               "O.D": "Outflows-Deposits", "O.W": "Outflows-Wholesale", "O.S": "Outflows-Secured",
               "O.O": "Outflows-Other", "S": "Supplemental"}
COUNTERPARTY_CODES = {name: f"LOCAL_{name.upper()}" for name in COUNTERPARTIES}
BUCKETS = ("demand", "overnight", "2_to_7", "8_to_30", "31_to_90", "91_to_180", "181_to_365", "over_365")


def maturity_bucket(date: object, as_of: pd.Timestamp = AS_OF) -> str:
    """Assign mutually exclusive local maturity buckets, not filing codes."""
    if pd.isna(date):
        return "demand"
    days = days_to(date, as_of)
    if days < 0:
        raise ValueError("Maturity precedes calculation date")
    for ceiling, name in zip((1, 7, 30, 90, 180, 365), BUCKETS[1:-1]):
        if days <= ceiling:
            return name
    return "over_365"


def validate_positions(positions: pd.DataFrame) -> pd.DataFrame:
    """Return all detectable source defects without silently repairing them."""
    defects = []

    def report(identifier: object, rule: str, detail: str) -> None:
        defects.append((str(identifier), rule, detail))

    missing = set(REQUIRED) - set(positions.columns)
    for column in sorted(missing):
        report("SCHEMA", "completeness", f"Missing column: {column}")
    if missing:
        return pd.DataFrame(defects, columns=["position_id", "rule", "detail"])
    for row in positions.to_dict("records"):
        identifier = row["position_id"]
        incomplete = False
        for column in REQUIRED:
            if column not in {"maturity_date", "encumbrance_end", "collateral_asset_id"} and pd.isna(row[column]):
                report(identifier, "completeness", column)
                incomplete = True
        if incomplete:
            continue
        for field, allowed in [("side", SIDES), ("product", PRODUCTS), ("counterparty_type", COUNTERPARTIES),
                               ("collateral_class", COLLATERAL), ("currency", {"USD"})]:
            if row[field] not in allowed:
                report(identifier, "valid_code", field)
        try:
            if not isinstance(row["balance"], Real) or isinstance(row["balance"], (bool, np.bool_)) or not np.isfinite(float(row["balance"])) or float(row["balance"]) < 0:
                report(identifier, "nonnegative_balance", "Balance must be finite and nonnegative")
        except (TypeError, ValueError):
            report(identifier, "nonnegative_balance", "Balance must be numeric")
        for field in ("maturity_date", "encumbrance_end"):
            if not pd.isna(row[field]):
                try:
                    if pd.Timestamp(row[field]) < AS_OF:
                        report(identifier, "date", field)
                except (ValueError, TypeError):
                    report(identifier, "date", field)
        for field in ("insured", "operational", "relationship", "encumbered", "performing"):
            if not isinstance(row[field], (bool, np.bool_)):
                report(identifier, "boolean", field)
        expected_side = ("asset" if row["product"] in {"cash", "treasury", "agency", "corporate_bond", "mortgage", "loan", "reverse_repo"}
                         else "equity" if row["product"] == "equity" else "off_balance" if row["product"] in {
                             "credit_facility", "liquidity_facility"} else "liability")
        if row["side"] != expected_side:
            report(identifier, "product_side", "Unsupported product and side combination")
        expected_collateral = {"cash": "L1", "treasury": "L1", "agency": "L2A", "corporate_bond": "L2B"}
        if row["product"] in expected_collateral and row["collateral_class"] != expected_collateral[row["product"]]:
            report(identifier, "collateral_class", "Synthetic liquid asset class differs from product")
        try:
            if not isinstance(row["risk_weight"], Real) or not np.isfinite(float(row["risk_weight"])) or row["risk_weight"] < 0:
                report(identifier, "risk_weight", "Risk weight must be finite and nonnegative")
        except (TypeError, ValueError):
            report(identifier, "risk_weight", "Risk weight must be numeric")
        if row["product"] not in {"deposit", "equity", "cash"} and pd.isna(row["maturity_date"]):
            report(identifier, "completeness", "Contractual maturity required for this product")
        if isinstance(row["encumbered"], (bool, np.bool_)) and row["encumbered"] and pd.isna(row["encumbrance_end"]):
            report(identifier, "completeness", "Encumbrance end required")
        if row["product"] == "deposit" and row["insured"] and row["counterparty_type"] == "financial":
            report(identifier, "deposit_flags", "Synthetic financial deposits cannot be insured")
    for identifier in positions.loc[positions.position_id.duplicated(keep=False), "position_id"]:
        report(identifier, "unique_id", "Duplicate position ID")
    assets = positions.loc[positions.side.eq("asset")].set_index("position_id")
    for row in positions.loc[positions["product"].eq("repo")].to_dict("records"):
        reference = row["collateral_asset_id"]
        if reference not in assets.index:
            report(row["position_id"], "collateral_link", "Missing collateral asset")
        elif not assets.index.duplicated().any():
            asset = assets.loc[reference]
            if not asset.encumbered or asset.collateral_class != row["collateral_class"]:
                report(row["position_id"], "collateral_link", "Collateral flags disagree")
            if pd.isna(row["maturity_date"]) or pd.isna(asset.encumbrance_end) or row["maturity_date"] != asset.encumbrance_end:
                report(row["position_id"], "collateral_link", "Repo maturity and collateral release differ")
    repos = positions.loc[positions["product"].eq("repo")]
    for identifier in repos.loc[repos.collateral_asset_id.duplicated(keep=False), "position_id"]:
        report(identifier, "collateral_link", "Collateral asset allocated to multiple repo transactions")
    return pd.DataFrame(defects, columns=["position_id", "rule", "detail"])


def _classification(row: pd.Series) -> tuple[str, str]:
    product = row["product"]
    if row.side == "equity":
        return "S", "S.B.1"
    if product == "deposit":
        code = "O.D.4" if row.operational else ("O.D.1" if row.counterparty_type == "retail" else "O.D.6")
        return "O.D", code
    if product == "repo":
        return "O.S", "O.S.1"
    if product == "debt":
        return "O.W", "O.W.11"
    if product in {"other", "derivative", "credit_facility", "liquidity_facility"}:
        return "O.O", {"other": "O.O.22", "derivative": "O.O.1", "credit_facility": "O.O.4",
                       "liquidity_facility": "O.O.5"}[product]
    if product in {"reverse_repo", "mortgage"}:
        return "I.S", "I.S.1" if product == "reverse_repo" else "I.S.8"
    if product == "loan":
        return "I.U", "I.U.6"
    return "I.A", "I.A.3" if product == "cash" else ("I.A.7" if row.encumbered else "I.A.1")


def transform(positions: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Partition each source position once, retaining lineage and unweighted balances."""
    defects = validate_positions(positions)
    if not defects.empty:
        raise ValueError(f"Source data has {len(defects)} exceptions")
    result = positions.copy()
    codes = result.apply(_classification, axis=1)
    result["table_code"] = [code[0] for code in codes]
    result["product_code"] = [code[1] for code in codes]
    result["counterparty_code"] = result.counterparty_type.map(COUNTERPARTY_CODES)
    result["bucket"] = result.maturity_date.map(maturity_bucket)
    return {code: result.loc[result.table_code.eq(code)].reset_index(drop=True) for code in TABLE_NAMES}


def bucket_totals(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Aggregate balances by table and local maturity bucket."""
    detail = pd.concat(tables.values(), ignore_index=True)
    return detail.groupby(["table_code", "bucket"], observed=True).balance.sum().reset_index()


def validate_tables(positions: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Check coverage, lineage, valid codes, classification, and bucket conservation."""
    defects = []
    fields = {"position_id", "table_code", "product_code", "counterparty_code", "bucket", "balance"}
    if not tables or any(not fields.issubset(table.columns) for table in tables.values()):
        return pd.DataFrame([("ALL", "completeness", "Missing table fields")], columns=["position_id", "rule", "detail"])
    detail = pd.concat(tables.values(), ignore_index=True)
    expected = pd.concat(transform(positions).values(), ignore_index=True).set_index("position_id")
    if set(tables) != set(TABLE_NAMES):
        defects.append(("ALL", "table_set", "Missing or unexpected table"))
    if detail.position_id.duplicated().any() or set(detail.position_id) != set(positions.position_id):
        defects.append(("ALL", "coverage", "Source positions must occur exactly once"))
    for key, table in tables.items():
        if not table.table_code.eq(key).all():
            defects.append((key, "table_code", "Partition and code differ"))
    for row in detail.to_dict("records"):
        identifier = row["position_id"]
        if identifier not in expected.index:
            continue
        source = expected.loc[identifier]
        for field in ("table_code", "product_code", "counterparty_code", "bucket", "balance"):
            if row[field] != source[field]:
                defects.append((identifier, "lineage", field))
    for key, table in tables.items():
        source_total = expected.loc[expected.table_code.eq(key), "balance"].sum()
        grouped_total = table.groupby("bucket").balance.sum().sum()
        if not np.isclose(source_total, grouped_total, rtol=0, atol=1e-7):
            defects.append((key, "bucket_reconciliation", "Bucket sum differs from source"))
    return pd.DataFrame(defects, columns=["position_id", "rule", "detail"])
