"""Additional model boundary and artifact reconciliation checks."""

from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from liquidity_suite import calculate_lcr, calculate_nsfr, generate_bank
from liquidity_suite.collateral import capacity, inventory, waterfall
from liquidity_suite.common import AS_OF, markdown_table
from liquidity_suite.fr2052a import transform, validate_positions, validate_tables
from liquidity_suite.ilst import Scenario, stress
from liquidity_suite.intraday import monitor, simulate_payments
from test_suite import position, small_bank


class ModelEdgeTests(unittest.TestCase):
    def test_empty_reporting(self) -> None:
        bank = generate_bank().iloc[:0]
        tables = transform(bank)
        self.assertTrue(all(table.empty for table in tables.values()))
        self.assertTrue(validate_tables(bank, tables).empty)

    def test_empty_ratios(self) -> None:
        bank = generate_bank().iloc[:0]
        self.assertTrue(np.isnan(calculate_lcr(bank).summary["lcr"]))
        self.assertTrue(np.isnan(calculate_nsfr(bank).summary["nsfr"]))

    def test_nullable_required_flag_caught(self) -> None:
        bank = small_bank().astype({"insured": "object"})
        bank.loc[0, "insured"] = pd.NA
        self.assertIn("completeness", validate_positions(bank).rule.values)

    def test_string_balance_rejected(self) -> None:
        bank = small_bank().astype({"balance": "object"})
        bank.loc[0, "balance"] = "100"
        self.assertIn("nonnegative_balance", validate_positions(bank).rule.values)

    def test_invalid_product_side_caught(self) -> None:
        bank = small_bank()
        bank.loc[0, "side"] = "liability"
        self.assertIn("product_side", validate_positions(bank).rule.values)

    def test_hqla_class_mismatch_caught(self) -> None:
        bank = small_bank()
        bank.loc[0, "collateral_class"] = "L2B"
        self.assertIn("collateral_class", validate_positions(bank).rule.values)

    def test_negative_risk_weight_caught(self) -> None:
        bank = small_bank()
        bank.loc[0, "risk_weight"] = -1
        self.assertIn("risk_weight", validate_positions(bank).rule.values)

    def test_missing_contractual_maturity_caught(self) -> None:
        bank = small_bank()
        bank.loc[bank["product"].eq("mortgage"), "maturity_date"] = pd.NaT
        self.assertIn("completeness", validate_positions(bank).rule.values)

    def test_missing_report_field(self) -> None:
        bank = small_bank()
        tables = transform(bank)
        tables["I.A"] = tables["I.A"].drop(columns="bucket")
        self.assertIn("completeness", validate_tables(bank, tables).rule.values)

    def test_missing_source_position_caught(self) -> None:
        bank = small_bank()
        tables = transform(bank)
        tables["I.A"] = tables["I.A"].iloc[:0]
        self.assertIn("coverage", validate_tables(bank, tables).rule.values)

    def test_term_wholesale_outside_window_excluded(self) -> None:
        bank = pd.DataFrame([position("deposit", "liability", 100, position_id="deposit",
                                      maturity_date=AS_OF + pd.Timedelta(days=31))])
        self.assertEqual(calculate_lcr(bank).summary["outflows"], 0)
        bank.loc[0, "maturity_date"] = AS_OF + pd.Timedelta(days=30)
        self.assertEqual(calculate_lcr(bank).summary["outflows"], 40)

    def test_retail_term_regardless_maturity(self) -> None:
        bank = pd.DataFrame([position("deposit", "liability", 100, position_id="deposit", counterparty_type="retail",
                                      maturity_date=AS_OF + pd.Timedelta(days=730))])
        self.assertEqual(calculate_lcr(bank).summary["outflows"], 10)

    def test_custom_haircuts_change_allocation(self) -> None:
        schedules = {"FHLB": {"mortgage": .8}, "discount_window": {"mortgage": .1}}
        result = inventory(small_bank(), haircuts=schedules)
        self.assertEqual(capacity(result), 90)
        self.assertEqual(result.allocated_venue.iloc[0], "discount_window")

    def test_negative_waterfall_rejected(self) -> None:
        with self.assertRaises(ValueError):
            waterfall(-1, 1, 1, 1, 1)

    def test_restricted_maturity_proceeds(self) -> None:
        bank = pd.DataFrame([position("mortgage", balance=100, collateral_class="mortgage", counterparty_type="retail",
                                      encumbered=True, encumbrance_end=AS_OF + pd.Timedelta(days=730))])
        result = stress(bank, Scenario("calm", 0, 1, 0, 0, 1), horizon=30)
        self.assertEqual(result.daily.net_asset_collections.iloc[-1], 0)
        self.assertEqual(result.summary["counterbalancing_capacity"], 0)

    def test_first_day_survival_failure(self) -> None:
        bank = pd.DataFrame([position("deposit", "liability", 100, counterparty_type="retail", maturity_date=pd.NaT)])
        result = stress(bank, Scenario("shock", 1, 0, 0, 0, 1))
        self.assertEqual(result.summary["survival_days"], 0)
        self.assertFalse(result.summary["censored"])

    def test_stress_horizon_rejected(self) -> None:
        with self.assertRaises(ValueError):
            stress(small_bank(), Scenario("calm", 0, 1, 0, 0, 1), horizon=366)

    def test_equal_timestamp_sequence(self) -> None:
        flows = pd.DataFrame(dict(payment_id=[2, 1], minute=[480, 480], signed_amount=[10., -10.],
                                  time_specific=[False, False], deadline=[np.nan, np.nan]))
        self.assertEqual(monitor(flows, 0).summary["maximum_usage"], 10)

    def test_intraday_duplicate_id_rejected(self) -> None:
        flows = simulate_payments(count=10)
        flows.loc[1, "payment_id"] = flows.loc[0, "payment_id"]
        with self.assertRaises(ValueError):
            monitor(flows, 0)

    def test_time_specific_without_deadline_rejected(self) -> None:
        flows = simulate_payments(count=10)
        flows.loc[0, "signed_amount"] = -10
        flows.loc[0, "time_specific"] = True
        flows.loc[0, "deadline"] = np.nan
        with self.assertRaises(ValueError):
            monitor(flows, 0)

    def test_markdown_cells_escape_pipes(self) -> None:
        table = markdown_table(pd.DataFrame({"name": ["a|b\nc"]}))
        self.assertIn("a/b c", table)
        self.assertIn(":-:", table)


if __name__ == "__main__":
    unittest.main()
