"""Generate reviewable Markdown and CSV artifacts from model results."""

from pathlib import Path
import json

import pandas as pd

from .collateral import capacity, inventory
from .common import AS_OF, SEED, markdown_table
from .data import contractual_cashflows, generate_bank
from .fr2052a import bucket_totals, transform, validate_positions, validate_tables
from .ilst import SCENARIOS, assumption_table, clri, stress
from .intraday import monitor, simulate_payments
from .lcr import calculate_lcr
from .limits import breach_report, evaluate, framework, wholesale_concentration
from .nsfr import calculate_nsfr


def write_table(frame: pd.DataFrame, path: Path) -> None:
    """Write inspectable numeric data and a matching plain Markdown table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path.with_suffix(".csv"), index=False, float_format="%.10f", lineterminator="\n")
    path.with_suffix(".md").write_text(markdown_table(frame), encoding="utf-8")


def run_suite(project: Path) -> pd.DataFrame:
    """Run all engines offline and write a synthetic ILAAP-style assessment."""
    output = project / "examples" / "output"
    output.mkdir(parents=True, exist_ok=True)
    docs = project / "docs"
    docs.mkdir(exist_ok=True)
    positions = generate_bank()
    tables = transform(positions)
    lcr = calculate_lcr(positions)
    nsfr = calculate_nsfr(positions)
    stresses = [stress(positions, scenario) for scenario in SCENARIOS]
    intraday = monitor(simulate_payments(), opening_cash=12000)
    collateral = inventory(positions)
    limits = evaluate({"LCR": lcr.summary["lcr"], "NSFR": nsfr.summary["nsfr"],
                       "ILST survival days": min(float(result.summary["survival_days"]) for result in stresses),
                       "Wholesale funding concentration": wholesale_concentration(positions),
                       "Intraday usage": intraday.summary["maximum_usage"] / intraday.summary["available_at_start"]})
    positions.to_csv(output / "positions.csv", index=False, float_format="%.10f", lineterminator="\n")
    write_table(contractual_cashflows(positions), output / "contractual_cashflows")
    for key, table in tables.items():
        table.to_csv(output / f"fr2052a_{key.replace('.', '_')}.csv", index=False, float_format="%.10f", lineterminator="\n")
    source_exceptions = validate_positions(positions)
    table_exceptions = validate_tables(positions, tables)
    write_table(pd.concat([source_exceptions, table_exceptions]), output / "data_quality_exceptions")
    write_table(bucket_totals(tables), output / "fr2052a_bucket_totals")
    write_table(lcr.contributions, output / "lcr_contributions")
    write_table(lcr.unwind, output / "lcr_unwind")
    write_table(lcr.daily_mismatch, output / "lcr_maturity_mismatch")
    write_table(pd.DataFrame(lcr.summary.items(), columns=["metric", "value"]), output / "lcr_summary")
    write_table(nsfr.contributions, output / "nsfr_contributions")
    write_table(pd.DataFrame(nsfr.summary.items(), columns=["metric", "value"]), output / "nsfr_summary")
    stress_summary = pd.DataFrame([result.summary for result in stresses])
    stress_horizons = pd.concat([result.horizons for result in stresses], ignore_index=True)
    write_table(stress_summary, output / "stress_summary")
    write_table(stress_horizons, output / "stress_horizons")
    write_table(assumption_table(), output / "stress_assumptions")
    write_table(clri(positions), output / "clri")
    for result in stresses:
        name = str(result.summary["scenario"])
        write_table(result.daily, output / f"stress_daily_{name}")
        write_table(result.resources, output / f"stress_resources_{name}")
        write_table(result.usage_waterfall, output / f"stress_waterfall_{name}")
    write_table(collateral, output / "collateral_inventory")
    write_table(intraday.flows, output / "intraday_flows")
    write_table(intraday.throughput, output / "intraday_throughput")
    write_table(intraday.obligations, output / "intraday_obligations")
    write_table(pd.DataFrame(intraday.summary.items(), columns=["metric", "value"]), output / "intraday_summary")
    write_table(framework(), output / "limit_framework")
    write_table(limits, output / "limit_status")
    write_table(breach_report(limits), output / "limit_breaches")
    defective = positions.copy()
    defective.loc[0, "balance"] = -1
    defective.loc[1, "counterparty_type"] = "UNKNOWN"
    defective.loc[2, "counterparty_id"] = None
    write_table(validate_positions(defective), output / "injected_defect_exceptions")
    metrics = dict(assets_usd_millions=float(positions.loc[positions.side.eq("asset"), "balance"].sum()),
                   position_count=float(len(positions)), lcr_percent=lcr.summary["lcr"] * 100,
                   nsfr_percent=nsfr.summary["nsfr"] * 100, hqla_usd_millions=lcr.summary["hqla"],
                   net_outflows_usd_millions=lcr.summary["net_outflows"], asf_usd_millions=nsfr.summary["asf"],
                   rsf_usd_millions=nsfr.summary["rsf"], collateral_capacity_usd_millions=capacity(collateral),
                   combined_survival_days=float(stresses[-1].summary["survival_days"]),
                   combined_shortfall_usd_millions=float(stresses[-1].summary["maximum_shortfall"]),
                   intraday_usage_usd_millions=intraday.summary["maximum_usage"],
                   wholesale_concentration_percent=wholesale_concentration(positions) * 100,
                   data_quality_exceptions=float(len(source_exceptions) + len(table_exceptions)),
                   limit_breaches=float(len(breach_report(limits))))
    validation = pd.DataFrame(metrics.items(), columns=["metric", "value"])
    write_table(validation, output / "validation_results")
    combined = stresses[-1]
    conclusion = ("The synthetic bank does not meet the internal long-horizon adequacy target. "
                  "The combined scenario exhausts liquidity before the survival appetite threshold. "
                  "Wholesale concentration also exceeds internal appetite. "
                  "Regulatory-style ratios alone do not establish internal liquidity adequacy.")
    report = f"""# Synthetic ILAAP-style liquidity assessment

This is a model-generated internal assessment structure, not a US regulatory filing or an assertion that US banks must prepare ILAAP. Amounts are USD millions. The calculation date is {AS_OF.date()}. All inputs are synthetic.

## Governance

The proposed board risk appetite is implemented through the limit framework. Treasury owns funding execution; independent Risk challenges assumptions; ALCO reviews amber exceptions and immediately escalates red exceptions. This is a proposed governance design, not evidence of actual approvals or controls.

## Risk identification

The balance sheet includes {len(positions)} synthetic position pools and {metrics['assets_usd_millions']:,.6f} of assets. Deposit withdrawal, wholesale rollover, collateral accessibility, committed drawdowns, derivative margin, and payment timing form the risk inventory. The CLRI output retains source IDs, triggers, exposure sizes, and timing. Exposures are alternative risk channels and must not be summed as a second set of stress outflows.

## Measurement

The LCR is {metrics['lcr_percent']:.6f}% with HQLA of {metrics['hqla_usd_millions']:,.6f} and net outflows of {metrics['net_outflows_usd_millions']:,.6f}. The NSFR is {metrics['nsfr_percent']:.6f}%, with ASF of {metrics['asf_usd_millions']:,.6f} and RSF of {metrics['rsf_usd_millions']:,.6f}. Source and reporting checks produce {int(metrics['data_quality_exceptions'])} exceptions. See methodology for verified CFR references, assumptions, and omitted cases.

## Stress results

Survival is the last fully funded calendar day before the first negative balance. Censored survival means the scenario remains funded through the simulation endpoint; it is not an estimate of ultimate survival.

{markdown_table(stress_summary)}
### Horizon snapshots

{markdown_table(stress_horizons[['scenario', 'day', 'net_need', 'liquidity_balance']])}
## Contingency funding

The plan uses cash, securities monetization, FHLB allocation, and discount window allocation in that order. Baseline borrowing capacity excluding HQLA is {metrics['collateral_capacity_usd_millions']:,.6f}. Haircuts, eligibility, access, and immediate execution are stylized/unverified. Venue alternatives are mutually exclusive. Maturing loans repay the advance assumed against them, preventing reuse of principal. Combined-stress capacity is {float(combined.summary['counterbalancing_capacity']):,.6f} and the peak shortfall is {metrics['combined_shortfall_usd_millions']:,.6f}. Proposed actions are to reduce wholesale dependence, increase available liquid assets, and test collateral mobilization and funding access.

## Intraday liquidity

Daily maximum usage is {metrics['intraday_usage_usd_millions']:,.6f}; opening resources are {intraday.summary['available_at_start']:,.6f}. Total payments sent are {intraday.summary['total_sent']:,.6f} and received are {intraday.summary['total_received']:,.6f}. This single-day simulation does not provide monthly monitoring statistics.

## Limits

{markdown_table(limits[['kri', 'value', 'status', 'owner', 'escalation']])}
## Conclusion on adequacy

{conclusion}

The conclusion is conditional on the synthetic balance sheet, deterministic scenario coefficients, immediate funding access, and the selected regulatory universe. No actual institution's adequacy or compliance is assessed.
"""
    (docs / "ilaap_report.md").write_text(report, encoding="utf-8")
    manifest = dict(data_status="synthetic", seed=SEED, as_of=str(AS_OF.date()),
                    monetary_unit="USD millions", runtime_network_access=False,
                    collateral_parameter_status="stylized/unverified")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return validation
