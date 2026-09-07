# Salesforce source contract: salesforce-lines-v2

The application treats a source record as one exported opportunity/product line. An
opportunity may contain many products; an opportunity/product pair may contain many
source rows. Identical-looking rows remain additive because the export supplies no
line-item identifier proving that either row is a duplicate. `source_row_count` and
the multiplicity-preserving dataset fingerprint retain that distinction. Missing
opportunity or product identifiers are excluded and counted in snapshot diagnostics.

## Explicit mapping

`data_layer.SOURCE_BUSINESS_FIELDS` declares one mapping for the CSV and raw-table
adapters. Neither adapter guesses or swaps fields based on a query or its values.
Normalized raw column names preserve the original header provenance:

| Business meaning | CSV header | Normalized raw / PostgreSQL field |
| --- | --- | --- |
| Additive exported line amount | `Opp Amount (converted)` (alias `Opportunity Amount (converted)`) | `opp_amount_converted` |
| Currency of that line amount | `Opp Amount (converted) Currency` | `opp_amount_converted_currency` |
| Whole opportunity total repeated on its lines | `Amount (converted)` | `amount_converted` |
| Currency of that repeated total | `Amount (converted) Currency` | `amount_converted_currency` |
| Independently reported deal size in USD | `Deal Size on Pricing Date (USD)` | `deal_size_on_pricing_date_usd` |

The mapping is supported by examination of the September 2026 local CSV: the repeated
field is constant within every examined opportunity and additive line sums reconcile
within 0.01 for 12,454 of 12,575 opportunities. This is strong empirical evidence,
**not independent confirmation of Salesforce report definitions or PostgreSQL export
lineage**. The live PostgreSQL adapter applies this declared contract, but its column
semantics still require verification against its actual extraction/report definition.
Passing synthetic adapter parity tests does not establish that verification. If a
different upstream table uses different business meanings, adapt it explicitly to
this contract before relying on its monetary output.

`reference_evaluator.py` independently declares these meanings as `reference-3`.
It does not import the production mapping. `tests/test_source_contract.py` uses
literal, asymmetric examples to make an accidental shared reversal fail.

## Reduction and reconciliation

For two products with line amounts 40 and 60, and a repeated opportunity total of
100 on each line, SKU amounts are 40 and 60 and the opportunity amount is 100. The
exported comparison total remains 100. Quantities are line quantities and are summed
once; the count of the opportunity is one. Selecting only the first product at SKU
grain gives 40; selecting whole opportunities containing that product gives 100.

Canonical `sku_amount` sums source line amounts for each opportunity/product key.
Canonical `opportunity_amount` sums those SKU amounts for the opportunity. It never
adds the repeated whole opportunity total or silently substitutes that total for
the line sum. `exported_opp_amount_min` / `max` retain the source's repeated parent
values; conflicts are explicit. Deal size remains a separate reported USD measure,
counted once per opportunity and never inferred from either converted-amount field.

The historical public currency column names remain supported: SKU
`amount_converted_currency` and opportunity `opp_amount_converted_currency` both
describe the **canonical sum of line amounts**, hence both originate from raw
`opp_amount_converted_currency`. Internal `exported_opp_amount_currency` separately
describes the raw repeated parent amount. These names must not be used to infer the
raw mapping. Raw records and their fingerprint remain unchanged.

Currencies are validated before any SKU or opportunity amount sum. A missing code
or multiple codes makes that grain's scalar amount unavailable; all observed codes
remain in internal `amount_currency_values`. A valid line sum may still have an
unreconcilable parent currency; this is a comparison issue, not an implicit currency
conversion. Amount queries cannot report invalid mixed-currency scalars as totals.

Missing or invalid numeric values remain null. A known subtotal can be shown for
review, but a missing line is flagged even if that subtotal happens to equal the
exported total. It must not be presented as a complete aggregate. Parent comparison
requires one valid parent total and matching known currencies. Differences strictly
greater than 0.01 are flagged; exactly 0.01 is inside the existing tolerance. The
tolerance is not widened to hide the remaining source discrepancies, and their
causes (rounding, missing lines, charges, extraction rules) are not guessed.

## Memberships and quality evidence

`first_channel` has no confirmed single-valued grain in the source. All nonempty
memberships survive in internal `first_channel_values`, including multiple values
inside a repeated SKU key. A canonical row with several values displays
`Multiple channels`. Membership equality/inclusion filters match any actual member;
exclusion matches none. Grouping uses one explicit `Multiple channels` bucket, so
the app does not allocate or repeat an opportunity's amount across channels.

Other metadata fields retain deterministic minimum-value selection; conflicting
known values are surfaced with the field and all observed alternatives. Opportunity
metadata is checked across all original lines, not only a previously reduced SKU.
Different product names across different products are normal. Conflicting names
within the same SKU are reviewable. Last modification date uses the latest date;
normal differing update timestamps do not create a conflict.

`CanonicalViews.quality_details` stores all flagged keys at both grains. Reasons
distinguish missing/invalid amounts, conflicting repeated parent totals, arithmetic
mismatches, metadata conflicts, multiple channels, and missing/mixed/mismatched
currencies. A mismatch includes the line sum, exported comparison total, signed
difference, and currency. One opportunity can have several reasons but contributes
one to the affected-opportunity count. These flags retain rows for review; a channel
ambiguity or unresolved source discrepancy is not proof the source is wrong.

Open status depends on stage: Identified, Qualified, or Negotiation. Close month is
a separate closing-date attribute and does not establish Open status. Won and Lost
opportunities may also have a close month; created date is independent.

## Historical SQL and saved results

Migrations 001 and 002 describe historical view consumers and their earlier amount
assumptions. The current application reads raw records in a read-only transaction
and does not execute those migrations or query the derived views. They are not
current monetary reference implementations. Do not apply them to establish parity
with this contract. Their existing date-parser compatibility test remains a
historical migration test only. Live-source semantic validation is still required.

The data contract and independent evaluator versions form calculation provenance.
Previously saved results retain their original evidence/version; corrected results
require an explicit rerun. Old acceptance qualification must not qualify a new
calculation version merely because the raw dataset fingerprint is unchanged.
