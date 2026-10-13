"""Run the complete synthetic bank example from any working directory."""

from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from liquidity_suite.common import markdown_table
from liquidity_suite.report import run_suite


if __name__ == "__main__":
    print(markdown_table(run_suite(PROJECT)))
