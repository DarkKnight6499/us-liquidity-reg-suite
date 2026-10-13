"""Independent hand cases and invariants for synthetic streaming payments."""

from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from liquidity_suite.common import AS_OF
from liquidity_suite.intraday import monitor
from liquidity_suite.payment_feed import FeedEvents, generate_payment_feed, delay_counterparty_receipts
from liquidity_suite.payment_stream import PaymentLimits, PaymentProcessor, process_payment_feed, stress_payment_feed


def message(payment_id, hour, amount, direction="outgoing", **overrides):
    row = dict(payment_id=payment_id, timestamp=AS_OF + pd.Timedelta(hours=hour), amount=amount,
               direction=direction, counterparty="BANK_01", payment_type="customer",
               correspondent_client="", time_specific=False, deadline=pd.NaT)
    row.update(overrides)
    return row


class PaymentFeedTests(unittest.TestCase):
    def test_hand_position_and_peak(self):
        rows = [message(0, 9, 100), message(1, 10, 40, "incoming"),
                message(2, 11, 80), message(3, 12, 200, "incoming")]
        processor = PaymentProcessor(70, 20, 10)
        for row, net, peak in zip(rows, [-100, -60, -140, 60], [100, 100, 140, 140]):
            processor.consume(row)
            self.assertEqual(processor.net_cumulative, net)
            self.assertEqual(processor.maximum_usage, peak)
        result = processor.finish()
        self.assertEqual(result.summary["maximum_usage"], 140)
        self.assertEqual(result.summary["available_at_start"], 100)
        self.assertEqual(result.summary["resource_shortfall"], 40)
        self.assertEqual(result.summary["total_sent"], 180)
        self.assertEqual(result.summary["total_received"], 240)
        self.assertEqual(result.summary["maximum_positive_position"], 60)

    def test_legacy_monitor_reconciliation(self):
        feed = generate_payment_feed(count=200)
        legacy = pd.DataFrame(dict(payment_id=feed.payment_id,
                              minute=(feed.timestamp - AS_OF).dt.total_seconds() / 60,
                              signed_amount=np.where(feed.direction.eq("outgoing"), -feed.amount, feed.amount),
                              time_specific=feed.time_specific,
                              deadline=(feed.deadline - AS_OF).dt.total_seconds() / 60))
        old = monitor(legacy, 1000, 500, 2000)
        new = process_payment_feed(iter(feed.to_dict("records")), 1000, 2000, 500)
        for metric in ("maximum_usage", "total_sent", "total_received", "available_at_start", "time_specific_obligations"):
            self.assertAlmostEqual(old.summary[metric], new.summary[metric])
        np.testing.assert_allclose(old.throughput.throughput_fraction, new.throughput.throughput_fraction)

    def test_ordering_rejected(self):
        with self.assertRaises(ValueError):
            process_payment_feed([message(0, 10, 1), message(1, 9, 1)], 10)

    def test_timestamp_tie_order(self):
        result = process_payment_feed([message(0, 9, 5), message(1, 9, 5, "incoming")], 10)
        self.assertEqual(result.summary["maximum_usage"], 5)
        with self.assertRaises(ValueError):
            process_payment_feed([message(1, 9, 5), message(0, 9, 5)], 10)

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            process_payment_feed([message(0, 9, 1), message(0, 10, 1)], 10)

    def test_seed_determinism(self):
        pd.testing.assert_frame_equal(generate_payment_feed(seed=1), generate_payment_feed(seed=1))
        self.assertFalse(generate_payment_feed(seed=1).equals(generate_payment_feed(seed=2)))

    def test_generated_schema_and_positive_amounts(self):
        feed = generate_payment_feed()
        self.assertTrue(feed.amount.gt(0).all())
        self.assertTrue(np.isfinite(feed.amount).all())
        self.assertEqual(set(feed.direction), {"incoming", "outgoing"})
        self.assertEqual(feed.payment_type.nunique(), 4)
        self.assertEqual(len(feed), 2000)
        self.assertEqual(feed.timestamp.min().date(), AS_OF.date())
        self.assertTrue(feed.timestamp.le(AS_OF + pd.Timedelta(hours=18)).all())
        pd.testing.assert_frame_equal(feed, feed.sort_values(["timestamp", "payment_id"]).reset_index(drop=True))

    def test_invalid_amounts(self):
        for value in (-1, np.nan, np.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                process_payment_feed([message(0, 9, value)], 10)

    def test_zero_amount_and_empty_feed(self):
        result = process_payment_feed([], 0)
        self.assertEqual(result.summary["maximum_usage"], 0)
        self.assertEqual(len(result.throughput), 11)
        self.assertIn("amount", result.deferred.columns)
        self.assertIn("covered", result.obligations.columns)
        result = process_payment_feed([message(0, 9, 0)], 0)
        self.assertTrue(result.breaches.empty)

    def test_exact_limit_boundaries_and_tiers(self):
        rows = [message(0, 9, 70), message(1, 10, 1), message(2, 11, 19),
                message(3, 12, 1), message(4, 13, 9), message(5, 14, 1)]
        result = process_payment_feed(rows, 100)
        self.assertEqual(result.breaches.severity.tolist(), ["amber", "red", "critical"])
        self.assertEqual(result.breaches.payment_id.tolist(), [1, 3, 5])
        self.assertEqual(result.summary["first_resource_breach"], AS_OF + pd.Timedelta(hours=14))

    def test_alert_reentry(self):
        rows = [message(0, 9, 80), message(1, 10, 80, "incoming"), message(2, 11, 80)]
        result = process_payment_feed(rows, 100)
        self.assertEqual(result.breaches.severity.tolist(), ["amber", "amber"])

    def test_zero_resources(self):
        result = process_payment_feed([message(0, 9, 1)], 0)
        self.assertEqual(result.breaches.severity.tolist(), ["critical"])

    def test_hour_boundary_and_lag(self):
        limits = PaymentLimits(throughput_targets={12: .5, 15: .8})
        result = process_payment_feed([message(0, 12, 50), message(1, 16, 50)], 200,
                                      expected_outgoing=100, limits=limits)
        self.assertEqual(result.breaches.rule.tolist(), ["throughput_lag"])
        self.assertEqual(result.breaches.timestamp.iloc[0], AS_OF + pd.Timedelta(hours=15))
        self.assertEqual(result.throughput.loc[result.throughput.hour.eq(12), "throughput_fraction"].iloc[0], .5)

    def test_empty_hour_lag_at_close(self):
        result = process_payment_feed([], 1, expected_outgoing=100)
        self.assertEqual(result.breaches.timestamp.dt.hour.tolist(), [12, 15, 17])

    def test_obligations_and_correspondents(self):
        rows = [message(0, 9, 20, time_specific=True, deadline=AS_OF + pd.Timedelta(hours=9), correspondent_client="CLIENT"),
                message(1, 10, 10, time_specific=True, deadline=AS_OF + pd.Timedelta(hours=9)),
                message(2, 11, 80, time_specific=True, deadline=AS_OF + pd.Timedelta(hours=12))]
        result = process_payment_feed(rows, 100)
        self.assertEqual(result.summary["time_specific_obligations"], 110)
        self.assertEqual(result.summary["covered_obligations_value"], 20)
        self.assertEqual(result.summary["uncovered_obligations"], 2)
        self.assertEqual(result.summary["late_obligations"], 1)
        self.assertEqual(result.summary["correspondent_value"], 20)

    def test_deferred_not_clipped(self):
        rows = [message(0, 9, 100), message(1, 19, 100, "incoming")]
        result = process_payment_feed(rows, 100)
        self.assertEqual(result.summary["net_cumulative"], -100)
        self.assertEqual(result.summary["deferred_value"], 100)

    def test_deferred_obligation_uncovered(self):
        result = process_payment_feed([message(0, 19, 20, time_specific=True,
                                               deadline=AS_OF + pd.Timedelta(hours=18))], 100)
        self.assertEqual(result.summary["time_specific_obligations"], 20)
        self.assertEqual(result.summary["uncovered_obligations"], 1)
        self.assertFalse(result.obligations.settled.iloc[0])

    def test_stress_hand_case(self):
        feed = pd.DataFrame([message(0, 9, 80, "incoming"), message(1, 10, 100)])
        base, stressed, comparison = stress_payment_feed(feed, "BANK_01", 3, 30, 20, 80)
        self.assertEqual(base.summary["maximum_usage"], 20)
        self.assertEqual(stressed.summary["maximum_usage"], 100)
        self.assertEqual(stressed.summary["available_at_start"], 70)
        self.assertEqual(stressed.summary["first_resource_breach"], AS_OF + pd.Timedelta(hours=10))
        self.assertEqual(comparison.peak_usage_change.tolist(), [0, 80])

    def test_stress_monotonicity_many_seeds(self):
        for seed in range(5):
            feed = generate_payment_feed(seed=seed, count=200)
            previous_peak, previous_shortfall = 0., 0.
            previous_breach = pd.NaT
            for delay, reduction in [(0, 0), (1, 100), (3, 500), (12, 1000)]:
                _, stressed, _ = stress_payment_feed(feed, "BANK_01", delay, reduction, 100, 1000)
                self.assertGreaterEqual(stressed.summary["maximum_usage"] + 1e-8, previous_peak)
                self.assertGreaterEqual(stressed.summary["resource_shortfall"] + 1e-8, previous_shortfall)
                previous_peak, previous_shortfall = stressed.summary["maximum_usage"], stressed.summary["resource_shortfall"]
                breach = stressed.summary["first_resource_breach"]
                if pd.notna(previous_breach):
                    self.assertTrue(pd.notna(breach))
                    self.assertLessEqual(breach, previous_breach)
                previous_breach = breach

    def test_credit_reduction_does_not_change_usage(self):
        feed = generate_payment_feed(count=100)
        base, stressed, _ = stress_payment_feed(feed, "BANK_01", 0, 500, 100, 1000)
        self.assertEqual(base.summary["maximum_usage"], stressed.summary["maximum_usage"])

    def test_delay_conserves_payments(self):
        feed = generate_payment_feed(count=200)
        stressed = delay_counterparty_receipts(feed, "BANK_01", 3).set_index("payment_id")
        original = feed.set_index("payment_id")
        pd.testing.assert_series_equal(original.amount.sort_index(), stressed.amount.sort_index())
        outgoing = original.direction.eq("outgoing")
        pd.testing.assert_series_equal(original.loc[outgoing, "timestamp"].sort_index(),
                                       stressed.loc[original.index[outgoing], "timestamp"].sort_index())

    def test_event_injections_deterministic(self):
        events = FeedEvents(3, "BANK_02", 12, 3, 2000)
        feed = generate_payment_feed(events=events)
        pd.testing.assert_frame_equal(feed, generate_payment_feed(events=events))
        self.assertEqual(len(feed), 2001)
        self.assertTrue(feed.event.str.contains("delayed_large_incoming").any())
        self.assertTrue(feed.event.str.contains("counterparty_outage").any())
        self.assertEqual(feed.loc[feed.event.eq("late_funding_squeeze"), "amount"].iloc[0], 2000)

    def test_invalid_settings(self):
        for kwargs in ({"count": 0}, {"count": 1.5}, {"day": "2026-10-11"},
                       {"events": FeedEvents(outage_counterparty="UNKNOWN")},
                       {"events": FeedEvents(delayed_incoming_hours=-1)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                generate_payment_feed(**kwargs)
        for kwargs in ({"amber_fraction": .9, "red_fraction": .7},
                       {"throughput_targets": {12: np.nan}}, {"throughput_targets": {12: .8, 13: .5}}):
            with self.assertRaises(ValueError):
                PaymentLimits(**kwargs)

    def test_invalid_message_fields(self):
        for overrides in ({"direction": "wrong"}, {"time_specific": "False"},
                          {"time_specific": True}, {"payment_type": "wrong"},
                          {"counterparty": ""}, {"payment_id": -1},
                          {"timestamp": pd.NaT}, {"direction": "incoming", "correspondent_client": "CLIENT"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                row = message(0, 9, 10)
                row.update(overrides)
                process_payment_feed([row], 100)

    def test_missing_fields_and_invalid_resources(self):
        with self.assertRaises(ValueError):
            process_payment_feed([{}], 100)
        with self.assertRaises(ValueError):
            PaymentProcessor(-1)
        with self.assertRaises(ValueError):
            stress_payment_feed(generate_payment_feed(count=100), "BANK_01", 1, 101, 1, 100)

    def test_finished_processor_rejects_messages(self):
        processor = PaymentProcessor(100)
        processor.finish()
        with self.assertRaises(ValueError):
            processor.consume(message(0, 9, 1))


if __name__ == "__main__":
    unittest.main()
