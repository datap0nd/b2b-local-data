# B2B Local Data

A local Qwen question-to-table app for a Salesforce extract already loaded into SQL.
Ask a question, answer a clarification if needed, and get an opportunity summary or opportunity/SKU detail table.

**Status: runnable starter with fictional data.** The original internal scripts, actual schema, and final business definitions have not been supplied yet. No work-PC SQL or Qwen connection has been tested. Start with [the intake checklist](docs/intake.md).

## What is included

- A small browser interface, follow-up questions, table preview, and CSV export of the displayed rows.
- Local Qwen through Ollama or an OpenAI-compatible local server such as vLLM or LM Studio.
- PostgreSQL and Windows SQL Server adapters, plus an in-memory SQLite demonstration dataset.
- An editable column map and deterministic summary/detail rules. Qwen returns a restricted JSON plan; the application compiles parameterized SELECTs and runs the selected table builder.
- Portable Windows setup/update using downloaded archives. No pip, global Python package installation, admin elevation, service registration, or Git installation on the work PC.

The starter focuses on the two requested table layouts. Rankings, arbitrary groupings, computed metrics, OR filters, aggregate filters, automatic scheduled updates, Windows service hosting, and team authentication remain integration work. Unsupported questions should prompt a clarification; model interpretation still needs evaluation using your real question examples.

## Try it from a checkout

With Python 3.13 available:

```powershell
python run.py
```

Open <http://127.0.0.1:8765> and click **Summary table** or **Detailed table**. These buttons use fictional data and do not require Qwen or database credentials.

```powershell
python run.py --self-test
```

The first fictional opportunity has three source lines, two SKUs, quantity 4, product-line value 750, and repeated opportunity value 750. Summary must show 750, not 2,250. Detail combines the two rows for SKU-A into quantity 3 and line value 600.

## Install or update on the work PC

Download `setup.ps1` from this repository and run it in PowerShell:

```powershell
.\setup.ps1 -InstallDir "$env:LOCALAPPDATA\B2BLocalData"
```

The repository is private by default. Set `B2B_GITHUB_TOKEN` in the setup process environment if GitHub downloads need authentication. Use a token able to read this repository; it is not stored in the app's configuration or sent to Qwen. A ZIP downloaded in an authenticated browser can instead be extracted and used with `-LocalSource`.

Setup resolves the requested GitHub ref to an exact commit, stages a new release, downloads and verifies the pinned Python archive and pure-Python wheels, unpacks dependencies into that release's `vendor` directory, and runs the tests. Only a passing release becomes current. It preserves `.env`, `schema.json`, and `business_rules.md` in the install folder. Rerun the same setup script to update.

Run `start.ps1` in the install folder. Stop a running app with Ctrl+C and restart it after updating. This first version uses an interactive local process; it does not restart existing processes or install a background service.

To install from an extracted source folder:

```powershell
.\setup.ps1 -LocalSource . -InstallDir "$env:LOCALAPPDATA\B2BLocalData"
```

An offline install uses `-LocalSource`, `-Offline`, and `-DownloadCache` pointing to a folder containing the exact Python ZIP and wheel files named in the lock files. Populate that cache during an online setup first. Qwen runtime/model files are separate and must already be available on the work PC or internal model host.

## Work-PC settings

Keep a `.env` file in the install folder. This is ordinary local text, not an encrypted secret store; protect it with the work PC's normal Windows file permissions. The repository ignores it. Environment variables override entries in this file, so service-account settings can be used later without changing code. Values are literal, optionally quoted; there is no variable expansion.

For an Ollama model:

```dotenv
AI_PROVIDER=ollama
AI_BASE_URL=http://127.0.0.1:11434
AI_MODEL=your-exact-installed-qwen-model-name
```

For the same type of local Qwen server used by the data-governance project:

```dotenv
AI_PROVIDER=openai_compatible
AI_BASE_URL=http://YOUR_INTERNAL_QWEN_HOST:8000/v1
AI_MODEL=your-exact-served-model-name
```

The endpoint must resolve to loopback or a private network address. HTTP proxies and redirects are disabled for model requests. The model must support the configured structured-output protocol. Use a locally hosted model; a private endpoint can itself forward requests elsewhere, so its configuration remains the operator's responsibility. Gemini/cloud fallback is not implemented.

Only questions, conversation context, logical column descriptions, and business rules are sent to Qwen. Result rows and SQL credentials are kept out of the model request. SQL returns matching rows to the local app, which computes the tables with decimal arithmetic.

### PostgreSQL

```dotenv
DB_KIND=postgres
DB_HOST=your-internal-server
DB_PORT=5432
DB_NAME=your-database
DB_USER=your-read-only-user
DB_PASSWORD=your-password
DB_SSL=true
DB_CA_FILE=
```

Set an absolute `DB_CA_FILE` path if your database uses an internal CA not trusted by the runtime. TLS verifies the server certificate by default. The adapter sets a read-only transaction and a statement timeout. The pinned pg8000 packages are unpacked by setup. In a developer checkout, use `python scripts/vendor_dependencies.py` once.

### SQL Server on Windows

```dotenv
DB_KIND=sqlserver
DB_HOST=your-internal-server
DB_PORT=1433
DB_NAME=your-database
DB_AUTH=windows
DB_SSL=true
```

Alternatively set `DB_AUTH=password`, `DB_USER`, and `DB_PASSWORD`. Windows authentication uses the account running the application. Clear `DB_PORT` when using a named instance in `DB_HOST`. The fixed PowerShell adapter uses Windows' .NET SQL client, so no Python SQL Server package or system ODBC installation is required. Windows PowerShell script execution must be allowed by workplace policy. TLS certificate validation remains enabled; internal certificate trust is managed by Windows. Azure/Entra and other specialized auth flows are not implemented.

Use a database account with SELECT access to the intended view/table. SQL Server's `ApplicationIntent=ReadOnly` is a connection hint, not a permission restriction.

## Column mapping and business rules

Copy `config/schema.example.json` to `schema.json` in the install folder (setup does this only if the file is absent). Set `table` as separate identifier parts, for example `["dbo", "YourExtract"]`, and map each logical column's `source` to its actual SQL column. Names with spaces are supported. No real column names are assumed by the starter.

Each field has a type and a level: `opportunity` or `product`. Each view selects a reducer: `sum` for additive product-line numbers, `join` for distinct text values, or `unique` for a value that must agree across the group. Opportunity-level fields cannot use `sum`.

- Summary: one row per opportunity; combine product names/SKUs and sum only explicitly additive fields.
- Detail: one row per opportunity and SKU; repeated SKU lines are summed in the example. Confirm the true source grain and snapshot policy before enabling real data.
- Opportunity amounts, dates, owners, and currency must agree across an opportunity's selected lines. Conflicts stop the query.
- Null numeric inputs produce an unknown total rather than treating missing values as zero.
- Filters apply to source rows before aggregation. For product filters, choose matching rows only or all lines from matching opportunities. An unspecified scope triggers a follow-up.
- Text matching follows the database collation. It is case-sensitive in the demo/PostgreSQL path by default; SQL Server follows the source collation.
- Default source cap: 100,000 rows. Exceeding it stops the query so totals cannot be partial. The display limit, at most 1,000 rows, is applied after complete aggregation and is visibly labeled. CSV exports only those displayed rows.

Edit `business_rules.md` beside `.env` to add business vocabulary, stage mappings, date conventions, and approved examples. After changing local configuration, restart the app. Arbitrary model-generated SQL, Python, or script paths are never executed. Existing Python scripts can be integrated as named, reviewed operations once supplied.

## Deployment layout

```text
B2BLocalData/
  .env                       local connection/model settings
  schema.json                actual column map and aggregation rules
  business_rules.md          local business vocabulary
  current.json               active release and runtime paths
  previous.json              prior release pointer after an update
  setup.ps1                  setup/update entry point
  start.ps1                  launcher
  releases/<commit>-<id>/     versioned application and vendor files
  runtime/python-<version>/   portable runtime
  .downloads/                reusable verified downloads
```

Old releases are retained. To roll back, stop the app, copy `previous.json` over `current.json`, then run `start.ps1`. Do not edit generated pointer paths to untrusted locations. Setup never deletes old releases automatically. The app binds to `127.0.0.1`; LAN access, team sign-in, and unattended hosting should be decided from your existing deployment scripts before exposing it to colleagues.

## Reference material

- [Existing data-governance setup](https://github.com/datap0nd/data_governance/blob/main/setup.ps1): reference for portable installation and exact-commit updates; this starter does not copy its machine-specific paths or service setup.
- [Python embedded distribution](https://docs.python.org/3.13/using/windows.html#the-embeddable-package).
- [Ollama chat API](https://docs.ollama.com/api/chat).
- [pg8000 driver](https://pypi.org/project/pg8000/).
- [SQL Server application intent](https://learn.microsoft.com/en-us/dotnet/api/system.data.sqlclient.applicationintent?view=netframework-4.8.1).
