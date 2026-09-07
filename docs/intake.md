# Remaining work-PC integration inputs

The replication manual supplies PostgreSQL relation names, raw columns, canonical views, amount rules, stage groups, QueryPlanV1, and the Qwen endpoint format. Those are implemented in v0.2. Version 0.4 adds the four remaining extract columns (`1st_channel`, `age`, `comment`, `deal_size_on_pricing_date_usd`), reads the raw table directly, and supports a local CSV export for development.

Please provide these next, without pasting credentials:

1. The actual PostgreSQL host/port/database, and whether TLS needs an internal CA file. Put the username and password directly in the work-PC .env.
2. Confirmation of the current local Qwen endpoint/model ID. Put the API key directly in .env. Internal model hosts with public-range addresses need an exact B2B_LLM_ALLOWED_HOSTS entry.
3. Five to ten real questions with expected columns, grain, filters, and totals. Include a follow-up question and a product-filter example.
4. Whether bi_reporting.b2b_project contains only the current extract, or historical snapshots that need an explicit selection rule. Confirm that its 30 column names match the export headers the app already resolves; any different spelling can be added to the alias table.
5. Whether all converted amounts use the same currency, and whether the exported parent currency agrees with SKU amount currency.
6. How colleagues reach the work PC: local-only use, an existing authenticated reverse proxy, or another approved hosting arrangement.

The supplied document is an architectural specification, not the original complete implementation. If the internal app has behavior beyond the documented contract, paste the relevant script with its filename and secrets replaced by placeholders. Incoming files can go in the Git-ignored incoming/ folder until reviewed.

A live read-only SQL and Qwen test on the work PC is still required before replacing the existing app. The migration file is legacy documentation of the original SQL view rules; nothing runs or reads it since 0.4.
