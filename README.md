# B2B Salesforce Query Agent

Ask a locally hosted Qwen model about the Salesforce extract in PostgreSQL. The model produces a validated `QueryPlanV1`; a deterministic engine returns opportunity/SKU tables, metrics, and charts.

Version 0.3 implements the supplied replication manual with a **FastAPI backend and a browser frontend**, plus a folder-based GitHub installer. Sorting, chart controls, and layout selection stay in the browser. Queries call the backend explicitly; ordinary clicks do not rerun Python. Qwen/model latency and database refresh time remain separate from UI interactions.

## Current state

The canonical schema, normalization, amount formulas, stage mappings, query contract, local history, and database fallback are implemented. Tests use fictional data and a disposable PostgreSQL instance in CI. The work PC's actual database and Qwen endpoint still need a configured connection test. No credentials from the supplied manual are committed.

## Install and start on Windows

Download and extract this repository into the folder you want to use on the work PC. Keep that folder between updates. Copy `.env.example` to `.env` and set `B2B_GITHUB_TOKEN` to a GitHub token with **Contents: read** access to this private repository. You can instead provide it as a process environment variable. SQL and Qwen settings can be filled in when ready; the defaults use fictional demo data.

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

Edit `.env` **in the install folder**, not in a versioned release. Environment variables override file settings. Values are literal, optionally quoted; no shell expansion occurs. The file is ordinary local text, ignored by Git, and should use your normal Windows file permissions.

The supplied replication manual explicitly included `.env` configuration and the `PGURL`, `RO_SQL_USER`, `RO_SQL_PW`, `LLM_API_URL`, `LLM_API_KEY`, and `LLM_MODEL_NAME` names used below. It also included the `B2B_DATA_DIR`, `B2B_INSTALL_ROOT`, and identity-header settings. `B2B_GITHUB_TOKEN` is an addition for this private-repository installer and is never sent to SQL or Qwen.

```dotenv
B2B_GITHUB_TOKEN=your-github-read-token
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

A blank `DB_KIND` selects PostgreSQL when `PGURL` is present, otherwise fictional demo data. `DB_KIND=demo` explicitly stays in demo mode. The old `DB_HOST`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` and `AI_*` settings are accepted for existing installations; set `DB_KIND=postgres` with old database variables.

Both complete `/v1/chat/completions` URLs and base URLs ending in `/v1` work. For Ollama, set `AI_PROVIDER=ollama`, its local URL in `LLM_API_URL`, and the exact installed model name. Internal servers using a public-range address require that exact hostname/IP in `B2B_LLM_ALLOWED_HOSTS`. This supports corporate routing without broadly allowing public endpoints. The operator must ensure the endpoint really hosts the local model. Redirects and HTTP proxy forwarding are disabled for model requests; there is no Gemini/cloud fallback.

SQL uses certificate validation by default. If needed, point `DB_CA_FILE` to an internal CA certificate. The application uses a read-only transaction, a statement timeout, and a maximum row bound. Its credentials need SELECT access, not migration privileges.

`B2B_DATA_DIR` defaults to `<install-folder>/data`. It contains SQLite conversation history. Questions, clarification responses, and validated plans are saved; result rows and credentials are not. Questions themselves can contain business information, so this folder belongs on the work PC. A saved conversation can be reopened and its query rerun against the current data.

## Data contract

The expected raw source is `bi_reporting.b2b_project`, using the exact columns in the supplied manual. To change relation names, use `B2B_RAW_TABLE`, `B2B_SKU_VIEW`, `B2B_OPPORTUNITY_VIEW`, and `B2B_SCHEMA_VERSION_TABLE`. Each uses `schema.relation` notation.

| Grain | Key | Amount |
| --- | --- | --- |
| SKU | `opportunity_no`, `product_code` | Sum of `amount_converted` for that pair |
| Opportunity | `opportunity_no` | Sum of its canonical SKU amounts |

Text follows the supplied PostgreSQL `btrim` behavior: surrounding spaces are removed, empty strings become null. Numeric strings must match the manual's decimal pattern; malformed values become null. Probability is divided by 100, with an optional `%` suffix. Raw dates use `DD/MM/YYYY`; invalid calendar dates become null in both paths.

SQL-style reductions ignore null inputs. A sum with only null inputs stays null. Exported parent opportunity amounts are retained as min/max checks, never added as a measure. Amount discrepancy is true when the parent min/max differ, when the required comparison is unknown, or when the SKU total differs from the parent by more than 0.01. Metadata conflicts use the manual's specified quality fields, deterministic MIN/MAX selection, and visible warnings. These flags do not stop the table.

The optional [canonical-view migration](migrations/001_canonical_views.sql) creates the two views and the version ledger. Apply it manually with a migration-capable role; the app and installer do not run DDL against the work database. It uses guarded date parsing and explicit C collation so the local and SQL paths agree on invalid dates and text ordering.

The repository reads both views within one repeatable-read snapshot. Missing or denied views/version metadata cause a savepoint rollback and reconstruction from the raw table. Connection failures, timeouts, incompatible schema versions, missing columns, and oversized results stop the request rather than being hidden by fallback. The source cap defaults to 100,000 rows; partial inputs are never reported as complete totals.

The source must contain the intended current extract. No historical snapshot de-duplication is invented. Rows without an opportunity number or product code are excluded, as in the supplied SQL.

## Queries and follow-ups

The Pydantic contract forbids unknown fields and supports:

- Intents: table, metric, chart, clarify.
- Grains: opportunity and opportunity_sku.
- Filters: eq, ne, gt, ge, lt, le, contains, in, between. Filters are ANDed.
- Measures: amount, quantity, sku_count, opportunity_count.
- Up to ten selected/grouping dimensions, three sort fields, and a 1,000-row result preview.
- Bar, line, area, and scatter charts, with exact values also available in a table.

For **tables**, dimensions select columns and business keys remain included. For **metrics/charts**, dimensions group rows. Opportunity count counts distinct opportunity identifiers even at SKU grain. SKU count counts opportunity/SKU pairs, not globally distinct product codes. Mixed-currency amount metrics require a currency grouping or filter.

Filters run on canonical rows after aggregation. An opportunity-grain product filter selects complete matching opportunities, including all their SKU values. SKU grain computes values only for the matching SKU rows. Ambiguous scope should produce a clarification. Date filters use `YYYY-MM-DD`; probability filters use fractions such as `0.75`.

Stage filters expand the canonical groups:

| Group | Included stages |
| --- | --- |
| Won | Won, Rollout Started, Rollout Finished |
| Open | Identified, Qualified, Negotiation |
| Lost | Dropped, Lost |

Use `stage_group` for grouped reporting. `context_action=refine` retains omitted settings, replaces existing filters on the same field, and honors `remove_filters`. Explicit empty lists clear dimensions/measures/sort; `replace` starts a fresh query. The server owns the active plan, so the browser cannot substitute its own conversation context. A clarification does not erase the last completed query.

Arbitrary SQL, Python, expressions, and script paths are not execution options. This limits what a model plan can do; it does not guarantee that a model will interpret every business question correctly. Representative work questions and expected results remain the next evaluation input.

Edit `business_rules.md` for local vocabulary supplements. The engine's canonical formulas remain fixed. The v0.1 example `schema.json`, if present, is preserved but no longer used; the supplied Salesforce schema supersedes it. Review any old example business-rule prose when upgrading.

## Responsiveness and freshness

The FastAPI process, SQL connection pool, and conversation store stay alive. A canonical data snapshot is cached in memory for `B2B_CACHE_SECONDS` (default 60). Queries reuse a fresh snapshot; **Refresh data** forces a new one. Failed refreshes report an error and invalidate the cache. Tables display the snapshot load time, not an inferred Salesforce refresh timestamp.

Browser sorting affects displayed rows only. CSV exports those displayed rows. Chart controls do not call SQL or Qwen, and charts display at most 30 groups. The result preview limit is applied after complete filtering/aggregation/sorting, with visible truncation information.

## Identity and hosting

The app listens on loopback and supports the current local Windows user's identity when `B2B_ALLOW_LOCALHOST_IDENTITY=true`. For a corporate reverse proxy, set the authenticated user header, exact trusted proxy addresses, a shared secret of at least 32 characters, and `B2B_PUBLIC_ORIGIN`. The proxy must inject `X-B2B-Proxy-Secret`, overwrite the configured user header, and strip incoming copies. Set localhost identity to false for a proxy-only deployment. Arbitrary browser-supplied user headers are not trusted.

History is scoped by authenticated identity. The SQL source is shared for this team; this is not per-user Salesforce row-level authorization. TLS termination and the actual corporate sign-in mechanism remain deployment configuration. The installer does not change firewall rules, install services, or expose a public listener.

## Updates and rollback

Rerun `setup.ps1` or `update_app.ps1` from your original install folder. `tools/apply_update.ps1` accepts an exact 40-character commit for controlled deployment. Setup stages a separate release, reuses or downloads its pinned dependencies, runs regression/API checks, verifies the release/configuration, then atomically selects it. Existing `.env`, business rules, and the data/history folder survive updates. Stop the running app with Ctrl+C and run `start.ps1` again to use the new release.

For an existing v0.2 installation, first replace its `setup.ps1` with the current repository copy once. That older bootstrap predates the GitHub asset lock and same-run installer refresh. Subsequent refreshes use the updated script automatically.

Old release directories and `previous.json` are retained. Stop the app, use the portable interpreter to run `updater.py --home <install-folder> --rollback`, then run `start.ps1`. Rollback validates that pointer targets remain inside this installation and never rewrites history. No unattended polling, arbitrary remote execution, or local PyInstaller compilation is required.

Offline installation uses `-LocalSource`, `-Offline`, and `-DownloadCache` containing the exact Python ZIP and wheel files named in the locks. Populate that cache during an online setup first. Qwen/model files are managed separately on the internal model host.

## Development and validation

`run.py --self-test` runs the test suite with the portable interpreter and app-local vendor packages. `scripts/lock_dependencies.py` is a maintainer-only refresh of explicitly pinned versions, not a runtime resolver. `release_manifest.json` locks the application, query plan, schema, dependency digest, and Python ABI.

When changing dependency versions, run `scripts/lock_dependencies.py`, then `scripts/publish_portable_assets.py` on a development machine with an authenticated GitHub CLI. The latter mirrors the original, verified wheels and runtime ZIP to a release named by their combined hashes; it does not rebuild or modify the archives. Publish the assets before promoting the matching code to `main`. Existing assets are checked and skipped. The manual **Publish portable dependency archives** Actions workflow provides the same publishing command. App-only updates can run `scripts/release_metadata.py` to refresh manifest versions without fetching package metadata or creating a new dependency release.

CI runs on Windows with the packaged dependencies, checks SQL/Pandas parity against disposable localhost PostgreSQL, exercises a real role with raw-table SELECT access only, and checks folder installation, offline dependency reuse, clean source replacement, local-data preservation, and rollback. Integration tests never use `PGURL`; they require the separate `B2B_TEST_PGURL` setting and refuse non-loopback hosts.

The source layout follows the manual's backend module boundaries (`app_config`, `data_layer`, `query_models`, `query_engine`, `history_store`, `ui_app`, `updater`). The UI and deployment packaging intentionally use FastAPI/static assets and portable archives, following the architecture discussion. See [remaining integration inputs](docs/intake.md).
