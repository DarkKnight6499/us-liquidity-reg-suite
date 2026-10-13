# us-liquidity-reg-suite

A standalone Python library for synthetic US bank liquidity measurement, reporting, stress testing, collateral capacity, intraday monitoring, and internal limits. It connects granular position pools to traceable contributions and a generated internal liquidity assessment. All data are synthetic. Runtime processing is offline.

The example bank has **$120.000000 billion of assets**, represented by **912 synthetic position pools**. Deposit pools represent homogeneous groups of accounts, not individual insured accounts. Insurance, relationships, operational status, security qualification, and risk weights are assumed input classifications.

## What it produces

The package provides:

* FR 2052a-style partitions, selected product IDs, local counterparty codes and maturity buckets, source reconciliation, and data-quality exception reports.
* LCR contributions, haircut-adjusted HQLA, current and post-unwind caps, capped inflows, and a daily maturity mismatch calculation.
* NSFR ASF and RSF contributions, calendar maturity boundaries, encumbrance overrides, and a separate derivative valuation contribution.
* Internal idiosyncratic, market-wide, and combined stress paths, horizon snapshots, survival estimates, and a contingent liquidity risk inventory.
* Parameterized FHLB and discount window collateral tags, exclusive venue allocation, borrowing capacity, and stress resource waterfalls.
* Seeded synthetic payment messages, streaming intraday positions, peak liquidity usage, opening resources, correspondent payments, time-specific obligations, hourly throughput, timestamped alerts, and receipt-delay stress.
* Treasury risk appetite tiers, owners, escalation routes, OCC topic mappings, and a breach report.

Outputs are CSV and Markdown tables under `examples/output/`. The complete example also writes [docs/ilaap_report.md](docs/ilaap_report.md), an ILAAP-style internal narrative generated from actual model outputs.

## Run

The library requires Python and only NumPy and pandas at runtime. Scripts import the source tree directly, so installation is optional.

```powershell
python examples/run_suite.py
python examples/stress_sensitivity.py
python examples/intraday_payment_feed.py
python -m unittest discover -s tests -v
```

For use as an installed library in an environment with packaging tools:

```powershell
python -m pip install -e .
```

```python
from liquidity_suite import generate_bank, calculate_lcr, calculate_nsfr

positions = generate_bank()
lcr = calculate_lcr(positions)
nsfr = calculate_nsfr(positions)
print(lcr.summary)
print(nsfr.summary)
```

The CI workflow runs the unittest suite and the complete example on its configured Python matrix. Local validation used the supplied interpreter; the CI matrix has not been executed in this sandbox.

## Methodology

Positions retain IDs, products, counterparties, maturity dates, currencies, collateral classes, encumbrance dates, and deposit flags. Seeded Dirichlet allocations preserve balance-sheet totals. Contractual flows contain principal only. Reporting tables retain source lineage and unweighted balances. Regulatory engines produce separate weighted contributions, avoiding confusion between contractual amounts and regulatory requirements.

LCR uses the verified US haircuts and rounded cap coefficients. The linked repo unwind returns pledged securities and deducts cash repayment before testing adjusted cap excess. The larger current or adjusted cap excess is deducted from current HQLA. Supported cash-flow rates, the inflow ceiling, and the maturity mismatch add-on are applied separately. This is full calibration for the synthetic universe; synthetic asset size does not establish regulatory applicability or tailoring. [CFR HQLA rules](https://www.law.cornell.edu/cfr/text/12/249.21), [outflow rules](https://www.law.cornell.edu/cfr/text/12/249.32), [inflow rules](https://www.law.cornell.edu/cfr/text/12/249.33), [net outflow rules](https://www.law.cornell.edu/cfr/text/12/249.30).

NSFR assigns verified category factors to liabilities, capital, assets, and undrawn facilities, with calendar maturity and encumbrance adjustments. Derivative treatment is limited to the synthetic uncollateralized liability case. [ASF rules](https://www.law.cornell.edu/cfr/text/12/249.104), [RSF rules](https://www.law.cornell.edu/cfr/text/12/249.106), [derivative rules](https://www.law.cornell.edu/cfr/text/12/249.107).

Internal stress uses explicit cumulative runoff, rollover, drawdown, haircut, and collection assumptions. Free securities are sold once; collateral borrowing excludes those securities. Each collateral asset has one allocated venue. Loan maturities repay borrowing already counted as capacity. Survival ends at the first negative daily balance; funded endpoints are reported as censored.

The reporting names and selected product IDs were checked against the [Federal Reserve instructions](https://www.federalreserve.gov/apps/reportingforms/Download/DownloadAttachment?guid=ec24a96e-e47b-490c-b4b0-cf88e22a9ee2). Intraday definitions follow the requested category A tools and direct-participant throughput in [BCBS monitoring tools](https://www.bis.org/publications/201304-standards-monitoring-tools-intraday-liquidity-management.pdf). KRI topic names were checked against the [OCC Liquidity booklet](https://www.occ.gov/publications-and-resources/publications/comptrollers-handbook/files/liquidity/pub-ch-liquidity.pdf).

Full formulas, paragraph references, qualification assumptions, verification notes, and supported boundaries are in [docs/methodology.md](docs/methodology.md).

## Validation and results

The full local unittest run passed **148 tests**, including **26 payment-feed tests**. Tests cover independent hand cases, binding HQLA caps, inflow cap behavior, maturity boundaries, scale invariance, bucket reconciliation, injected source and reporting defects, stress monotonicity, collateral conservation, payment-flow reconciliation, stream ordering, seed determinism, deferred messages, obligations, hourly alerts, and exact limit transitions.

Actual complete-example outputs, monetary amounts in USD millions:

| Metric | Computed result |
| :-: | :-: |
| Assets | 120,000.000000 |
| HQLA | 33,100.000000 |
| LCR net outflows | 21,466.022557 |
| LCR | 154.197173% |
| Available stable funding | 77,450.261669 |
| Required stable funding | 48,428.439037 |
| NSFR | 159.927231% |
| Baseline collateral capacity excluding HQLA | 41,700.000000 |
| Intraday maximum usage | 2,230.807554 |
| Wholesale funding share of liabilities | 48.181818% |
| Source and reporting data-quality exceptions | 0 |
| Internal amber or red limit exceptions | 2 |

Actual stress outputs:

| Scenario | Starting capacity, USD millions | Survival days | Censored | Peak shortfall, USD millions |
| :-: | :-: | :-: | :-: | :-: |
| Idiosyncratic | 70,550.000000 | 365 | Yes | 0.000000 |
| Market-wide | 62,050.000000 | 365 | Yes | 0.000000 |
| Combined | 53,550.000000 | 64 | No | 12,742.442552 |

The combined survival result is amber against internal appetite. Wholesale funding concentration is red. The synthetic bank therefore does not meet the internal long-horizon adequacy target even though its regulatory-style ratios exceed their modeled appetite thresholds. These are model conclusions, not assessments of an actual institution.

The sensitivity example independently varies combined stress severity. Actual results:

| Shock multiplier | Survival days | Censored | Peak shortfall, USD millions |
| :-: | :-: | :-: | :-: |
| 0.500000 | 365 | Yes | 0.000000 |
| 0.750000 | 365 | Yes | 0.000000 |
| 1.000000 | 64 | No | 12,742.442552 |
| 1.250000 | 24 | No | 27,389.715649 |
| 1.500000 | 19 | No | 39,468.406928 |

The tables above are transcribed from [validation results](examples/output/validation_results.csv), [stress results](examples/output/stress_summary.csv), and [stress sensitivity](examples/output/stress_sensitivity.csv). Re-run the examples to reproduce them. The output manifest records the seed, calculation date, monetary units, and synthetic status.

## Synthetic payment-feed simulator

`payment_feed.generate_payment_feed` creates Fedwire Funds Service style messages for a synthetic weekday. This feed is synthetic and is not a connection to Fedwire, CHIPS, or any real payment system. Customer, bank-to-bank, securities settlement, and CHIPS-like netting release messages carry timestamps, positive amounts, counterparties, deadlines, and correspondent-client labels. `FeedEvents` optionally delays the largest incoming payment, pauses a counterparty during an outage, or injects a late funding payment.

`PaymentProcessor.consume` accepts messages one at a time. `process_payment_feed` consumes an iterable once, rejecting timestamp disorder and duplicate IDs. Ties require ascending payment IDs. Resources equal distinct reserves, intraday credit lines, and collateral capacity. Usage excludes opening resources. Hourly throughput uses realized outgoing value; lag alerts use a separately supplied daily outgoing budget. Internal alerts start strictly above 70% usage for amber, 90% for red, and 100% for critical. Lag targets are 25% by noon, 60% by 15:00, and 90% by 17:00. These are configurable model choices.

```python
from liquidity_suite import generate_payment_feed, process_payment_feed

feed = generate_payment_feed()
budget = float(feed.loc[feed.direction.eq("outgoing"), "amount"].sum())
result = process_payment_feed(
    iter(feed.to_dict("records")), reserves=1000, credit_lines=2500,
    collateral_capacity=500, expected_outgoing=budget,
)
print(result.summary)
```

Actual example run: seed 2052, synthetic date 2026-09-30, 2,000 baseline messages. Stress delays BANK_01 receipts by 3 hours and reduces credit by 1,500 USD millions. Monetary results below are USD millions, transcribed from [payment-feed summary](examples/output/payment_feed_summary.csv).

| Metric | Baseline | Stressed |
| :-: | :-: | :-: |
| Peak usage | 1,955.196066 | 3,619.397544 |
| Available opening liquidity | 4,000.000000 | 2,500.000000 |
| Peak resource shortfall | 0.000000 | 1,119.397544 |
| Outgoing value | 27,806.755700 | 27,806.755700 |
| Incoming value settled by close | 27,414.299422 | 24,772.423219 |
| Correspondent payment value | 4,989.563143 | 4,989.563143 |
| Time-specific obligation value | 15,506.573902 | 15,506.573902 |
| Obligations covered on time within resources | 15,506.573902 | 12,552.133634 |
| Uncovered obligation count | 0 | 52 |
| Messages deferred beyond close | 0 | 53 |
| Deferred value | 0.000000 | 2,641.876203 |
| Alert log entries, including throughput | 3 | 25 |
| First usage alert | None | 12:51 |
| First resource breach | None | 15:00 |

Stress increases peak usage by 1,664.201478 USD millions. All baseline alerts concern throughput lag. The example exports messages, optional event messages, cumulative positions, obligations, deferred messages, hourly throughput, breaches, and comparison tables to `examples/output/`. [Run notes](examples/output/payment_feed_run.md) record the inputs and chart status. Matplotlib was unavailable in the actual run, so the optional chart was skipped.

Timing profiles, heavy-tailed sizes, netting release times, counterparties, events, resources, and thresholds are stylized. The synthetic window is 08:00 to 18:00 without a holiday calendar or real service cutoffs. CHIPS-like releases do not implement CHIPS netting. Messages after close remain auditable but do not affect that day's settlement balance. Payments remain recorded during resource deficits; no queue, rejection, or funding response is simulated. An obligation is covered only when its outgoing payment is on time and the post-payment resource balance is nonnegative.

## Limitations

This is a selected regulatory implementation for a deliberately limited synthetic universe. It is not a filing engine or compliance certification. The official reporting format includes overlapping inventories, additional schedules, legal entities, and dimensions omitted here. Local buckets and counterparty codes are simplified.

**Stylized/unverified parameters:** all FHLB and discount window eligibility tags and haircuts, immediate borrowing access, internal stress coefficients, and internal appetite thresholds. Regulatory coefficients used in the supported categories were verified in primary text. eCFR retrieval failed, so the CFR text was checked through Cornell LII. Security qualification, deposit insurance aggregation, operational status, and capital eligibility remain assumed classifications.

The model omits interest and amortization, optional maturities, currency conversion, multi-entity transfer restrictions, regulatory category tailoring, brokered deposits, structured transactions, general derivative netting and margin, general asset-exchange and secured-lending HQLA unwinds, venue credit limits and legal access checks, and repeated refinancing of rolled debt. Intraday monitoring covers one synthetic day and omits customer intraday credit portfolios and monthly statistics. Floating-point amounts are not cent-exact accounting. No external market data are used.

## Layout

```text
src/liquidity_suite/   Model engines and artifact generation
tests/                Analytic and invariant unittest tests
docs/                 Methodology and generated internal assessment
examples/             Complete run and stress sensitivity scripts
examples/output/      Reproducible CSV and Markdown artifacts
.github/workflows/    CI validation
```
