# Salesforce business vocabulary

These rules follow the supplied replication manual and the users' business mappings. Local supplements may add vocabulary but cannot change the validated execution contract.

## Grains and amounts
- A BO (business opportunity) is an opportunity, keyed by opportunity_no. Summary means opportunity grain (one row per BO). Detail means opportunity_sku grain, keyed by opportunity_no and product_code.
- Opportunity amount is the sum of SKU amounts (opportunity_amount). Revenue, amount, deal value, and deal size in ordinary questions mean this amount. The exported parent amount (exported_opp_amount_min/max) is a comparison field only, never an additive measure or a ranking key.
- At SKU grain quantity and amount_converted are summed; missing/non-numeric inputs are ignored like SQL SUM. An entirely missing group stays null.
- Unique or distinct opportunities (BOs) mean opportunity grain: exactly one row per opportunity_no. When counting, opportunity_count counts distinct opportunity_no even at SKU grain. SKU count counts opportunity/SKU business rows, not globally distinct product_code values.
- Top N, largest, biggest, or highest opportunities sort by opportunity_amount descending with opportunity_no ascending as the tie-breaker, then limit N. Smallest sorts ascending.

## Stages
- Won includes Won, Rollout Started, Rollout Finished. Open includes Identified, Qualified, Negotiation. Lost includes Dropped, Lost.
- Won BOs, open BOs, lost BOs, and the bare words won, open, lost refer to those groups. Stage filters using the group names expand to their members. Use stage_group for grouped reporting.

## Mapping words to columns
- Product marketing names such as S26, Galaxy S25, or Tab are case-insensitive contains filters on pet_name (Product Marketing Name). A code such as a SKU number is an exact product_code filter.
- Product categories such as tablet, smart phone, or wearable are case-insensitive contains filters on gscm_product_group_new (Product Group).
- Subsidiary codes such as SETK, SGE, or SGH are exact filters on subsidiary_subsidiary_code.
- Customer names such as TDbooks are case-insensitive contains filters on end_customer, unless the user quotes an exact name.
- Owner names are exact filters on opportunity_owner; a partial name is a contains filter.
- Age is the supplied opportunity age in days; it is filtered or shown, never recalculated or summed. first_channel, comment, and deal_size_on_pricing_date_usd are opportunity attributes shown in both layouts.
- Measure deal_size sums deal_size_on_pricing_date_usd once per opportunity, in USD; it cannot be broken down by product fields. Product breakdowns use amount.

## Dates
- Raw dates use DD/MM/YYYY with one- or two-digit days and months. Query filters use YYYY-MM-DD. Probability is a fraction: 75% becomes 0.75.
- A month, quarter, or year (March 2026, Q1 2026, 2026) filters close_month with an inclusive between over the whole period: March 2026 is 2026-03-01 to 2026-03-31, Q1 2026 is 2026-01-01 to 2026-03-31.
- Closing on or before/after a specific day, or "close date", filters close_date. Created and last modified refer to created_date and last_modified_date.
- Relative periods (last month, this quarter, year to date) are resolved from today's date given in the prompt; if the reference point is unclear, ask.

## Scope and follow-ups
- Opportunity filters on product-only fields select full matching opportunities. Use SKU grain for totals of only matching products. Ask when the intended scope is unclear.
- Table dimensions select columns; metric and chart dimensions group rows. Table results always retain their business keys.
- Refine keeps previous filters unless explicitly removed or replaced on the same field. New questions use replace.
- A numeric-looking opportunity_no or product_code is still text. Never sum identifiers or exported parent amounts.
- Do not invent fiscal periods, currency conversion, weighted revenue, or unsupported calculations. Ask a short clarification.
