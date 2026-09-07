# Salesforce business vocabulary

These rules follow the supplied replication manual. Local supplements may add vocabulary but cannot change the validated execution contract.

- Summary means opportunity grain, keyed by opportunity_no. Detail means opportunity_sku grain, keyed by opportunity_no and product_code.
- Opportunity amount is the sum of SKU amounts. Exported parent opportunity amounts are comparison fields, never an additive measure.
- At SKU grain quantity and amount_converted are summed; missing/non-numeric inputs are ignored like SQL SUM. An entirely missing group stays null.
- Conflicting metadata is selected deterministically with MIN and shown with quality warnings according to the canonical views. A parent amount mismatch greater than 0.01 also warns.
- Raw dates use DD/MM/YYYY. Query filters use YYYY-MM-DD. Probability is a fraction: 75% becomes 0.75.
- Won includes Won, Rollout Started, Rollout Finished. Open includes Identified, Qualified, Negotiation. Lost includes Dropped, Lost.
- Stage filters using those canonical names expand to their members. Use stage_group for grouped reporting.
- Opportunity filters on product-only fields select full matching opportunities. Use SKU grain for totals of only matching products. Ask when the intended scope is unclear.
- Table dimensions select columns; metric and chart dimensions group rows. Table results always retain their business keys.
- Amount and quantity are sums. Opportunity count counts distinct opportunity_no. SKU count counts opportunity/SKU business rows, not globally distinct product_code values.
- A numeric-looking opportunity_no or product_code is still text. Never sum identifiers or exported parent amounts.
- Refine keeps previous filters unless explicitly removed or replaced on the same field. New questions use replace.
- Do not invent fiscal periods, currency conversion, weighted revenue, or unsupported calculations. Ask a short clarification.
