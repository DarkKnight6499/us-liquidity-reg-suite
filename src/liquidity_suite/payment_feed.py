"""Offline synthetic payment messages, separate from settlement monitoring.

Amounts are USD millions. System labels describe styles, not real connections.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .common import AS_OF, SEED, nonnegative

PAYMENT_TYPES = ("customer", "bank_to_bank", "securities_settlement", "chips_netting_release")
COUNTERPARTIES = tuple(f"BANK_{i:02d}" for i in range(1, 9))


@dataclass(frozen=True)
class FeedEvents:
    """Optional stylized shocks; outage pauses both directions until recovery."""

    delayed_incoming_hours: float = 0.0
    outage_counterparty: str | None = None
    outage_start_hour: float = 12.0
    outage_hours: float = 0.0
    late_funding_squeeze: float = 0.0


def generate_payment_feed(seed: int = SEED, count: int = 2000,
                          day: pd.Timestamp = AS_OF,
                          events: FeedEvents | None = None) -> pd.DataFrame:
    """Generate a sorted one-day feed with lognormal sizes and timing mixtures.

    Delays may move messages beyond close. Such messages remain in the feed for
    audit but are deferred by the one-day processor. Weekends are rejected.
    """
    day = pd.Timestamp(day).normalize()
    if pd.isna(day) or day.tz is not None or day.dayofweek >= 5:
        raise ValueError("A timezone-naive weekday is required")
    if not isinstance(count, (int, np.integer)) or isinstance(count, bool) or count < 1:
        raise ValueError("Payment count must be a positive integer")
    events = events or FeedEvents()
    nonnegative((events.delayed_incoming_hours, events.outage_hours, events.late_funding_squeeze))
    if not np.isfinite(events.outage_start_hour) or not 8 <= events.outage_start_hour <= 18:
        raise ValueError("Outage start must be inside the synthetic day")
    if events.outage_counterparty is not None and events.outage_counterparty not in COUNTERPARTIES:
        raise ValueError("Unknown outage counterparty")
    rng = np.random.default_rng(seed)
    types = rng.choice(PAYMENT_TYPES, count, p=[.50, .28, .17, .05])
    direction = rng.choice(["outgoing", "incoming"], count)
    # Low morning activity, concentrated midday activity, and late settlement.
    segment = rng.choice(3, count, p=[.12, .58, .30])
    minutes = np.array([rng.integers(a, b) for a, b in
                        [(480, 660) if s == 0 else (660, 900) if s == 1 else (900, 1081)
                         for s in segment]])
    securities = types == "securities_settlement"
    chips = types == "chips_netting_release"
    minutes[securities] = rng.integers(900, 1051, securities.sum())
    minutes[chips] = rng.choice([780, 900, 1020], chips.sum())
    scales = np.select([securities, chips, types == "bank_to_bank"], [4., 8., 2.], default=1.)
    amounts = rng.lognormal(1.5, 1.4, count) * scales
    timed = (direction == "outgoing") & (securities | chips | (rng.random(count) < .08))
    timestamps = day + pd.to_timedelta(minutes, unit="m")
    deadlines = pd.Series(pd.NaT, index=range(count), dtype="datetime64[ns]")
    deadlines.loc[timed] = timestamps[timed] + pd.to_timedelta(rng.integers(0, 31, timed.sum()), unit="m")
    deadlines = deadlines.clip(upper=day + pd.Timedelta(hours=18))
    feed = pd.DataFrame(dict(payment_id=np.arange(count), timestamp=timestamps,
                             direction=direction, amount=amounts,
                             counterparty=rng.choice(COUNTERPARTIES, count), payment_type=types,
                             correspondent_client=np.where((direction == "outgoing") & (rng.random(count) < .20),
                                                           "CLIENT_01", ""),
                             time_specific=timed, deadline=deadlines, event=""))
    incoming = feed.loc[feed.direction.eq("incoming")]
    if events.delayed_incoming_hours and not incoming.empty:
        index = incoming.amount.idxmax()
        feed.loc[index, "timestamp"] += pd.Timedelta(hours=events.delayed_incoming_hours)
        feed.loc[index, "event"] = "delayed_large_incoming"
    if events.outage_counterparty is not None and events.outage_hours:
        start = day + pd.Timedelta(hours=events.outage_start_hour)
        end = start + pd.Timedelta(hours=events.outage_hours)
        affected = feed.counterparty.eq(events.outage_counterparty) & feed.timestamp.ge(start) & feed.timestamp.lt(end)
        feed.loc[affected, "timestamp"] = end
        feed.loc[affected, "event"] += ";counterparty_outage"
    if events.late_funding_squeeze:
        extra = dict(payment_id=count, timestamp=day + pd.Timedelta(hours=17, minutes=30),
                     direction="outgoing", amount=events.late_funding_squeeze, counterparty="BANK_01",
                     payment_type="bank_to_bank", correspondent_client="", time_specific=True,
                     deadline=day + pd.Timedelta(hours=17, minutes=30), event="late_funding_squeeze")
        feed = pd.concat([feed, pd.DataFrame([extra])], ignore_index=True)
    return feed.sort_values(["timestamp", "payment_id"], kind="stable").reset_index(drop=True)


def delay_counterparty_receipts(feed: pd.DataFrame, counterparty: str,
                                delay_hours: float) -> pd.DataFrame:
    """Delay receipts only, preserving amounts, IDs, deadlines, and outgoing times."""
    nonnegative((delay_hours,))
    if counterparty not in set(feed.counterparty):
        raise ValueError("Counterparty is absent from the feed")
    stressed = feed.copy(deep=True)
    if "event" not in stressed:
        stressed["event"] = ""
    affected = stressed.counterparty.eq(counterparty) & stressed.direction.eq("incoming")
    stressed.loc[affected, "timestamp"] += pd.Timedelta(hours=delay_hours)
    stressed.loc[affected, "event"] += ";receipt_delay"
    return stressed.sort_values(["timestamp", "payment_id"], kind="stable").reset_index(drop=True)
