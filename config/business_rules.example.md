# Example rules — replace with confirmed business definitions

- Summary means one row per opportunity; detail means one row per opportunity and SKU.
- Quantity and line value are additive product-line fields. Opportunity value is repeated on product rows and must be retained once, never summed across those rows.
- Repeated opportunity attributes must agree, including currency. Conflicts are data-quality errors.
- A numeric-looking opportunity number or SKU is an identifier.
- A product filter can mean matching product rows only, or all products from opportunities that have a matching product. Ask which scope the user wants if unclear.
- Do not invent a definition of open, pipeline, won, fiscal quarter, or revenue. Ask for missing definitions.
- Dates use ISO YYYY-MM-DD. Ask whether the user means close date if the date field is unclear. Resolve relative dates using the supplied current date.
- If the user asks for value, clarify line value versus opportunity value when the meaning is ambiguous.
- The starter supports summary/detail tables with AND filters, sorted by the view keys. It does not yet support arbitrary rankings, cross-opportunity groupings, OR filters, or computed metrics. Explain this and ask for a supported alternative; do not silently approximate.
- Product-line duplicates are summed in the example detail view. Confirm whether a line ID or snapshot date is needed before using real data.
- Never infer currency conversion, missing values, or percentages. Null numeric values remain unknown; aggregation returns null if any input is null.
