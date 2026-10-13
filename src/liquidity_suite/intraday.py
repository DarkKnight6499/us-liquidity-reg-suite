"""BCBS 248 category A tools and direct-participant throughput."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .common import SEED, nonnegative


def simulate_payments(seed: int = SEED, count: int = 1000) -> pd.DataFrame:
    """Generate synthetic settlement flows, with early outgoing payment pressure."""
    if count < 1:
        raise ValueError("Payment count must be positive")
    rng = np.random.default_rng(seed)
    direction = rng.choice([-1, 1], count)
    minutes = np.where(direction < 0, rng.integers(480, 960, count), rng.integers(540, 1081, count))
    amounts = rng.lognormal(2.0, .8, count)
    timed = (direction < 0) & (rng.random(count) < .12)
    return pd.DataFrame(dict(payment_id=np.arange(count), minute=minutes, signed_amount=direction * amounts,
                              time_specific=timed, deadline=np.where(timed, minutes + rng.integers(0, 61, count), np.nan)))


@dataclass
class IntradayResult:
    summary: dict[str, float]
    flows: pd.DataFrame
    throughput: pd.DataFrame
    obligations: pd.DataFrame


def monitor(payments: pd.DataFrame, opening_cash: float, pledged_collateral: float = 0.0,
            credit_lines: float = 0.0) -> IntradayResult:
    """Measure usage independently of opening resources, which fund the payment deficit."""
    nonnegative((opening_cash, pledged_collateral, credit_lines))
    required = {"payment_id", "minute", "signed_amount", "time_specific", "deadline"}
    if not required.issubset(payments.columns):
        raise ValueError("Missing payment fields")
    if payments.payment_id.duplicated().any() or payments[list(required - {"deadline"})].isna().any().any():
        raise ValueError("Payment fields must be complete and IDs unique")
    if not np.isfinite(payments.signed_amount).all() or not payments.minute.between(480, 1080).all():
        raise ValueError("Invalid settlement amounts or times")
    if not payments.time_specific.map(lambda x: isinstance(x, (bool, np.bool_))).all():
        raise ValueError("Time-specific flags must be boolean")
    timed = payments.loc[payments.time_specific]
    if timed.deadline.isna().any() or timed.signed_amount.ge(0).any() or not np.isfinite(timed.deadline).all():
        raise ValueError("Time-specific obligations require outgoing amounts and finite deadlines")
    # Payment IDs provide a deterministic settlement sequence for identical timestamps.
    flows = payments.sort_values(["minute", "payment_id"], kind="stable").reset_index(drop=True).copy()
    flows["net_cumulative"] = flows.signed_amount.cumsum()
    available = opening_cash + pledged_collateral + credit_lines
    flows["available_balance"] = available + flows.net_cumulative
    sent = float(-flows.loc[flows.signed_amount.lt(0), "signed_amount"].sum())
    received = float(flows.loc[flows.signed_amount.gt(0), "signed_amount"].sum())
    usage = max(0.0, -float(flows.net_cumulative.min())) if len(flows) else 0.0
    positive = max(0.0, float(flows.net_cumulative.max())) if len(flows) else 0.0
    profile = []
    for hour in range(8, 19):
        selected = flows.loc[flows.minute.le(hour * 60) & flows.signed_amount.lt(0)]
        cumulative = float(-selected.signed_amount.sum())
        profile.append((hour, cumulative, cumulative / sent if sent else 0.0))
    obligations = flows.loc[flows.time_specific].copy()
    obligations["late"] = obligations.minute.gt(obligations.deadline)
    summary = dict(maximum_usage=usage, maximum_positive_position=positive, available_at_start=available,
                   opening_cash=opening_cash, pledged_collateral=pledged_collateral, credit_lines=credit_lines,
                   total_sent=sent, total_received=received, time_specific_obligations=float(-obligations.signed_amount.sum()),
                   late_obligations=float(obligations.late.sum()), resource_shortfall=max(0.0, usage - available))
    return IntradayResult(summary, flows, pd.DataFrame(profile, columns=["hour", "cumulative_sent", "throughput_fraction"]), obligations)
