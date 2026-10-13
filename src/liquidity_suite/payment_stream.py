"""Streaming BCBS 248 daily measures and internal synthetic alert thresholds."""

from dataclasses import dataclass, field
from collections.abc import Iterable, Mapping

import numpy as np
import pandas as pd

from .common import AS_OF, nonnegative
from .payment_feed import PAYMENT_TYPES, delay_counterparty_receipts


@dataclass(frozen=True)
class PaymentLimits:
    """Internal boundaries, not payment-system or regulatory requirements."""

    amber_fraction: float = .70
    red_fraction: float = .90
    throughput_targets: dict[int, float] = field(default_factory=lambda: {12: .25, 15: .60, 17: .90})

    def __post_init__(self) -> None:
        if not 0 <= self.amber_fraction < self.red_fraction <= 1:
            raise ValueError("Usage thresholds must satisfy 0 <= amber < red <= 1")
        previous = 0.0
        for hour, fraction in sorted(self.throughput_targets.items()):
            if not isinstance(hour, int) or not 8 <= hour <= 18 or not np.isfinite(fraction) or not previous <= fraction <= 1:
                raise ValueError("Hourly targets must be finite, nondecreasing fractions")
            previous = fraction


@dataclass
class PaymentStreamResult:
    summary: dict
    flows: pd.DataFrame
    throughput: pd.DataFrame
    obligations: pd.DataFrame
    breaches: pd.DataFrame
    deferred: pd.DataFrame


class PaymentProcessor:
    """Consume timestamp-ordered messages and maintain state after every payment.

    Daily outgoing budget is supplied before streaming for hourly lag alerts.
    Realized BCBS throughput uses the final daily outgoing total instead.
    Payments are recorded even when resources are insufficient; this is a
    liquidity diagnostic, not a settlement or queueing engine.
    """

    def __init__(self, reserves: float, credit_lines: float = 0., collateral_capacity: float = 0.,
                 day: pd.Timestamp = AS_OF, expected_outgoing: float = 0.,
                 limits: PaymentLimits | None = None):
        nonnegative((reserves, credit_lines, collateral_capacity, expected_outgoing))
        self.day = pd.Timestamp(day).normalize()
        if pd.isna(self.day) or self.day.tz is not None or self.day.dayofweek >= 5:
            raise ValueError("A timezone-naive weekday is required")
        self.close = self.day + pd.Timedelta(hours=18)
        self.reserves, self.credit_lines, self.collateral_capacity = reserves, credit_lines, collateral_capacity
        self.available = float(reserves + credit_lines + collateral_capacity)
        self.expected_outgoing = expected_outgoing
        self.limits = limits or PaymentLimits()
        self.net_cumulative = self.maximum_usage = self.total_sent = self.total_received = 0.
        self.maximum_positive_position = 0.
        self.correspondent_value = self.covered_value = 0.
        self._flows, self._obligations, self._breaches, self._deferred, self._hours = [], [], [], [], []
        self._ids, self._last_key, self._severity = set(), None, 0
        self._next_hour, self._finished = 8, False

    def _advance_hours(self, timestamp: pd.Timestamp, inclusive: bool = False) -> None:
        while self._next_hour <= 18:
            checkpoint = self.day + pd.Timedelta(hours=self._next_hour)
            if checkpoint > timestamp or (checkpoint == timestamp and not inclusive):
                break
            fraction = self.total_sent / self.expected_outgoing if self.expected_outgoing else 0.
            self._hours.append(dict(hour=self._next_hour, timestamp=checkpoint, cumulative_sent=self.total_sent,
                                    budget_fraction=fraction))
            target = self.limits.throughput_targets.get(self._next_hour)
            if target is not None and self.expected_outgoing and fraction < target:
                self._breaches.append(dict(timestamp=checkpoint, payment_id=None, rule="throughput_lag",
                                           severity="amber", observed=fraction, threshold=target))
            self._next_hour += 1

    def consume(self, message: Mapping) -> None:
        """Reject unordered or malformed messages before changing processor state."""
        if self._finished:
            raise ValueError("Processor is already finalized")
        required = {"payment_id", "timestamp", "direction", "amount", "counterparty", "payment_type",
                    "correspondent_client", "time_specific", "deadline"}
        if not required.issubset(message):
            raise ValueError("Missing message fields")
        row = dict(message)
        payment_id = row["payment_id"]
        if not isinstance(payment_id, (int, np.integer)) or isinstance(payment_id, bool) or payment_id < 0:
            raise ValueError("Payment IDs must be nonnegative integers")
        timestamp = pd.Timestamp(row["timestamp"])
        if pd.isna(timestamp) or timestamp.tz is not None or timestamp < self.day + pd.Timedelta(hours=8):
            raise ValueError("Invalid payment timestamp")
        key = (timestamp, payment_id)
        if payment_id in self._ids or (self._last_key is not None and key <= self._last_key):
            raise ValueError("Messages must have unique IDs and timestamp then ID ordering")
        nonnegative((row["amount"],))
        if row["direction"] not in {"outgoing", "incoming"} or row["payment_type"] not in PAYMENT_TYPES:
            raise ValueError("Invalid payment direction or type")
        if not isinstance(row["counterparty"], str) or not row["counterparty"] or not isinstance(row["correspondent_client"], str):
            raise ValueError("Counterparty and correspondent client must be strings")
        if not isinstance(row["time_specific"], (bool, np.bool_)):
            raise ValueError("Time-specific flags must be boolean")
        deadline = pd.Timestamp(row["deadline"])
        if row["time_specific"] and (row["direction"] != "outgoing" or pd.isna(deadline) or
                                     deadline.tz is not None or not self.day + pd.Timedelta(hours=8) <= deadline <= self.close):
            raise ValueError("Obligations need an outgoing payment and an in-day deadline")
        if row["correspondent_client"] and row["direction"] != "outgoing":
            raise ValueError("Correspondent payment value counts outgoing payments only")
        row.update(timestamp=timestamp, deadline=deadline, amount=float(row["amount"]))
        self._advance_hours(min(timestamp, self.close))
        self._ids.add(payment_id)
        self._last_key = key
        if timestamp > self.close:
            self._deferred.append(row)
            if row["time_specific"]:
                self._obligations.append(dict(**row, late=True, funded=False, covered=False, settled=False))
            return
        signed = row["amount"] * (-1 if row["direction"] == "outgoing" else 1)
        self.net_cumulative += signed
        self.maximum_positive_position = max(self.maximum_positive_position, self.net_cumulative)
        usage = max(0., -self.net_cumulative)
        self.maximum_usage = max(self.maximum_usage, usage)
        balance = self.available + self.net_cumulative
        if signed < 0:
            self.total_sent -= signed
            if row["correspondent_client"]:
                self.correspondent_value -= signed
        else:
            self.total_received += signed
        if row["time_specific"]:
            covered = timestamp <= deadline and balance >= 0
            self._obligations.append(dict(**row, late=timestamp > deadline, funded=balance >= 0,
                                          covered=covered, settled=True))
            if covered:
                self.covered_value += row["amount"]
        fraction = usage / self.available if self.available else (np.inf if usage else 0.)
        severity = (3 if usage > self.available else 2 if fraction > self.limits.red_fraction
                    else 1 if fraction > self.limits.amber_fraction else 0)
        if severity > self._severity:
            threshold = [0., self.limits.amber_fraction, self.limits.red_fraction, 1.][severity]
            self._breaches.append(dict(timestamp=timestamp, payment_id=payment_id, rule="liquidity_usage",
                                       severity=["green", "amber", "red", "critical"][severity],
                                       observed=fraction, threshold=threshold))
        self._severity = severity
        self._flows.append(dict(**row, signed_amount=signed, net_cumulative=self.net_cumulative,
                                current_usage=usage, peak_usage=self.maximum_usage,
                                available_liquidity=self.available, available_balance=balance,
                                covered_obligations_value=self.covered_value,
                                correspondent_value=self.correspondent_value))

    def finish(self) -> PaymentStreamResult:
        """Close the synthetic day, including empty hours and deferred obligations."""
        self._advance_hours(self.close, inclusive=True)
        self._finished = True
        throughput = pd.DataFrame(self._hours)
        throughput["throughput_fraction"] = throughput.cumulative_sent / self.total_sent if self.total_sent else 0.
        breaches = pd.DataFrame(self._breaches, columns=["timestamp", "payment_id", "rule", "severity", "observed", "threshold"])
        breaches = breaches.sort_values("timestamp", kind="stable").reset_index(drop=True)
        usage_breaches = breaches.loc[breaches.rule.eq("liquidity_usage")]
        critical = usage_breaches.loc[usage_breaches.severity.eq("critical")]
        message_columns = ["payment_id", "timestamp", "direction", "amount", "counterparty", "payment_type",
                           "correspondent_client", "time_specific", "deadline", "event"]
        obligations = pd.DataFrame(self._obligations).reindex(columns=message_columns +
                                                            ["late", "funded", "covered", "settled"])
        summary = dict(maximum_usage=self.maximum_usage, available_at_start=self.available,
                       maximum_positive_position=self.maximum_positive_position,
                       reserves=self.reserves, credit_lines=self.credit_lines, collateral_capacity=self.collateral_capacity,
                       total_sent=self.total_sent, total_received=self.total_received, net_cumulative=self.net_cumulative,
                       total_payments=self.total_sent + self.total_received, payment_count=len(self._flows),
                       time_specific_obligations=sum(r["amount"] for r in self._obligations),
                       covered_obligations_value=self.covered_value,
                       late_obligations=sum(r["late"] for r in self._obligations),
                       uncovered_obligations=sum(not r["covered"] for r in self._obligations),
                       correspondent_value=self.correspondent_value, resource_shortfall=max(0., self.maximum_usage - self.available),
                       deferred_count=len(self._deferred), deferred_value=sum(r["amount"] for r in self._deferred),
                       breach_count=len(breaches),
                       first_usage_alert=usage_breaches.timestamp.min(), first_resource_breach=critical.timestamp.min())
        flow_columns = message_columns + ["signed_amount", "net_cumulative", "current_usage", "peak_usage",
                                          "available_liquidity", "available_balance", "covered_obligations_value",
                                          "correspondent_value"]
        return PaymentStreamResult(summary, pd.DataFrame(self._flows).reindex(columns=flow_columns),
                                   throughput, obligations, breaches,
                                   pd.DataFrame(self._deferred).reindex(columns=message_columns))


def process_payment_feed(messages: Iterable[Mapping], reserves: float, credit_lines: float = 0.,
                         collateral_capacity: float = 0., day: pd.Timestamp = AS_OF,
                         expected_outgoing: float = 0., limits: PaymentLimits | None = None) -> PaymentStreamResult:
    """Consume an iterable once without sorting or looking ahead."""
    processor = PaymentProcessor(reserves, credit_lines, collateral_capacity, day, expected_outgoing, limits)
    for message in messages:
        processor.consume(message)
    return processor.finish()


def stress_payment_feed(feed: pd.DataFrame, counterparty: str, delay_hours: float,
                        credit_reduction: float, reserves: float, credit_lines: float,
                        collateral_capacity: float = 0., day: pd.Timestamp = AS_OF,
                        limits: PaymentLimits | None = None) -> tuple[PaymentStreamResult, PaymentStreamResult, pd.DataFrame]:
    """Compare identical payments with delayed receipts and reduced credit capacity."""
    nonnegative((credit_reduction, credit_lines))
    if credit_reduction > credit_lines:
        raise ValueError("Credit reduction cannot exceed the opening credit line")
    stressed_feed = delay_counterparty_receipts(feed, counterparty, delay_hours)
    budget = float(feed.loc[feed.direction.eq("outgoing") & feed.timestamp.le(pd.Timestamp(day).normalize() + pd.Timedelta(hours=18)), "amount"].sum())
    baseline = process_payment_feed(feed.to_dict("records"), reserves, credit_lines, collateral_capacity, day, budget, limits)
    stressed = process_payment_feed(stressed_feed.to_dict("records"), reserves, credit_lines - credit_reduction,
                                    collateral_capacity, day, budget, limits)
    comparison = pd.DataFrame([dict(scenario=name, **result.summary) for name, result in
                               [("baseline", baseline), ("stressed", stressed)]])
    comparison["peak_usage_change"] = comparison.maximum_usage - baseline.summary["maximum_usage"]
    return baseline, stressed, comparison
