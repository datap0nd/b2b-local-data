# Bring over the existing project

Paste scripts in this conversation one at a time, with the filename above each code block. Start with the SQL connection/query script, then the Qwen request and prompt helper, then the summary/detail transformations. Use placeholders for credentials. An existing working script is more useful than recreating its behavior from memory.

If pasting files directly into this workspace is convenient, use `incoming/`. That folder is ignored by Git until we review and integrate its contents.

## First questions

1. Is SQL PostgreSQL, SQL Server, or something else? Is authentication username/password, Windows, or another method?
2. How is Qwen served: Ollama, LM Studio, vLLM, or another endpoint? What exact model ID is currently configured? Share the request shape with secrets replaced.
3. Which external GitHub repository should hold this app? The starter uses private `datap0nd/b2b-local-data`. Is the work-PC installer allowed to download from private GitHub, python.org, and files.pythonhosted.org? Does it need a proxy or browser-download fallback?
4. Will colleagues open a page hosted by the work PC, or will each person run their own copy? Does the existing app already have authentication or a Windows service?

## Data and table rules

Please paste the column list and SQL types, or the current SELECT statement. A tiny fictional example showing the expected summary and detail results is enough; no extract file is required.

| Decision | What we need to know |
| --- | --- |
| Opportunity key | Exact column; whether IDs can be missing or contain leading zeroes |
| Product grain | SKU, product name, opportunity-line ID, or a combination |
| Repeated SKU | Sum multiple genuine product lines, or remove duplicate copies? |
| Historical snapshots | Does the table hold only the newest extract? Which field marks snapshot/version? |
| Quantity/value | Which fields belong to a product line and which repeat an opportunity-level total? |
| Other numbers | Which are sums, averages, weighted averages, rates, IDs, or values kept once? |
| Currency | One currency, multiple currencies, or a preconverted reporting value? |
| Nulls/conflicts | Existing behavior for missing numbers and conflicting header values |
| Product filtering | Matching product lines only, or all lines for matching opportunities? |
| Dates/stages | Fiscal calendar, timezone, relevant date fields, and definitions of open/won/pipeline |
| Expected outputs | Default columns, order, sorting, rounding, export format, and full-export needs |

## Copy order

1. SQL connection and data-fetch script, with secrets replaced by variable names.
2. Main app entry point and dependency list, if there is one.
3. Summary-table builder and detail-table builder.
4. Qwen/Gemini request code, prompt helper, and clarification handling.
5. Business-rule prompt/configuration and five typical questions with expected results.
6. Existing setup/update or hosting script if it differs from data governance.

We will preserve the working business behavior as these arrive, add regression examples for the tricky cases, and replace the fictional schema. Live SQL and Qwen testing must happen against the work-PC environment after its configuration is supplied.
