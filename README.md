# B2B Salesforce Query Agent

Ask a locally hosted Qwen model about the Salesforce extract in PostgreSQL, or about a local CSV export of the same extract during development. The model produces a validated `QueryPlanV1`; a deterministic engine returns opportunity/SKU tables, metrics, and charts.

The browser workspace is answer-first: one question at a time, the latest answer directly beneath the composer (title, scope and data-load time, read-only filter chips, warnings, metric cards or a chart, then the table), previous turns and saved conversations in a History drawer, and technical details in **Query details** / **Workspace details** disclosures. Column visibility, row details, sorting, chart measure, and CSV export stay in the browser. Version 0.5 adds the **Run acceptance test** action (in Workspace details): a standardized live-data acceptance test with an independent reference calculator and a Markdown report (see below). Version 0.4 reads all **30 Salesforce columns** with one shared parser from either the raw PostgreSQL table or a local CSV file. Version 0.3 implemented the supplied replication manual with a **FastAPI backend and a browser frontend**, plus a folder-based GitHub installer. Sorting, chart controls, and layout selection stay in the browser. Queries call the backend explicitly; ordinary clicks do not rerun Python. Qwen/model latency and data refresh time remain separate from UI interactions.

## Current state

The canonical 30-column schema, normalization, amount formulas, stage mappings, query contract, local history, CSV development source, and raw-table PostgreSQL source are implemented. Tests use invented fixtures and a disposable PostgreSQL instance in CI; the supplied sample export stays local and is checked only by an opt-in test. The work PC's actual database and Qwen endpoint still need a configured connection test. No credentials from the supplied manual are committed.

## Install and start on Windows

Only `setup.ps1` is needed on the work PC: save it in an empty install folder and run it. It downloads everything else from this private repository with the same `DG_GITHUB_TOKEN` GitHub token that the data-governance installer uses on work PCs (a token with **Contents: read** access). The installer reads `DG_GITHUB_TOKEN` from the environment, or from a `DG_GITHUB_TOKEN=` line in `.env` when the variable is absent. Keep the install folder between updates. SQL and Qwen settings can be filled in when ready; the defaults use fictional demo data.

Run from that folder:

```powershell
.\setup.ps1
.\start.ps1
```

Run the same `setup.ps1` whenever you want to refresh. The default install location is **the folder containing the script**. An explicit `-InstallDir` or `B2B_INSTALL_ROOT` setting can select a different folder. No Git client, administrator rights, pip, Node.js, or system Python installation is needed.

Setup resolves `main` to an exact commit, downloads its complete source archive from GitHub, and stages a clean application copy. It also runs a changed setup script from that revision during the same update. The active code lives under `releases/`, selected by `current.json`; removed code cannot linger in that active copy. Local settings and data remain alongside the launcher.

Python and all 25 library archives are downloaded **from this repository's GitHub release assets**, with SHA-256 verification against the locks. The upstream Python/PyPI URLs in the locks are provenance for maintainers; work-PC setup never uses them. GitHub's download CDN must also be reachable.

- `.downloads/` keeps the exact archives. Only missing, changed, or corrupted archives are downloaded.
- `runtime/` keeps portable Python and reuses a healthy matching version.
- `dependencies/` keeps verified, unpacked packages. Unchanged packages are reused; only new or damaged packages are unpacked.
- Each clean application copy receives its exact dependency set, using local hard links where supported and file copies otherwise. Dependencies removed from the lock do not appear in the refreshed app.
- `.env`, `business_rules.md`, and `data/` survive updates. Old application releases remain available for rollback.

To install an already-downloaded source revision without fetching `main`, use:

```powershell
.\setup.ps1 -LocalSource .
```

That option still downloads any missing dependencies from GitHub. For an entirely offline installation, add `-Offline` and provide a populated `-DownloadCache`. An authenticated browser download of the source ZIP alone does not contain the dependency archives. Pandas/NumPy and Pydantic's native extensions are packaged for the pinned Python 3.13/Windows x64 ABI; the launcher refuses an incompatible or incomplete release.

Run `start.ps1` in the install folder. The default address is <http://127.0.0.1:8765>. Sample buttons work without SQL or Qwen credentials. A fictional parent amount mismatch is deliberately included so you can see the quality warnings.

For development, use the installed portable interpreter with this checkout's `run_app.py` after running `scripts/vendor_dependencies.py` with that same interpreter. That maintainer/development command may download from the pinned upstream URLs. Work-PC setup calls it in offline mode after fetching GitHub assets. The native dependencies require Windows x64 Python, including x64 emulation on Windows ARM. There is no frontend build step.

## Work-PC configuration

Edit `.env` **in the install folder**, not in a versioned release. For the same setting name, an environment variable overrides the file. The data-governance and legacy alias names are used only when the canonical name is set nowhere, so `LLM_MODEL_NAME` in `.env` always beats `DG_AI_MODEL` from the environment. Values are literal, optionally quoted; no shell expansion occurs. The file is ordinary local text, ignored by Git, and should use your normal Windows file permissions.

The supplied replication manual explicitly included `.env` configuration and the `PGURL`, `RO_SQL_USER`, `RO_SQL_PW`, `LLM_API_URL`, `LLM_API_KEY`, and `LLM_MODEL_NAME` names used below. It also included the `B2B_DATA_DIR`, `B2B_INSTALL_ROOT`, and identity-header settings. `DG_GITHUB_TOKEN` is used by this private-repository installer only and is never sent to SQL or Qwen (the earlier `B2B_GITHUB_TOKEN` name is still accepted from old `.env` files).

```dotenv
# Only if DG_GITHUB_TOKEN is not already an environment variable.
DG_GITHUB_TOKEN=
PGURL=your-postgres-host:5432/postgres
RO_SQL_USER=your-read-only-user
RO_SQL_PW=your-password
DB_SSL=true
DB_CA_FILE=

AI_PROVIDER=openai_compatible
LLM_API_URL=http://your-internal-qwen-host:4002/v1/chat/completions
LLM_API_KEY=your-local-api-key
LLM_MODEL_NAME=qwen3.8-27b-fast

B2B_DATA_DIR=C:\YourInstallFolder\data
APP_PORT=8765
```

On a work PC the model is configured by the environment variables `LOCAL_AI_ENDPOINT`, `LOCAL_AI_API_KEY`, and `LOCAL_AI_MODEL` (case-insensitive), which fill `LLM_API_URL`, `LLM_API_KEY`, and `LLM_MODEL_NAME` when those are blank; the endpoint host is trusted automatically. The data-governance names `DG_AI_API_URL`, `DG_AI_API_KEY`, and `DG_AI_MODEL` are used after them, and `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD` supply the PostgreSQL connection. Values in `.env` take precedence when set.

A blank `DB_KIND` selects PostgreSQL when `PGURL` (or `PGHOST`) is present, otherwise fictional demo data. `DB_KIND=demo` explicitly stays in demo mode. The old `DB_HOST`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` and `AI_*` settings are accepted for existing installations; set `DB_KIND=postgres` with old database variables.

For development against a local export, set `DB_KIND=csv` and `B2B_CSV_PATH` explicitly. A relative path resolves from the folder containing `.env`; an absolute local path is accepted as is. `B2B_CSV_ENCODING` defaults to `utf-8-sig`. A missing, unreadable, malformed, or incomplete file stops the request with a message naming the file or the missing columns. CSV mode is never selected automatically, and a PostgreSQL failure never falls back to a CSV file or to demo data. Keep exports, copies, and result downloads in the install folder or another local place; `*.csv` and `*.xlsx` are Git-ignored, and the sample export must not be committed.

In demo and CSV modes the **Opportunity summary table**, **Product detail table**, and **Amount by stage group chart** sample buttons build fixed previews locally without calling Qwen. Natural-language questions still use the configured local model in every mode. The status line and each result name the actual source: fictional data, the CSV file name, or the PostgreSQL raw table.

Both complete `/v1/chat/completions` URLs and base URLs ending in `/v1` work. For Ollama, set `AI_PROVIDER=ollama`, its local URL in `LLM_API_URL`, and the exact installed model name. Internal servers using a public-range address require that exact hostname/IP in `B2B_LLM_ALLOWED_HOSTS`. This supports corporate routing without broadly allowing public endpoints. The operator must ensure the endpoint really hosts the local model. Model requests behave like the Scribble client on the same PC: the reply is streamed (`B2B_LLM_STREAM=true`), the Windows/system proxy settings are honoured (`B2B_LLM_USE_SYSTEM_PROXY=true`; set it to false to bypass proxies), only model, messages, stream, temperature, and max_tokens are sent, and an optional field the server rejects with 400 is dropped and the request retried. Redirects are refused; there is no Gemini/cloud fallback. `AI_TIMEOUT_SECONDS` (up to 900) applies to each read of the stream.

`DB_SSL=prefer` is the default and matches the data-governance connection: TLS without certificate checks when the server offers it, plain text otherwise. `DB_SSL=true` requires verified TLS (point `DB_CA_FILE` to an internal CA certificate if needed) and fails with "Server refuses SSL" on a server without TLS. `DB_SSL=false` disables TLS. The read-only login comes from `RO_SQL_USER`/`RO_SQL_PW`, or from `PGUSER`/`PGPASSWORD` when those are not set. A failed read reports the driver's own diagnosis with the password redacted. The application uses a read-only transaction, a statement timeout, and a maximum row bound. Its credentials need SELECT access, not migration privileges.

`B2B_DATA_DIR` defaults to `<install-folder>/data`. It contains SQLite conversation history. Questions, clarification responses, and validated plans are saved; result rows and credentials are not. Questions themselves can contain business information, so this folder belongs on the work PC. A saved conversation can be reopened and its query rerun against the current data.

## Data contract

The expected raw source is `bi_reporting.b2b_project` (`B2B_RAW_TABLE`, in `schema.relation` notation) holding the 30 extract columns as text. The application reads that table directly in a read-only transaction with the statement timeout and row cap, resolves its column names, and builds both grains with the same code that reads a CSV file. The two derived views and the version ledger from earlier releases are no longer read; [migrations/001_canonical_views.sql](migrations/001_canonical_views.sql) stays as legacy documentation of the original SQL rules only.

Canonical field names are lower snake_case identifiers. Each equals its PostgreSQL column name except `first_channel`, which maps to the column `1st_channel` (an identifier that must be quoted in SQL). Column names from either source are normalized (lowercase, punctuation and spaces become `_`) and matched against the canonical names, the SQL names, and a short manual alias table, so export headers such as `Opportunity No.`, `Subsidiary: Subsidiary Code`, `1st Channel`, or `Deal Size on Pricing Date (USD)` resolve without configuration. A source missing any of the 30 fields, or supplying two columns for the same field, is rejected with the field names listed. Extra columns are ignored.

The four columns added in 0.4 are opportunity attributes available in both layouts: `first_channel`, `age`, `comment`, and `deal_size_on_pricing_date_usd`. They are selected deterministically (MIN) like other metadata, never summed. `age` is the supplied value and is never recalculated. Differing values within an opportunity/SKU group or across an opportunity's SKU rows set `has_quality_warning` without dropping rows.

| Grain | Key | Amount |
| --- | --- | --- |
| SKU | `opportunity_no`, `product_code` | Sum of `amount_converted` for that pair |
| Opportunity | `opportunity_no` | Sum of its canonical SKU amounts |

All source values are loaded as text, so identifiers such as `000123` or `1E3` are preserved exactly. Text follows the supplied PostgreSQL `btrim` behavior: surrounding spaces are removed, empty strings become null. Numeric strings must match the manual's decimal pattern and are converted to exact decimals; malformed values become null. Probability is divided by 100, with an optional `%` suffix. Raw dates are day-first `D/M/YYYY` with padded or unpadded day and month; invalid calendar dates become null in both paths.

SQL-style reductions ignore null inputs. A sum with only null inputs stays null. Exported parent opportunity amounts are retained as min/max checks, never added as a measure. Amount discrepancy is true when the parent min/max differ, when the required comparison is unknown, or when the SKU total differs from the parent by more than 0.01. Metadata conflicts use the manual's specified quality fields, deterministic MIN/MAX selection, and visible warnings. These flags do not stop the table.

No database migration is required for 0.4; the app and installer never run DDL against the work database, and the read-only role needs SELECT on the raw table only. Connection failures, timeouts, missing columns, and oversized results stop the request rather than being hidden by fallback. The source cap defaults to 100,000 rows for both PostgreSQL and CSV; partial inputs are never reported as complete totals.

The source must contain the intended current extract. No historical snapshot de-duplication is invented. Rows without an opportunity number or product code are excluded, as in the supplied SQL.

## Queries and follow-ups

The Pydantic contract forbids unknown fields and supports:

- Intents: table, metric, chart, clarify. Every table result also reports complete-result totals and a `result_digest` so previews can be checked against everything that matched.
- Grains: opportunity and opportunity_sku.
- Filters: eq, ne, gt, ge, lt, le, contains, in, between. Filters are ANDed.
- Measures: amount, quantity, sku_count, opportunity_count, deal_size.
- Up to ten selected/grouping dimensions, three sort fields, and a 1,000-row result preview.
- Bar, line, area, and scatter charts, with exact values also available in a table.

For **tables**, dimensions select columns and business keys remain included. For **metrics/charts**, dimensions group rows. Opportunity count counts distinct opportunity identifiers even at SKU grain. SKU count counts opportunity/SKU pairs, not globally distinct product codes. Mixed-currency amount metrics require a currency grouping or filter.

`deal_size` sums `deal_size_on_pricing_date_usd` once per opportunity, in USD, at either grain. It supports totals and groupings by opportunity-level fields such as `stage_group`, `opportunity_owner`, or `first_channel`; a product filter selects the matching opportunities and still counts each once. A deal-size breakdown by product fields, or a deal-size measure in the per-SKU detail table, is rejected by the engine, and the planner is instructed to ask a clarification instead; product breakdowns use `amount`. Plans saved by earlier releases remain valid.

Filters run on canonical rows after aggregation. An opportunity-grain product filter selects complete matching opportunities, including all their SKU values. SKU grain computes values only for the matching SKU rows. Ambiguous scope should produce a clarification. Date filters use `YYYY-MM-DD`; probability filters use fractions such as `0.75`.

Stage filters expand the canonical groups:

| Group | Included stages |
| --- | --- |
| Won | Won, Rollout Started, Rollout Finished |
| Open | Identified, Qualified, Negotiation |
| Lost | Dropped, Lost |

Use `stage_group` for grouped reporting. `context_action=refine` retains omitted settings, replaces existing filters on the same field, and honors `remove_filters`. Explicit empty lists clear dimensions/measures/sort; `replace` starts a fresh query. The server owns the active plan, so the browser cannot substitute its own conversation context. A clarification does not erase the last completed query.

Greetings, small talk, and questions outside the opportunity data are answered as clarifications: the planner is instructed to return `intent: clarify` with example questions as suggestions, and a model reply that contains no JSON object at all is shown as the model's own words (trimmed to 300 characters) instead of a parse error. A reply that contains malformed or off-contract JSON still stops the request with the validation problem named.

Arbitrary SQL, Python, expressions, and script paths are not execution options. This limits what a model plan can do; it does not guarantee that a model will interpret every business question correctly. Representative work questions and expected results remain the next evaluation input.

Edit `business_rules.md` for local vocabulary supplements. The engine's canonical formulas remain fixed. The v0.1 example `schema.json`, if present, is preserved but no longer used; the supplied Salesforce schema supersedes it. Review any old example business-rule prose when upgrading.

## Standardized live-data acceptance test

The **Run acceptance test** action in Workspace details runs a versioned suite of 54 predefined prompt turns (36 independent questions and three six-turn conversations) plus 12 browser checks, and produces one Markdown report to paste into a review. The suite tests three things separately: **interpretation** (did the model understand filters, grain, grouping, and follow-ups), **data correctness** (does every returned value match an independent calculation from the raw source), and **presentation** (does the browser display, sort, export, and chart the results correctly).

The run freezes one snapshot first: the raw relation is read in a single read-only, repeatable-read transaction, the app's canonical grains and an independent reference are built from it, and every case uses that same snapshot regardless of cache expiry, refreshes, or database changes. The report records the snapshot timestamp, relation name, row and key counts, currency distribution, normalization warnings, order-independent source fingerprints (`fp1`) that preserve duplicate multiplicity, the app revision, suite version, business-rule digest, model identity and settings, and the effective date. Owners, customers, products, duplicate pairs, thresholds, and a nonexistent identifier are selected deterministically from the frozen source before any model call, and every substituted value is listed. Missing examples produce **blocked** coverage checks, never empty-result passes.

Expected results come from `reference_evaluator.py`, a separate Decimal implementation of the rules that calls none of the production canonicalization, filtering, aggregation, or follow-up merging code. Each case's authored expectation (in `acceptance_suite.py`) is compared with the effective plan, accepting documented equivalents such as a Won stage-group filter versus its member stages; the reference result is computed from the authored expectation, never from the plan the model returned. Every returned row and cell is compared, together with complete counts, totals, and full-result digests (`digest1`) before the 1,000-row preview limit. Numbers are compared exactly; the only tolerance is the documented 0.01 parent-amount rule.

Test conversations live in a separate store under `B2B_DATA_DIR/acceptance` and never appear among saved conversations; the test panel leaves the user's current question and result untouched. Independent cases use fresh conversations; the three follow-up scenarios share their own. A failed case does not stop unrelated cases; a failed turn that makes later follow-ups impossible marks them **blocked**. Cancel, browser reload (Resume), and an application restart all still yield a partial report. Ordinary questions and test steps go through the same `QueryService` path and the same model-call lock; step requests are idempotent and carry no prompts, plans, SQL, or paths.

The Markdown report (`b2b-test-<timestamp>-<run-id>.md`, downloaded from the panel) contains the run identity and source, a scorecard with failed and blocked checks, per-case evidence (prompt, layout, conversation, expected behavior, returned plan, effective plan, expected versus actual counts, totals, digests, rows, chart specification, assertion outcomes, timings, and keyed differences), the browser observations with expected plot coordinates and recorded drawing operations, a comparison with the previous run (newly failing, fixed, inconsistent cases; source, prompt, rule, app, or model-setting changes; result and latency differences; eligibility for the same three-pass sequence), and review instructions including the CSV header mapping and fingerprint algorithm.

The header shows **Ready for review** only after three consecutive complete full passes with matching source fingerprint, app revision, suite version, business-rule digest, model configuration, and effective date. Failed, blocked, interrupted, cancelled, or missing browser checks prevent qualification; a failed-case-only rerun (`only_failed_from`) helps diagnosis but never counts; any relevant change restarts the sequence. Changed expectations require a reviewed suite revision. Final delivery still follows the reviewer's independent recomputation against the local CSV and a visual review of the charts in the app. Rare conditions absent from the live source, such as mixed currencies or malformed numbers, are covered by development fixtures and are not claimed as exercised by the live run.

By default the suite tests the configured source (the live PostgreSQL relation in production) with the configured model; it also runs against a CSV file, which is how the suite itself is exercised in CI with a scripted model. [migrations/002_legacy_views_unpadded_dates_and_added_columns.sql](migrations/002_legacy_views_unpadded_dates_and_added_columns.sql) optionally refreshes the legacy derived views so that other consumers parse one- and two-digit day-first dates and expose the four added columns exactly like the app; the app itself does not read those views, and applying the migration remains an operator step with a migration-capable role.

## Responsiveness and freshness

The FastAPI process, SQL connection pool, and conversation store stay alive. A canonical data snapshot is cached in memory for `B2B_CACHE_SECONDS` (default 60). Queries reuse a fresh snapshot; **Refresh data** forces a new one, after which the displayed answer is marked as awaiting a rerun with an **Update this answer** action. Failed refreshes report an error, keep the previous answer with its original load time, and invalidate the cache. Tables display the snapshot load time, not an inferred Salesforce refresh timestamp.

Browser sorting affects displayed rows only. CSV exports those displayed rows. Chart controls do not call SQL or Qwen, and charts display at most 30 groups. The result preview limit is applied after complete filtering/aggregation/sorting, with visible truncation information.

## People, history, and the access log

The page is a chat: conversations on the left, messages with their tables and charts in the middle, and the question box at the bottom. On first visit each person enters their name (`B2B_IDENTITY=name`, the default); the name is kept in a signed cookie and every conversation is scoped to it. `B2B_IDENTITY=windows` uses the signed-in Windows user instead, for a single-person PC on loopback. A corporate reverse proxy can still supply the identity header with the shared secret described in `.env.example`; that header wins when present.

Everything lives in the local SQLite file `data\history.sqlite3` in the install folder: each person's conversations with every question, the model's raw reply, the effective plan, and the answer summary; the `logins` table with name, IP address, browser, and time for every sign-in; and the `activity` table with owner, IP address, and time for every question, preview, re-shown result, deletion, and acceptance run. `GET /api/access-log` returns the recent entries. Result rows and credentials are never stored; an earlier answer's table is recomputed from its plan when re-shown.

The app listens on loopback by default. Set `B2B_LISTEN_HOST=0.0.0.0` to let colleagues open `http://<this-pc>:8765`; requests must then be same-origin on the app port, and the name prompt identifies each person. The installer does not change firewall rules, install services, or expose a public listener. History is scoped by name, not by Salesforce authorization: the SQL source is shared for this team.

## Updates and rollback

Run `update_app.ps1` from the install folder to update: it stops the running app, runs `setup.ps1`, and starts the new release in a new window (`-NoRestart` skips the restart). Rerunning `setup.ps1` alone also works. `tools/apply_update.ps1` accepts an exact 40-character commit for controlled deployment. Setup stages a separate release, reuses or downloads its pinned dependencies, runs regression/API checks, verifies the release/configuration, then atomically selects it. Existing `.env`, business rules, and the data/history folder survive updates. Stop the running app with Ctrl+C and run `start.ps1` again to use the new release.

For an existing v0.2 installation, first replace its `setup.ps1` with the current repository copy once. That older bootstrap predates the GitHub asset lock and same-run installer refresh. Subsequent refreshes use the updated script automatically.

Old release directories and `previous.json` are retained. Stop the app, use the portable interpreter to run `updater.py --home <install-folder> --rollback`, then run `start.ps1`. Rollback validates that pointer targets remain inside this installation and never rewrites history. No unattended polling, arbitrary remote execution, or local PyInstaller compilation is required.

Offline installation uses `-LocalSource`, `-Offline`, and `-DownloadCache` containing the exact Python ZIP and wheel files named in the locks. Populate that cache during an online setup first. Qwen/model files are managed separately on the internal model host.

## Development and validation

`run.py --self-test` runs the test suite with the portable interpreter and app-local vendor packages. `scripts/lock_dependencies.py` is a maintainer-only refresh of explicitly pinned versions, not a runtime resolver. `release_manifest.json` locks the application version, query plan version, the app's canonical data schema version (`data_schema_version`, 2 for the 30-column schema), dependency digest, and Python ABI. No database version ledger is consulted. Version 0.4 changes no dependencies, so existing portable archives are reused and updates keep local configuration and data.

When changing dependency versions, run `scripts/lock_dependencies.py`, then `scripts/publish_portable_assets.py` on a development machine with an authenticated GitHub CLI. The latter mirrors the original, verified wheels and runtime ZIP to a release named by their combined hashes; it does not rebuild or modify the archives. Publish the assets before promoting the matching code to `main`. Existing assets are checked and skipped. The manual **Publish portable dependency archives** Actions workflow provides the same publishing command. App-only updates can run `scripts/release_metadata.py` to refresh manifest versions without fetching package metadata or creating a new dependency release.

CI runs on Windows with the packaged dependencies, checks that an all-text raw table in disposable localhost PostgreSQL and an equivalent CSV file produce identical tables and totals, exercises a real role with raw-table SELECT access only, and checks folder installation, offline dependency reuse, clean source replacement, local-data preservation, and rollback. Integration tests never use `PGURL`; they require the separate `B2B_TEST_PGURL` setting and refuse non-loopback hosts. All committed fixtures are invented; the suite passes without the supplied sample.

To check the supplied sample export on a machine that holds it, set `B2B_SAMPLE_CSV_PATH` (and `B2B_SAMPLE_CSV_ENCODING` if needed) before `run.py --self-test`. That opt-in test expects 307 input rows to produce 112 opportunities and 305 opportunity/SKU rows. The file itself stays local and Git-ignored.

The source layout follows the manual's backend module boundaries (`app_config`, `data_layer`, `query_models`, `query_engine`, `history_store`, `ui_app`, `updater`). The UI and deployment packaging intentionally use FastAPI/static assets and portable archives, following the architecture discussion. See [remaining integration inputs](docs/intake.md).
