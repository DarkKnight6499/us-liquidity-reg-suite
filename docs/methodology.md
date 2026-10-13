# Methodology and model boundaries

All amounts are USD millions. The synthetic calculation date is fixed in `common.AS_OF`; `common.SEED` controls NumPy `default_rng`. No runtime function opens a network connection. Synthetic positions are homogeneous pools, not individual insured deposit accounts. Counterparty IDs identify synthetic funding groups. Insurance, relationships, operational status, HQLA qualification, regulatory capital qualification, fair value equal to carrying value, and risk weights are model inputs, not legal conclusions.

## Data and contractual flows

The bank has cash, liquid securities, residential mortgages, corporate and financial loans, secured lending, deposits, term debt, repo, derivative payables, other payables, capital, and undrawn facilities. Dirichlet weights allocate fixed product totals across position pools. Assets reconcile to liabilities plus equity. Undrawn facilities are outside the balance sheet. Dates use calendar days, except NSFR maturity bands, which use calendar anniversaries. All currencies are USD; the validator rejects other currencies rather than aggregating unconverted amounts.

The cash flow table includes principal only. Demand liabilities appear on the calculation date. Cash holdings, equity, and undrawn commitments have no contractual principal flow. Interest, coupons, amortization, prepayment, options, and business-day settlement adjustments are omitted. Balances are not inferred from market prices.

## Reporting structure

The Federal Reserve instructions identify I.A Inflows-Assets, I.U Inflows-Unsecured, I.S Inflows-Secured, O.D Outflows-Deposits, O.W Outflows-Wholesale, O.S Outflows-Secured, and O.O Outflows-Other. The local supplemental partition uses S.B.1 Regulatory Capital Element. These names and selected product IDs were checked in the instruction contents and Product Definitions, printed pages 33 through 73. Field Definitions and Appendix I describe the official reporting structure. [Federal Reserve FR 2052a instructions](https://www.federalreserve.gov/apps/reportingforms/Download/DownloadAttachment?guid=ec24a96e-e47b-490c-b4b0-cf88e22a9ee2).

This implementation partitions each position once to permit source reconciliation. It is not the official overlapping inventory and cash flow submission schema. It omits I.O, most supplemental schedules, entity consolidation, forward starts, sub-products, effective maturity, and official maturity tailoring. Counterparty codes prefixed `LOCAL_` and maturity buckets are local simplifications. The supplemental table is a capital-only subset. Loan pools use I.U.6; residential mortgage pools use I.S.8; securities use I.A.1 or I.A.7; reserves use I.A.3. Retail deposits are treated as transactional accounts for the reporting mapping, while stable-rate classification conservatively requires a relationship flag as well as insurance.

The validator checks schema completeness, nonnegative finite balances, enums, boolean fields, contractual dates, unique IDs, and linked repo collateral. Table checks compare every source ID, code, bucket, and balance, then reconcile bucket sums to source partitions. An injected-defect example shows missing fields, invalid counterparties, and negative balances. These are deterministic checks, not an assessment of actual source-system completeness.

## LCR

HQLA starts with free liquid holdings. Level 2A receives a 15% haircut and level 2B a 50% haircut. With haircut-adjusted amounts A, B, and C for levels 1, 2A, and 2B, excess level 2 equals `max(B+C-0.6667*A, 0)`; excess level 2B equals `max(C-excess2-0.1765*(A+B), 0)`. Current holdings lose the larger current or post-unwind excess. The rounded CFR coefficients are retained, rather than substituting exact fractions for the nominal 40% and 15% caps. [12 CFR 249.21(b) through (i)](https://www.law.cornell.edu/cfr/text/12/249.21).

The unwind restores linked securities from repos maturing inside the LCR window and deducts the cash repayment. Synthetic secured lending uses non-HQLA collateral, so it does not affect the HQLA unwind. General secured-lending collateral reuse, asset exchanges, and collateralized derivative unwinds are outside the supported position model. The standalone `hqla` function accepts externally calculated adjusted holdings. Operational monetization capability, Treasury control, transferability, reserve requirements, and qualification are assumed; encumbered holdings are excluded. [12 CFR 249.22(a),(b)](https://www.law.cornell.edu/cfr/text/12/249.22).

Selected outflow rates: stable and other retail deposits 3% and 10%; operational wholesale deposits 5% if fully insured and 25% otherwise; nonfinancial nonoperational wholesale funding 20% if fully insured and 40% otherwise; other wholesale funding 100%. Secured funding rates are 0%, 15%, 50%, and 100% for level 1, level 2A, level 2B, and other collateral; the supported sovereign exception is 25% for other collateral. Facility rates depend on retail, nonfinancial, bank, and other financial counterparties and on credit versus liquidity commitment type. Derivative payables are unnetted contractual cash outflows. [12 CFR 249.32(a),(c),(e),(h),(j),(l)](https://www.law.cornell.edu/cfr/text/12/249.32).

Retail and nonfinancial loan inflows receive 50%; financial loan inflows receive 100%. Secured lending uses the collateral-based schedule. Nonperforming exposures and eligible HQLA cash flows are excluded. All modeled derivative contracts have only payables, no receivables or netting. [12 CFR 249.33(a),(c),(d),(e),(f)](https://www.law.cornell.edu/cfr/text/12/249.33).

The inflow cap is 75% of gross outflows. The maturity mismatch add-on is the positive peak cumulative maturity gap less the positive endpoint gap, based on the supported eligible sections. Open corporate deposits are excluded from the add-on; open financial nonoperational deposits enter on the first day. Full outflow calibration is assumed. The suite does not infer applicability or tailoring from synthetic asset size. [12 CFR 249.30(a),(b),(c)](https://www.law.cornell.edu/cfr/text/12/249.30).

Brokered and sweep deposits, market-maker buybacks, structured transactions, collateral substitution, additional regulatory derivative collateral outflows, and commitment collateral offsets are absent from the generated universe. The internal stress margin assumption is not substituted into regulatory LCR.

## NSFR

ASF uses 100% for assumed eligible capital and nonretail funding at least one year; stable and other nonbrokered retail deposits use 95% and 90%. Operational deposits, short nonfinancial wholesale funding, and qualifying intermediate funding use 50%. Short financial funding and short issued debt use zero. These are selected category rules, not the complete liability taxonomy. [12 CFR 249.104(a) through (e)](https://www.law.cornell.edu/cfr/text/12/249.104).

RSF uses zero for cash and level 1 securities; 15% for level 2A and qualifying short financial loans; 50% for level 2B, intermediate financial loans, and short nonfinancial loans. Qualifying long residential mortgages receive 65%; other qualifying long nonfinancial loans receive 65% or 85% according to the supplied risk weight. Long financial loans and nonperforming assets receive 100%. Undrawn facilities receive 5%. Encumbrance at least six months imposes a 50% floor; at least one year imposes 100%. Short level 1 secured lending requires assumed rehypothecation rights for its zero factor. [12 CFR 249.106(a),(b),(c)](https://www.law.cornell.edu/cfr/text/12/249.106).

Synthetic derivative liabilities are nonnetted and uncollateralized, with no exchanged margins. Their ASF is zero; the separate RSF potential valuation contribution is 5% of gross negative values. Derivative assets and general margin and netting cases are unsupported and rejected as invalid product-side combinations. [12 CFR 249.107(b)(5),(c)](https://www.law.cornell.edu/cfr/text/12/249.107).

The ratio uses full RSF calibration without category tailoring. Off-balance-sheet rehypothecated assets, interdependent assets and liabilities, and most derivative cases are omitted. Regulatory sections are modeled for the synthetic universe, not for unrestricted real-bank portfolios.

## Internal stress and CLRI

`assumption_table` exports all segment runoff rates at the requested horizons and each scenario's rollover, haircut shock, drawdown, and collection assumptions. Every coefficient is internal and stylized/unverified. The market-wide scenario is intentionally more severe than the idiosyncratic scenario; this ordering is a design choice. Combined stress is stronger on every modeled dimension.

Deposit runoff interpolates cumulative horizon assumptions and is capped at the segment balance. Drawdowns and contingent margin build linearly through the first stress month. Wholesale maturities repay the fraction not rolled. Rolled balances remain outstanding beyond the horizon; repeated future refinancing is omitted. Repaid repos release the matching fraction of securities, monetized at stressed value. Margin exposure uses twice modeled derivative payables, scaled by scenario severity. This contingent exposure is separate from payment of the existing payable.

Starting counterbalancing capacity comprises cash, immediate sale of free securities, and immediate borrowing against non-HQLA assets. Each asset is allocated once. Loan maturities collect scenario-adjusted proceeds and repay the borrowing assumed against those loans. There is no second security maturity receipt after sale and no borrowing against sold HQLA. Nonperforming collateral has no borrowing capacity. Restrictions on the separately encumbered mortgage pool last beyond the simulation.

Survival is the final funded calendar day before the first negative daily balance. A funded endpoint is explicitly censored. Peak shortfall uses the largest cumulative net need, not only the endpoint. Timing is daily; no recovery action is modeled after failure. The CLRI lists undrawn facilities, derivative margin triggers, and short refinancing exposure. These entries explain stress channels and are not an additional aggregate outflow amount.

## Collateral

FHLB and discount window eligibility tags and haircut schedules are parameterized, stylized/unverified. Alternative lendable values are informative, never additive. The allocator selects the higher lendable value for each free asset, with deterministic venue priority on ties. Stress excludes HQLA from collateral borrowing because those securities are sold. Existing encumbrance prevents new borrowing. Haircut shocks add percentage points and are capped at full loss of lendable value. Venue credit limits, membership, documentation, statutory restrictions, lien priority, operational access, and advance repayment terms require separate modeling before practical use.

## Intraday tools

The suite implements category A daily maximum usage, available start-of-day resources, total payments, and time-specific obligations; direct-participant category C throughput is also included. Usage is the absolute largest negative cumulative settlement-flow balance relative to the opening position. Opening resources are separate from usage. Throughput is cumulative outgoing value at each hour divided by daily outgoing value. Obligations retain deadlines and flag late settlement. [BCBS 248, paragraphs 13 through 23 and 27, Table 1](https://www.bis.org/publications/201304-standards-monitoring-tools-intraday-liquidity-management.pdf).

One synthetic settlement day is modeled. Timestamp ties follow payment ID order. Resources are supplied explicitly and must represent distinct available sources. Central bank facility proceeds are excluded from payment receipts. Correspondent-service category B tools, multiple currencies and settlement accounts, monthly top-three statistics, and payment queues are omitted. No actual correspondent service or intraday credit portfolio is asserted.

## Limits and assessment

Internal thresholds are stylized appetite choices. LCR maps to Liquidity Coverage Ratio Examination Procedures; NSFR to Net Stable Funding Ratio Examination Procedures; survival to Contingency Funding Plans; wholesale dependence to Funding Diversification; intraday usage to Intraday Liquidity and Collateral Management. These topic names were checked in the OCC booklet. Proposed owners and escalation rules are model design choices. [OCC Comptroller's Handbook, Liquidity](https://www.occ.gov/publications-and-resources/publications/comptrollers-handbook/files/liquidity/pub-ch-liquidity.pdf).

Green includes equality at its threshold; red starts strictly beyond its boundary; the intervening range, including equality at the red boundary, is amber. Missing or nonfinite KRI values are red data exceptions. Censored survival is tested only as demonstrated funded days. Wholesale concentration means wholesale deposits plus debt and repo divided by all liabilities, not the largest single counterparty share. Intraday usage is divided by available opening resources. The generated ILAAP-style report is an internal narrative format, not a US filing requirement or a declaration of legal compliance.

## Verification record

Primary text was read using web retrieval on the build date. eCFR URLs were inaccessible through the web tool; Cornell LII's CFR text supplied the section language. The Federal Reserve form page linked directly to the current instructions. The BIS publication page linked to the original document. OCC topic names were read from the booklet contents and text. Shell networking was unavailable, so remote PDFs were inspected using the web tool's extracted text. No local PDF artifact was created. No regulatory coefficient used here remains unverified; position qualification and internal policy parameters remain assumptions.

## Validation and extension

The unittest suite includes independently hand-computed ratios, binding caps, the inflow ceiling, calendar boundaries, scale invariance, collateral conservation, source lineage, shock monotonicity, survival timing, settlement-flow reconciliation, and threshold transitions. Floating-point money is suitable for scenario analysis, not cent-exact accounting. Extend the schema and source mapping before using unsupported products, currencies, legal entities, optional maturities, or collateral reuse arrangements. Tests validate algorithms for this supported universe; they do not certify regulatory compliance.
