"""Export daily liquidity sensitivity to compounded combined-scenario shocks."""

from pathlib import Path
import sys

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from liquidity_suite.common import markdown_table
from liquidity_suite.data import generate_bank
from liquidity_suite.ilst import Scenario, stress
from liquidity_suite.report import write_table


def run() -> pd.DataFrame:
    """Vary runoff, collection, haircuts, and drawdowns coherently."""
    positions = generate_bank()
    rows = []
    for multiplier in (.5, .75, 1.0, 1.25, 1.5):
        scenario = Scenario(f"combined_x{multiplier:.2f}", 2 * multiplier, 0,
                            min(1, .25 * multiplier), min(1, .70 * multiplier), max(0, 1 - .20 * multiplier))
        result = stress(positions, scenario)
        rows.append(dict(multiplier=multiplier, **result.summary))
    results = pd.DataFrame(rows)
    write_table(results, PROJECT / "examples" / "output" / "stress_sensitivity")
    return results


if __name__ == "__main__":
    print(markdown_table(run()))
