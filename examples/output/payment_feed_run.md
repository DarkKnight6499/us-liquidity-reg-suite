# Synthetic payment-feed run

Seed: 2052. Synthetic weekday: 2026-09-30. All amounts are USD millions. This feed is synthetic and is not a connection to any real payment system.

Stress delays BANK_01 receipts by 3 hours and reduces the opening credit line by 1,500. Opening reserves are 1,000, credit is 2,500, and distinct collateral capacity is 500.

Timing mixtures, lognormal sizes, counterparties, settlement windows, netting releases, events, resource assumptions, and alert thresholds are stylized. CHIPS-like releases are messages, not a CHIPS netting algorithm. Payments are recorded despite resource deficits; no queue is simulated.

| scenario | maximum_usage | available_at_start | maximum_positive_position | reserves | credit_lines | collateral_capacity | total_sent | total_received | net_cumulative | total_payments | payment_count | time_specific_obligations | covered_obligations_value | late_obligations | uncovered_obligations | correspondent_value | resource_shortfall | deferred_count | deferred_value | breach_count | first_usage_alert | first_resource_breach | peak_usage_change |
| :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| baseline | 1,955.196066 | 4,000.000000 | 2,457.547842 | 1,000.000000 | 2,500.000000 | 500.000000 | 27,806.755700 | 27,414.299422 | -392.456278 | 55,221.055122 | 2000 | 15,506.573902 | 15,506.573902 | 0 | 0 | 4,989.563143 | 0.000000 | 0 | 0.000000 | 3 | NaT | NaT | 0.000000 |
| stressed | 3,619.397544 | 2,500.000000 | 707.164389 | 1,000.000000 | 1,000.000000 | 500.000000 | 27,806.755700 | 24,772.423219 | -3,034.332481 | 52,579.178919 | 1947 | 15,506.573902 | 12,552.133634 | 0 | 52 | 4,989.563143 | 1,119.397544 | 53 | 2,641.876203 | 25 | 2026-09-30 12:51:00 | 2026-09-30 15:00:00 | 1,664.201478 |

Chart: Skipped: matplotlib is unavailable.
