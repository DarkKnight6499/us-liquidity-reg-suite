# Synthetic ILAAP-style liquidity assessment

This is a model-generated internal assessment structure, not a US regulatory filing or an assertion that US banks must prepare ILAAP. Amounts are USD millions. The calculation date is 2026-09-30. All inputs are synthetic.

## Governance

The proposed board risk appetite is implemented through the limit framework. Treasury owns funding execution; independent Risk challenges assumptions; ALCO reviews amber exceptions and immediately escalates red exceptions. This is a proposed governance design, not evidence of actual approvals or controls.

## Risk identification

The balance sheet includes 912 synthetic position pools and 120,000.000000 of assets. Deposit withdrawal, wholesale rollover, collateral accessibility, committed drawdowns, derivative margin, and payment timing form the risk inventory. The CLRI output retains source IDs, triggers, exposure sizes, and timing. Exposures are alternative risk channels and must not be summed as a second set of stress outflows.

## Measurement

The LCR is 154.197173% with HQLA of 33,100.000000 and net outflows of 21,466.022557. The NSFR is 159.927231%, with ASF of 77,450.261669 and RSF of 48,428.439037. Source and reporting checks produce 0 exceptions. See methodology for verified CFR references, assumptions, and omitted cases.

## Stress results

Survival is the last fully funded calendar day before the first negative balance. Censored survival means the scenario remains funded through the simulation endpoint; it is not an estimate of ultimate survival.

| scenario | counterbalancing_capacity | survival_days | censored | peak_net_need | maximum_shortfall |
| :-: | :-: | :-: | :-: | :-: | :-: |
| idiosyncratic | 70,550.000000 | 365 | True | 32,969.064416 | 0.000000 |
| market_wide | 62,050.000000 | 365 | True | 47,666.553780 | 0.000000 |
| combined | 53,550.000000 | 64 | False | 66,292.442552 | 12,742.442552 |

### Horizon snapshots

| scenario | day | net_need | liquidity_balance |
| :-: | :-: | :-: | :-: |
| idiosyncratic | 30 | 16,908.595145 | 53,641.404855 |
| idiosyncratic | 90 | 22,954.043979 | 47,595.956021 |
| idiosyncratic | 365 | 28,588.372521 | 41,961.627479 |
| market_wide | 30 | 29,064.688781 | 32,985.311219 |
| market_wide | 90 | 36,696.447135 | 25,353.552865 |
| market_wide | 365 | 43,133.617883 | 18,916.382117 |
| combined | 30 | 46,578.769257 | 6,971.230743 |
| combined | 90 | 54,010.213607 | -460.213607 |
| combined | 365 | 61,876.789678 | -8,326.789678 |

## Contingency funding

The plan uses cash, securities monetization, FHLB allocation, and discount window allocation in that order. Baseline borrowing capacity excluding HQLA is 41,700.000000. Haircuts, eligibility, access, and immediate execution are stylized/unverified. Venue alternatives are mutually exclusive. Maturing loans repay the advance assumed against them, preventing reuse of principal. Combined-stress capacity is 53,550.000000 and the peak shortfall is 12,742.442552. Proposed actions are to reduce wholesale dependence, increase available liquid assets, and test collateral mobilization and funding access.

## Intraday liquidity

Daily maximum usage is 2,230.807554; opening resources are 12,000.000000. Total payments sent are 5,774.502634 and received are 4,508.029112. This single-day simulation does not provide monthly monitoring statistics.

## Limits

| kri | value | status | owner | escalation |
| :-: | :-: | :-: | :-: | :-: |
| LCR | 1.541972 | green | Treasurer | routine monitoring |
| NSFR | 1.599272 | green | Treasurer | routine monitoring |
| ILST survival days | 64.000000 | amber | Chief Risk Officer | Chief Risk Officer: review next business day |
| Wholesale funding concentration | 0.481818 | red | Funding Desk | Funding Desk and ALCO: immediate escalation |
| Intraday usage | 0.185901 | green | Payments Head | routine monitoring |

## Conclusion on adequacy

The synthetic bank does not meet the internal long-horizon adequacy target. The combined scenario exhausts liquidity before the survival appetite threshold. Wholesale concentration also exceeds internal appetite. Regulatory-style ratios alone do not establish internal liquidity adequacy.

The conclusion is conditional on the synthetic balance sheet, deterministic scenario coefficients, immediate funding access, and the selected regulatory universe. No actual institution's adequacy or compliance is assessed.
