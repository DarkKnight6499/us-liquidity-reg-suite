"""Write reproducible synthetic payment-feed monitoring and stress artifacts."""

from pathlib import Path
import os
import sys

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from liquidity_suite.common import AS_OF, SEED, markdown_table
from liquidity_suite.payment_feed import FeedEvents, generate_payment_feed
from liquidity_suite.payment_stream import stress_payment_feed
from liquidity_suite.report import write_table


def run() -> pd.DataFrame:
    """Export both scenarios and optionally plot their cumulative positions."""
    output = PROJECT / "examples" / "output"
    output.mkdir(parents=True, exist_ok=True)
    feed = generate_payment_feed()
    baseline, stressed, comparison = stress_payment_feed(
        feed, counterparty="BANK_01", delay_hours=3., credit_reduction=1500.,
        reserves=1000., credit_lines=2500., collateral_capacity=500.)
    feed.to_csv(output / "payment_feed.csv", index=False, float_format="%.10f", lineterminator="\n")
    write_table(comparison, output / "payment_feed_summary")
    events = generate_payment_feed(events=FeedEvents(delayed_incoming_hours=3.,
                                  outage_counterparty="BANK_02", outage_hours=3., late_funding_squeeze=2000.))
    events.to_csv(output / "payment_feed_events.csv", index=False, float_format="%.10f", lineterminator="\n")
    for name, result in [("baseline", baseline), ("stressed", stressed)]:
        result.flows.to_csv(output / f"payment_{name}_flows.csv", index=False, float_format="%.10f", lineterminator="\n")
        for label in ("throughput", "obligations", "breaches", "deferred"):
            write_table(getattr(result, label), output / f"payment_{name}_{label}")
    chart = "Skipped: matplotlib is unavailable."
    os.environ["MPLCONFIGDIR"] = str(PROJECT / "examples" / "output" / ".matplotlib")
    try:
        import matplotlib
    except ImportError:
        pass
    else:
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        figure, axis = plt.subplots(figsize=(10, 4))
        for name, result in [("Baseline", baseline), ("Stressed", stressed)]:
            axis.plot(result.flows.timestamp, result.flows.net_cumulative, label=name)
            axis.axhline(-result.summary["available_at_start"], linestyle=":", label=f"{name} resource floor")
        axis.set(ylabel="Net cumulative position, USD millions", xlabel="Synthetic local settlement time",
                 title="Synthetic payment feed. No real payment-system connection.")
        axis.legend()
        figure.autofmt_xdate()
        figure.tight_layout()
        figure.savefig(output / "payment_feed_chart.png")
        plt.close(figure)
        chart = "Written: payment_feed_chart.png."
    notes = (f"# Synthetic payment-feed run\n\nSeed: {SEED}. Synthetic weekday: {AS_OF.date()}. "
             "All amounts are USD millions. This feed is synthetic and is not a connection to any real payment system.\n\n"
             "Stress delays BANK_01 receipts by 3 hours and reduces the opening credit line by 1,500. "
             "Opening reserves are 1,000, credit is 2,500, and distinct collateral capacity is 500.\n\n"
             "Timing mixtures, lognormal sizes, counterparties, settlement windows, netting releases, events, "
             "resource assumptions, and alert thresholds are stylized. CHIPS-like releases are messages, "
             "not a CHIPS netting algorithm. Payments are recorded despite resource deficits; no queue is simulated.\n\n"
             + markdown_table(comparison) + "\nChart: " + chart + "\n")
    (output / "payment_feed_run.md").write_text(notes, encoding="utf-8")
    return comparison


if __name__ == "__main__":
    print(markdown_table(run()))
