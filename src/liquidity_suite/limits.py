"""Internal risk appetite tiers with explicit threshold ownership."""

from dataclasses import dataclass
import math

import pandas as pd

OCC_SOURCE = "https://www.occ.gov/publications-and-resources/publications/comptrollers-handbook/files/liquidity/pub-ch-liquidity.pdf"


@dataclass(frozen=True)
class Limit:
    name: str
    direction: str
    green: float
    red: float
    owner: str
    topic: str

    def __post_init__(self) -> None:
        if self.direction not in {"minimum", "maximum"}:
            raise ValueError("Limit direction must be minimum or maximum")
        if not all(math.isfinite(value) for value in (self.green, self.red)):
            raise ValueError("Thresholds must be finite")
        if (self.direction == "minimum" and self.green < self.red) or (self.direction == "maximum" and self.green > self.red):
            raise ValueError("Green and red thresholds are reversed")

    def status(self, value: float) -> str:
        """Equality is green at the green threshold and amber at the red threshold."""
        if not math.isfinite(value):
            return "red"
        if self.direction == "minimum":
            return "green" if value >= self.green else ("red" if value < self.red else "amber")
        return "green" if value <= self.green else ("red" if value > self.red else "amber")


LIMITS = (Limit("LCR", "minimum", 1.20, 1.00, "Treasurer", "Liquidity Coverage Ratio Examination Procedures"),
          Limit("NSFR", "minimum", 1.10, 1.00, "Treasurer", "Net Stable Funding Ratio Examination Procedures"),
          Limit("ILST survival days", "minimum", 90.0, 30.0, "Chief Risk Officer", "Contingency Funding Plans"),
          Limit("Wholesale funding concentration", "maximum", .30, .40, "Funding Desk", "Funding Diversification"),
          Limit("Intraday usage", "maximum", .70, .90, "Payments Head", "Intraday Liquidity and Collateral Management"))


def framework() -> pd.DataFrame:
    """Generate stylized internal thresholds and verified OCC topic mappings."""
    return pd.DataFrame([dict(kri=item.name, direction=item.direction, green_threshold=item.green,
                              red_threshold=item.red, owner=item.owner, topic=item.topic, source=OCC_SOURCE,
                              parameter_status="stylized internal appetite") for item in LIMITS])


def evaluate(values: dict[str, float]) -> pd.DataFrame:
    """Report every KRI, with explicit missing-data breaches and escalation routes."""
    rows = []
    for item in LIMITS:
        value = values.get(item.name, math.nan)
        status = item.status(value)
        escalation = "routine monitoring" if status == "green" else (
            f"{item.owner}: review next business day" if status == "amber" else f"{item.owner} and ALCO: immediate escalation")
        rows.append((item.name, value, status, item.owner, escalation, item.topic, OCC_SOURCE))
    return pd.DataFrame(rows, columns=["kri", "value", "status", "owner", "escalation", "topic", "source"])


def breach_report(report: pd.DataFrame) -> pd.DataFrame:
    """Select amber and red exceptions for management action."""
    return report.loc[report.status.ne("green")].reset_index(drop=True)


def wholesale_concentration(positions: pd.DataFrame) -> float:
    """Measure wholesale deposits plus debt and repo as a share of total liabilities."""
    liabilities = positions.loc[positions.side.eq("liability")]
    wholesale = liabilities["product"].isin(["debt", "repo"]) | (
        liabilities["product"].eq("deposit") & liabilities.counterparty_type.ne("retail"))
    total = float(liabilities.balance.sum())
    return float(liabilities.loc[wholesale, "balance"].sum()) / total if total else 0.0
