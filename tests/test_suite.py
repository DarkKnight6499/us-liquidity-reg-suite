"""Analytic benchmarks, conservation laws, boundary behavior, and injected defects."""

import math
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from liquidity_suite import contractual_cashflows, generate_bank
from liquidity_suite.collateral import capacity, inventory, waterfall
from liquidity_suite.common import AS_OF, nonnegative, ratio
from liquidity_suite.fr2052a import BUCKETS, TABLE_NAMES, bucket_totals, maturity_bucket, transform, validate_positions, validate_tables
from liquidity_suite.ilst import SCENARIOS, Scenario, assumption_table, clri, stress
from liquidity_suite.intraday import monitor, simulate_payments
from liquidity_suite.lcr import cap_excess, calculate_lcr, hqla, inflow_rate, net_outflows, outflow_rate
from liquidity_suite.limits import LIMITS, Limit, breach_report, evaluate, framework, wholesale_concentration
from liquidity_suite.nsfr import asf_factor, calculate_nsfr, maturity_term, rsf_factor


def position(product: str = "cash", side: str = "asset", balance: float = 100.0, **kwargs: object) -> pd.Series:
    """Build a complete independently specified unit-test position."""
    row = dict(position_id="X", product=product, side=side, balance=balance,
               counterparty_type="corporate", counterparty_id="C", maturity_date=AS_OF + pd.Timedelta(days=30),
               currency="USD", collateral_class="none", encumbered=False, encumbrance_end=pd.NaT,
               insured=False, operational=False, relationship=False, performing=True, risk_weight=1.0,
               collateral_asset_id="")
    row.update(kwargs)
    return pd.Series(row)


def small_bank() -> pd.DataFrame:
    return pd.DataFrame([position(balance=100, position_id="cash", collateral_class="L1"),
                         position("mortgage", balance=100, position_id="mortgage", collateral_class="mortgage",
                                  counterparty_type="retail", risk_weight=.5, maturity_date=AS_OF + pd.Timedelta(days=730)),
                         position("deposit", "liability", 150, position_id="deposit", counterparty_type="retail",
                                  insured=True, relationship=True, maturity_date=pd.NaT),
                         position("equity", "equity", 50, position_id="capital", maturity_date=pd.NaT)])


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bank = generate_bank()

    def test_reproducibility(self) -> None:
        pd.testing.assert_frame_equal(self.bank, generate_bank())

    def test_different_seed(self) -> None:
        self.assertFalse(self.bank.balance.equals(generate_bank(1).balance))

    def test_asset_target(self) -> None:
        self.assertAlmostEqual(self.bank.loc[self.bank.side.eq("asset"), "balance"].sum(), 120000)

    def test_balance_sheet_conservation(self) -> None:
        asset = self.bank.loc[self.bank.side.eq("asset"), "balance"].sum()
        funding = self.bank.loc[self.bank.side.isin(["liability", "equity"]), "balance"].sum()
        self.assertAlmostEqual(asset, funding)

    def test_source_valid(self) -> None:
        self.assertTrue(validate_positions(self.bank).empty)

    def test_flow_principal_reconciliation(self) -> None:
        flows = contractual_cashflows(self.bank)
        eligible = self.bank.side.isin(["asset", "liability"]) & self.bank["product"].ne("cash")
        self.assertAlmostEqual(flows.balance.sum(), self.bank.loc[eligible, "balance"].sum())
        self.assertAlmostEqual(flows.signed_amount.sum(), 108000 - 110000)

    def test_flow_signs(self) -> None:
        flows = contractual_cashflows(self.bank)
        self.assertTrue(flows.loc[flows.direction.eq("inflow"), "signed_amount"].ge(0).all())
        self.assertTrue(flows.loc[flows.direction.eq("outflow"), "signed_amount"].le(0).all())

    def test_flows_exclude_commitments_and_cash(self) -> None:
        flows = contractual_cashflows(self.bank)
        self.assertFalse(flows["product"].isin(["cash", "credit_facility", "liquidity_facility", "equity"]).any())


class ReportingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bank = generate_bank()
        cls.tables = transform(cls.bank)

    def test_tables_present(self) -> None:
        self.assertEqual(set(self.tables), set(TABLE_NAMES))

    def test_bucket_source_totals(self) -> None:
        totals = bucket_totals(self.tables)
        self.assertAlmostEqual(totals.balance.sum(), self.bank.balance.sum())
        for key, table in self.tables.items():
            self.assertAlmostEqual(totals.loc[totals.table_code.eq(key), "balance"].sum(), table.balance.sum())

    def test_each_position_once(self) -> None:
        detail = pd.concat(self.tables.values())
        self.assertEqual(len(detail), len(self.bank))
        self.assertFalse(detail.position_id.duplicated().any())

    def test_clean_reconciliation(self) -> None:
        self.assertTrue(validate_tables(self.bank, self.tables).empty)

    def test_bucket_boundaries(self) -> None:
        expected = {0: "overnight", 1: "overnight", 2: "2_to_7", 7: "2_to_7", 8: "8_to_30", 30: "8_to_30",
                    31: "31_to_90", 90: "31_to_90", 91: "91_to_180", 180: "91_to_180", 181: "181_to_365",
                    365: "181_to_365", 366: "over_365"}
        for days, bucket in expected.items():
            with self.subTest(days=days):
                self.assertEqual(maturity_bucket(AS_OF + pd.Timedelta(days=days)), bucket)
        self.assertEqual(maturity_bucket(pd.NaT), "demand")
        self.assertEqual(len(BUCKETS), 8)

    def test_past_maturity_rejected(self) -> None:
        with self.assertRaises(ValueError):
            maturity_bucket(AS_OF - pd.Timedelta(days=1))

    def test_missing_column(self) -> None:
        self.assertIn("completeness", validate_positions(self.bank.drop(columns="currency")).rule.values)

    def test_missing_value(self) -> None:
        bank = self.bank.copy()
        bank.loc[0, "counterparty_id"] = None
        self.assertIn("completeness", validate_positions(bank).rule.values)

    def test_negative_balance(self) -> None:
        bank = self.bank.copy()
        bank.loc[0, "balance"] = -1
        self.assertIn("nonnegative_balance", validate_positions(bank).rule.values)
        with self.assertRaises(ValueError):
            transform(bank)

    def test_infinite_balance(self) -> None:
        bank = self.bank.copy()
        bank.loc[0, "balance"] = np.inf
        self.assertIn("nonnegative_balance", validate_positions(bank).rule.values)

    def test_bad_counterparty(self) -> None:
        bank = self.bank.copy()
        bank.loc[0, "counterparty_type"] = "invented"
        self.assertIn("valid_code", validate_positions(bank).rule.values)

    def test_duplicate_id(self) -> None:
        bank = self.bank.copy()
        bank.loc[0, "position_id"] = bank.loc[1, "position_id"]
        self.assertIn("unique_id", validate_positions(bank).rule.values)

    def test_bad_collateral_link(self) -> None:
        bank = self.bank.copy()
        bank.loc[bank["product"].eq("repo"), "collateral_asset_id"] = "missing"
        self.assertIn("collateral_link", validate_positions(bank).rule.values)

    def test_missing_encumbrance_end(self) -> None:
        bank = self.bank.copy()
        bank.loc[bank.encumbered, "encumbrance_end"] = pd.NaT
        self.assertIn("completeness", validate_positions(bank).rule.values)

    def test_table_balance_corruption(self) -> None:
        tables = {key: value.copy() for key, value in self.tables.items()}
        tables["I.A"].loc[0, "balance"] += 1
        defects = validate_tables(self.bank, tables)
        self.assertIn("lineage", defects.rule.values)
        self.assertIn("bucket_reconciliation", defects.rule.values)

    def test_table_bucket_corruption(self) -> None:
        tables = {key: value.copy() for key, value in self.tables.items()}
        tables["I.A"].loc[0, "bucket"] = "invented"
        self.assertIn("lineage", validate_tables(self.bank, tables).rule.values)

    def test_table_counterparty_code_corruption(self) -> None:
        tables = {key: value.copy() for key, value in self.tables.items()}
        tables["I.A"].loc[0, "counterparty_code"] = "invented"
        self.assertIn("lineage", validate_tables(self.bank, tables).rule.values)


class LCRTests(unittest.TestCase):
    def test_hand_computed_small_bank(self) -> None:
        result = calculate_lcr(small_bank()).summary
        self.assertAlmostEqual(result["hqla"], 100)
        self.assertAlmostEqual(result["outflows"], 4.5)
        self.assertAlmostEqual(result["lcr"], 100 / 4.5)

    def test_haircuts(self) -> None:
        result = hqla(100, 10, 10)
        self.assertAlmostEqual(result.amount, 113.5)
        self.assertAlmostEqual(result.level2a, 8.5)
        self.assertAlmostEqual(result.level2b, 5)

    def test_level2_cap_binding(self) -> None:
        result = hqla(60, 100, 0)
        self.assertAlmostEqual(result.amount, 100.002)
        self.assertAlmostEqual(result.unadjusted_excess, 44.998)

    def test_level2b_cap_binding(self) -> None:
        result = hqla(100, 0, 100)
        self.assertAlmostEqual(result.amount, 117.65)
        self.assertAlmostEqual(result.unadjusted_excess, 32.35)

    def test_both_caps_binding(self) -> None:
        result = hqla(60, 10, 200)
        level2_excess = 108.5 - .6667 * 60
        level2b_excess = 100 - level2_excess - .1765 * 68.5
        self.assertAlmostEqual(result.amount, 168.5 - level2_excess - level2b_excess)

    def test_unwind_adjustment_binding(self) -> None:
        result = hqla(100, 20, 0, (20, 100, 0))
        self.assertAlmostEqual(result.adjusted_excess, 71.666)
        self.assertAlmostEqual(result.amount, 45.334)

    def test_unadjusted_excess_dominates(self) -> None:
        result = hqla(60, 100, 0, (100, 0, 0))
        self.assertAlmostEqual(result.amount, 100.002)

    def test_inflow_cap_binding(self) -> None:
        net, allowed = net_outflows(100, 100)
        self.assertEqual(net, 25)
        self.assertEqual(allowed, 75)

    def test_inflow_cap_nonbinding(self) -> None:
        self.assertEqual(net_outflows(100, 20), (80, 20))

    def test_zero_flows(self) -> None:
        self.assertEqual(net_outflows(0, 100), (0, 0))
        self.assertTrue(math.isinf(ratio(100, 0)))
        self.assertTrue(math.isnan(ratio(0, 0)))

    def test_negative_input(self) -> None:
        for values in [(-1, 0, 0), (1, -1, 0), (1, 0, -1)]:
            with self.assertRaises(ValueError):
                hqla(*values)
        with self.assertRaises(ValueError):
            net_outflows(1, -1)

    def test_nonfinite_input(self) -> None:
        with self.assertRaises(ValueError):
            cap_excess(np.inf, 0, 0)

    def test_hqla_homogeneity(self) -> None:
        self.assertAlmostEqual(hqla(1000, 2000, 1000).amount, 10 * hqla(100, 200, 100).amount)

    def test_hqla_monotone_level1(self) -> None:
        values = [hqla(x, 100, 100).amount for x in range(0, 200)]
        self.assertTrue(np.all(np.diff(values) >= -1e-9))

    def test_retail_rates(self) -> None:
        stable = position("deposit", "liability", counterparty_type="retail", insured=True, relationship=True)
        self.assertEqual(outflow_rate(stable)[0], .03)
        stable.relationship = False
        self.assertEqual(outflow_rate(stable)[0], .10)

    def test_wholesale_rates(self) -> None:
        row = position("deposit", "liability", operational=True, insured=True)
        self.assertEqual(outflow_rate(row)[0], .05)
        row.insured = False
        self.assertEqual(outflow_rate(row)[0], .25)
        row.operational = False
        self.assertEqual(outflow_rate(row)[0], .40)
        row.insured = True
        self.assertEqual(outflow_rate(row)[0], .20)
        row.counterparty_type = "financial"
        self.assertEqual(outflow_rate(row)[0], 1.0)

    def test_secured_rates(self) -> None:
        for level, expected in [("L1", 0), ("L2A", .15), ("L2B", .50), ("none", 1)]:
            self.assertEqual(outflow_rate(position("repo", "liability", collateral_class=level))[0], expected)

    def test_facility_rates(self) -> None:
        for cp, credit, liquidity in [("retail", .05, .05), ("corporate", .10, .30), ("financial", .40, 1), ("bank", .50, .50)]:
            self.assertEqual(outflow_rate(position("credit_facility", "off_balance", counterparty_type=cp))[0], credit)
            self.assertEqual(outflow_rate(position("liquidity_facility", "off_balance", counterparty_type=cp))[0], liquidity)

    def test_inflow_rates_and_hqla_exclusion(self) -> None:
        self.assertEqual(inflow_rate(position("loan", counterparty_type="retail"))[0], .5)
        self.assertEqual(inflow_rate(position("loan", counterparty_type="financial"))[0], 1)
        self.assertEqual(inflow_rate(position("treasury", collateral_class="L1"))[0], 0)
        self.assertEqual(inflow_rate(position("loan", performing=False))[0], 0)

    def test_granular_reconciliation(self) -> None:
        result = calculate_lcr(generate_bank())
        self.assertAlmostEqual(result.contributions.loc[result.contributions.direction.eq("outflow"), "amount"].sum(), result.summary["outflows"])
        self.assertAlmostEqual(result.contributions.loc[result.contributions.direction.eq("inflow"), "amount"].sum(), result.summary["inflows"])
        self.assertAlmostEqual(result.unwind.cash_paid.sum(), 7250)
        self.assertAlmostEqual(result.unwind.collateral_returned.sum(), 9000)

    def test_maturity_mismatch_addon(self) -> None:
        bank = small_bank()
        debt = position("debt", "liability", 20, position_id="D", maturity_date=AS_OF + pd.Timedelta(days=2))
        loan = position("loan", "asset", 20, position_id="L", counterparty_type="financial", maturity_date=AS_OF + pd.Timedelta(days=29))
        result = calculate_lcr(pd.concat([bank, pd.DataFrame([debt, loan])], ignore_index=True)).summary
        self.assertEqual(result["mismatch_addon"], 20)
        self.assertAlmostEqual(result["net_outflows"], 24.5 - min(20, .75 * 24.5) + 20)

    def test_maturity_30_included_31_excluded(self) -> None:
        bank = small_bank()
        loan = position("loan", "asset", 1, position_id="L", counterparty_type="financial")
        included = calculate_lcr(pd.concat([bank, pd.DataFrame([loan])], ignore_index=True)).summary["inflows"]
        loan.maturity_date += pd.Timedelta(days=1)
        excluded = calculate_lcr(pd.concat([bank, pd.DataFrame([loan])], ignore_index=True)).summary["inflows"]
        self.assertEqual(included, 1)
        self.assertEqual(excluded, 0)


class NSFRTests(unittest.TestCase):
    def test_hand_computed_case(self) -> None:
        result = calculate_nsfr(small_bank()).summary
        self.assertEqual(result["asf"], 192.5)
        self.assertEqual(result["rsf"], 65)
        self.assertAlmostEqual(result["nsfr"], 192.5 / 65)

    def test_asf_retail(self) -> None:
        row = position("deposit", "liability", counterparty_type="retail", insured=True, relationship=True)
        self.assertEqual(asf_factor(row)[0], .95)
        row.relationship = False
        self.assertEqual(asf_factor(row)[0], .90)

    def test_asf_wholesale_maturity(self) -> None:
        row = position("debt", "liability", counterparty_type="financial")
        self.assertEqual(asf_factor(row)[0], 0)
        row.maturity_date = AS_OF + pd.DateOffset(months=6)
        self.assertEqual(asf_factor(row)[0], .5)
        row.maturity_date = AS_OF + pd.DateOffset(years=1)
        self.assertEqual(asf_factor(row)[0], 1)

    def test_operational_asf(self) -> None:
        self.assertEqual(asf_factor(position("deposit", "liability", operational=True))[0], .5)

    def test_rsf_liquid_levels(self) -> None:
        for product, level, expected in [("cash", "L1", 0), ("treasury", "L1", 0), ("agency", "L2A", .15), ("corporate_bond", "L2B", .5)]:
            self.assertEqual(rsf_factor(position(product, collateral_class=level))[0], expected)

    def test_rsf_long_mortgage_risk_weight(self) -> None:
        row = position("mortgage", maturity_date=AS_OF + pd.DateOffset(years=2), risk_weight=.5)
        self.assertEqual(rsf_factor(row)[0], .65)
        row.risk_weight = 1
        self.assertEqual(rsf_factor(row)[0], .85)

    def test_rsf_financial_loan(self) -> None:
        row = position("loan", counterparty_type="financial")
        self.assertEqual(rsf_factor(row)[0], .15)
        row.maturity_date = AS_OF + pd.DateOffset(months=6)
        self.assertEqual(rsf_factor(row)[0], .50)
        row.maturity_date = AS_OF + pd.DateOffset(years=1)
        self.assertEqual(rsf_factor(row)[0], 1)

    def test_encumbrance_override(self) -> None:
        row = position("agency", collateral_class="L2A", encumbered=True, encumbrance_end=AS_OF + pd.DateOffset(months=5))
        self.assertEqual(rsf_factor(row)[0], .15)
        row.encumbrance_end = AS_OF + pd.DateOffset(months=6)
        self.assertEqual(rsf_factor(row)[0], .50)
        row.encumbrance_end = AS_OF + pd.DateOffset(years=1)
        self.assertEqual(rsf_factor(row)[0], 1)

    def test_nonperforming_override(self) -> None:
        self.assertEqual(rsf_factor(position("mortgage", performing=False))[0], 1)

    def test_facility_rsf(self) -> None:
        self.assertEqual(rsf_factor(position("credit_facility", "off_balance"))[0], .05)

    def test_calendar_maturity_boundaries(self) -> None:
        self.assertEqual(maturity_term(AS_OF + pd.DateOffset(months=6) - pd.Timedelta(days=1)), "short")
        self.assertEqual(maturity_term(AS_OF + pd.DateOffset(months=6)), "medium")
        self.assertEqual(maturity_term(AS_OF + pd.DateOffset(years=1)), "long")

    def test_contributions_reconcile(self) -> None:
        result = calculate_nsfr(generate_bank())
        for name in ["ASF", "RSF"]:
            self.assertAlmostEqual(result.contributions.loc[result.contributions.measure.eq(name), "amount"].sum(), result.summary[name.lower()])
        derivative = result.contributions.loc[result.contributions["product"].eq("derivative_valuation"), "amount"].sum()
        self.assertAlmostEqual(derivative, 50)


class CollateralTests(unittest.TestCase):
    def test_hand_lendable_value(self) -> None:
        result = inventory(small_bank())
        self.assertEqual(capacity(result), 75)
        self.assertEqual(result.loc[result.position_id.eq("mortgage"), "allocated_venue"].iloc[0], "FHLB")

    def test_no_duplicate_venue_capacity(self) -> None:
        result = inventory(generate_bank())
        self.assertTrue(result.position_id.is_unique)
        self.assertLess(capacity(result), result.fhlb_alternative_value.sum() + result.discount_window_alternative_value.sum())

    def test_encumbered_assets_excluded(self) -> None:
        result = inventory(generate_bank())
        self.assertEqual(result.loc[result.encumbered, "lendable_value"].sum(), 0)

    def test_hqla_excluded_from_stress_borrowing(self) -> None:
        result = inventory(generate_bank())
        self.assertEqual(result.loc[result.collateral_class.isin(["L1", "L2A", "L2B"]), "lendable_value"].sum(), 0)

    def test_haircut_monotonicity(self) -> None:
        self.assertGreater(capacity(inventory(generate_bank(), shock=.1)), capacity(inventory(generate_bank(), shock=.2)))

    def test_shock_one_zero_capacity(self) -> None:
        self.assertEqual(capacity(inventory(generate_bank(), shock=1)), 0)

    def test_nonperforming_excluded(self) -> None:
        bank = small_bank()
        bank.loc[bank["product"].eq("mortgage"), "performing"] = False
        self.assertEqual(capacity(inventory(bank)), 0)

    def test_waterfall_conservation(self) -> None:
        result = waterfall(100, 20, 30, 10, 15)
        self.assertEqual(result.used.sum(), 75)
        self.assertEqual(result.remaining_need.iloc[-1], 25)
        np.testing.assert_allclose(result.used + result.unused, result.capacity)

    def test_waterfall_order(self) -> None:
        result = waterfall(25, 20, 30, 10, 15)
        self.assertEqual(list(result.used), [20, 5, 0, 0])

    def test_invalid_haircuts(self) -> None:
        with self.assertRaises(ValueError):
            inventory(small_bank(), haircuts={"FHLB": {"mortgage": 1.1}, "discount_window": {}})


class StressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bank = generate_bank()
        cls.results = [stress(cls.bank, scenario) for scenario in SCENARIOS]

    def test_monotone_severity_balance(self) -> None:
        for mild, severe in zip(self.results, self.results[1:]):
            self.assertTrue(np.all(mild.daily.liquidity_balance >= severe.daily.liquidity_balance - 1e-8))

    def test_monotone_survival(self) -> None:
        values = [result.summary["survival_days"] for result in self.results]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_daily_cash_reconciliation(self) -> None:
        for result in self.results:
            np.testing.assert_allclose(result.daily.liquidity_balance, result.summary["counterbalancing_capacity"]
                                       + result.daily.cumulative_inflows - result.daily.cumulative_outflows)

    def test_horizon_snapshots(self) -> None:
        for result in self.results:
            self.assertEqual(list(result.horizons.day), [30, 90, 365])
            self.assertEqual(len(result.daily), 365)

    def test_resources_reconcile(self) -> None:
        for result in self.results:
            self.assertEqual(result.resources.capacity.sum(), result.summary["counterbalancing_capacity"])

    def test_survival_definition(self) -> None:
        for result in self.results:
            survival = result.summary["survival_days"]
            self.assertTrue(result.daily.loc[result.daily.day.le(survival), "liquidity_balance"].ge(0).all())
            if not result.summary["censored"]:
                self.assertLess(result.daily.loc[result.daily.day.eq(survival + 1), "liquidity_balance"].iloc[0], 0)

    def test_deposit_runoff_bounded(self) -> None:
        deposits = self.bank.loc[self.bank["product"].eq("deposit"), "balance"].sum()
        for result in self.results:
            self.assertLessEqual(result.daily.deposit_runoff.max(), deposits + 1e-8)
            self.assertTrue(np.all(np.diff(result.daily.deposit_runoff) >= -1e-8))

    def test_zero_shock_censored(self) -> None:
        calm = Scenario("calm", 0, 1, 0, 0, 1)
        result = stress(small_bank(), calm)
        self.assertTrue(result.summary["censored"])
        self.assertEqual(result.summary["survival_days"], 365)

    def test_loan_maturity_repay_borrowing(self) -> None:
        bank = pd.DataFrame([position("mortgage", balance=100, collateral_class="mortgage", counterparty_type="retail")])
        result = stress(bank, Scenario("calm", 0, 1, 0, 0, 1), horizon=30)
        self.assertEqual(result.summary["counterbalancing_capacity"], 75)
        self.assertEqual(result.daily.net_asset_collections.iloc[-1], 25)
        self.assertEqual(result.daily.liquidity_balance.iloc[-1], 100)

    def test_clri_facility_size(self) -> None:
        contingent = clri(self.bank)
        self.assertAlmostEqual(contingent.loc[contingent.exposure_type.eq("off_balance"), "size"].sum(), 20000)
        self.assertTrue(contingent.earliest_day.le(contingent.latest_day).all())

    def test_assumptions_match_day30(self) -> None:
        assumptions = assumption_table()
        for scenario, result in zip(SCENARIOS, self.results):
            rates = assumptions.loc[assumptions.scenario.eq(scenario.name) & assumptions.horizon.eq(30)]
            self.assertTrue(rates.cumulative_runoff.between(0, 1).all())
            self.assertEqual(rates.facility_drawdown.iloc[0], scenario.drawdown)
            self.assertAlmostEqual(result.daily.facility_draws.iloc[29], 20000 * scenario.drawdown)

    def test_invalid_scenario(self) -> None:
        with self.assertRaises(ValueError):
            Scenario("invalid", 1, 1.1, .1, .2, .9)


class IntradayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payments = pd.DataFrame(dict(payment_id=[1, 2, 3, 4], minute=[480, 540, 600, 660],
                                          signed_amount=[-10., 5., -8., 20.], time_specific=[True, False, True, False],
                                          deadline=[480., np.nan, 610., np.nan]))

    def test_hand_usage(self) -> None:
        result = monitor(self.payments, 20)
        self.assertEqual(result.summary["maximum_usage"], 13)
        self.assertEqual(result.summary["maximum_positive_position"], 7)

    def test_opening_resources_do_not_change_usage(self) -> None:
        self.assertEqual(monitor(self.payments, 100).summary["maximum_usage"], monitor(self.payments, 0).summary["maximum_usage"])

    def test_source_flow_reconciliation(self) -> None:
        result = monitor(simulate_payments(), 5000)
        self.assertAlmostEqual(result.flows.net_cumulative.iloc[-1], result.summary["total_received"] - result.summary["total_sent"])
        self.assertAlmostEqual(result.summary["maximum_usage"], max(0, -result.flows.signed_amount.cumsum().min()))

    def test_available_start(self) -> None:
        result = monitor(self.payments, 5, 10, 20)
        self.assertEqual(result.summary["available_at_start"], 35)
        self.assertEqual(result.summary["resource_shortfall"], 0)

    def test_resource_shortfall(self) -> None:
        self.assertEqual(monitor(self.payments, 5).summary["resource_shortfall"], 8)

    def test_time_specific_obligations(self) -> None:
        result = monitor(self.payments, 20)
        self.assertEqual(result.summary["time_specific_obligations"], 18)
        self.assertEqual(result.summary["late_obligations"], 0)
        self.payments.loc[2, "deadline"] = 590
        self.assertEqual(monitor(self.payments, 20).summary["late_obligations"], 1)

    def test_throughput(self) -> None:
        result = monitor(self.payments, 20)
        self.assertAlmostEqual(result.throughput.throughput_fraction.iloc[0], 10 / 18)
        self.assertEqual(result.throughput.throughput_fraction.iloc[-1], 1)
        self.assertTrue(result.throughput.throughput_fraction.is_monotonic_increasing)

    def test_permutation_invariance(self) -> None:
        left = monitor(self.payments, 20)
        right = monitor(self.payments.iloc[::-1], 20)
        self.assertEqual(left.summary, right.summary)

    def test_receipt_only_zero_usage(self) -> None:
        payments = self.payments.loc[self.payments.signed_amount.gt(0)]
        self.assertEqual(monitor(payments, 0).summary["maximum_usage"], 0)

    def test_empty_flows(self) -> None:
        result = monitor(self.payments.iloc[:0], 0)
        self.assertEqual(result.summary["maximum_usage"], 0)
        self.assertEqual(result.throughput.throughput_fraction.sum(), 0)

    def test_seeded_simulation(self) -> None:
        pd.testing.assert_frame_equal(simulate_payments(), simulate_payments())

    def test_bad_payment(self) -> None:
        self.payments.loc[0, "signed_amount"] = np.nan
        with self.assertRaises(ValueError):
            monitor(self.payments, 20)


class LimitTests(unittest.TestCase):
    def test_minimum_transitions(self) -> None:
        limit = LIMITS[0]
        for value, expected in [(1.21, "green"), (1.20, "green"), (1.19, "amber"), (1.00, "amber"), (.99, "red")]:
            self.assertEqual(limit.status(value), expected)

    def test_maximum_transitions(self) -> None:
        limit = LIMITS[-1]
        for value, expected in [(.69, "green"), (.70, "green"), (.71, "amber"), (.90, "amber"), (.91, "red")]:
            self.assertEqual(limit.status(value), expected)

    def test_missing_values_breach(self) -> None:
        result = evaluate({})
        self.assertTrue(result.status.eq("red").all())
        self.assertEqual(len(breach_report(result)), 5)

    def test_breach_selection(self) -> None:
        result = evaluate({"LCR": 1.3, "NSFR": 1.2, "ILST survival days": 60,
                           "Wholesale funding concentration": .5, "Intraday usage": .5})
        self.assertEqual(set(breach_report(result).status), {"amber", "red"})
        self.assertEqual(len(breach_report(result)), 2)

    def test_wholesale_concentration_handcase(self) -> None:
        bank = small_bank()
        debt = position("debt", "liability", 50, position_id="debt")
        self.assertEqual(wholesale_concentration(pd.concat([bank, pd.DataFrame([debt])])), .25)

    def test_framework_owners_sources(self) -> None:
        result = framework()
        self.assertEqual(len(result), 5)
        self.assertTrue(result.source.str.contains("occ.gov", regex=False).all())
        self.assertTrue(result.owner.str.len().gt(0).all())

    def test_invalid_threshold_order(self) -> None:
        with self.assertRaises(ValueError):
            Limit("bad", "minimum", 1, 2, "Treasurer", "topic")

    def test_nonfinite_status(self) -> None:
        self.assertEqual(LIMITS[0].status(math.nan), "red")
        self.assertEqual(LIMITS[0].status(math.inf), "red")


if __name__ == "__main__":
    unittest.main()
