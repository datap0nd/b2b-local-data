import json
import os
import sqlite3
import ssl
import subprocess
from datetime import date
from decimal import Decimal

from app.config import AppError, ROOT


def identifier(value, dialect):
    if dialect == "sqlserver":
        return "[" + value.replace("]", "]]") + "]"
    return '"' + value.replace('"', '""') + '"'


def compile_query(schema, plan, dialect, cap):
    """Only identifiers from local configuration enter SQL; all values are parameters."""
    q = lambda name: identifier(name, dialect)
    table = ".".join(q(x) for x in (["salesforce_extract"] if dialect == "demo" else schema["table"]))
    columns = schema["columns"]
    parameters = []

    def conditions(alias):
        clauses = []
        for item in plan["filters"]:
            spec, op, value = columns[item["column"]], item["op"], item["value"]
            col = alias + "." + q(spec["source"])
            if op in ("is_null", "not_null"):
                clauses.append(col + (" IS NULL" if op == "is_null" else " IS NOT NULL"))
                continue
            slot = "%s" if dialect == "postgres" else (f"@p{len(parameters)}" if dialect == "sqlserver" else "?")
            if op == "contains":
                value = "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                if dialect == "sqlserver":
                    value = value.replace("[", "\\[")
                clauses.append(f"{col} LIKE {slot} ESCAPE '\\'")
            else:
                operator = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
                clauses.append(f"{col} {operator} {slot}")
            parameters.append({"value": value, "type": spec["type"]})
        return " AND ".join(clauses) or "1=1"

    selected = ", ".join(f"src.{q(spec['source'])} AS {q(name)}" for name, spec in columns.items())
    if plan["product_scope"] == "whole_opportunities" and plan["filters"]:
        key = q(columns[schema["opportunity_key"]]["source"])
        where = f"EXISTS (SELECT 1 FROM {table} AS matched WHERE matched.{key} = src.{key} AND {conditions('matched')})"
    else:
        where = conditions("src")
    prefix = f"TOP ({cap + 1}) " if dialect == "sqlserver" else ""
    suffix = "" if dialect == "sqlserver" else f" LIMIT {cap + 1}"
    return f"SELECT {prefix}{selected} FROM {table} AS src WHERE {where}{suffix}", parameters


def demo_connection():
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA case_sensitive_like=ON")
    con.execute("CREATE TABLE salesforce_extract (opportunity_number TEXT, account_name TEXT, owner_name TEXT, stage TEXT, close_date TEXT, currency TEXT, sku TEXT, product_name TEXT, quantity NUMERIC, line_value NUMERIC, opportunity_value NUMERIC)")
    con.executemany("INSERT INTO salesforce_extract VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        ("OPP-001", "Example North", "Alex", "Proposal", "2026-10-15", "EUR", "SKU-A", "Monitor", 2, 400, 750),
        ("OPP-001", "Example North", "Alex", "Proposal", "2026-10-15", "EUR", "SKU-B", "Dock", 1, 150, 750),
        ("OPP-001", "Example North", "Alex", "Proposal", "2026-10-15", "EUR", "SKU-A", "Monitor", 1, 200, 750),
        ("OPP-002", "Example West", "Blair", "Closed Won", "2026-09-01", "EUR", "SKU-B", "Dock", 3, 450, 450),
        ("OPP-003", "Example East", "Alex", "Qualification", "2026-11-20", "USD", "SKU-C", "Laptop", 2, 2400, 2400)
    ])
    con.commit()
    con.execute("PRAGMA query_only=ON")
    return con


def fetch_rows(settings, plan):
    dialect = settings.get("DB_KIND", "demo")
    if dialect not in ("demo", "postgres", "sqlserver"):
        raise AppError("DB_KIND must be demo, postgres, or sqlserver.")
    cap = settings.number("MAX_SOURCE_ROWS", 100000, high=1000000)
    timeout = settings.number("DB_TIMEOUT_SECONDS", 30, high=300)
    sql, parameters = compile_query(settings.schema, plan, dialect, cap)
    con = None
    try:
        if dialect == "sqlserver":
            if os.name != "nt":
                raise AppError("The SQL Server adapter requires Windows PowerShell. Paste your existing adapter if the PC uses another connection method.")
            shell = os.path.join(os.environ["SystemRoot"], "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
            payload = {"sql": sql, "parameters": parameters, "timeout": timeout,
                       "connection": {k: settings.get(k) for k in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_AUTH", "DB_SSL")}}
            result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(ROOT / "scripts/read_sqlserver.ps1")],
                input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", timeout=timeout + 15,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise AppError("SQL Server connection/query failed. Check credentials, SELECT access, TLS, schema, and Windows PowerShell policy.")
            rows = json.loads(result.stdout)
        else:
            if dialect == "demo":
                con = demo_connection()
                args = [p["value"] for p in parameters]
            else:
                try:
                    import pg8000.dbapi
                except ImportError:
                    raise AppError("PostgreSQL driver is missing. Run setup.ps1 or scripts/vendor_dependencies.py; no pip is needed.") from None
                context = ssl.create_default_context(cafile=settings.get("DB_CA_FILE") or None) if settings.get("DB_SSL", "true").lower() == "true" else False
                con = pg8000.dbapi.connect(host=settings.get("DB_HOST"), port=settings.number("DB_PORT", 5432, high=65535),
                    database=settings.get("DB_NAME"), user=settings.get("DB_USER"), password=settings.get("DB_PASSWORD"),
                    ssl_context=context, timeout=timeout)
                args = [Decimal(str(p["value"])) if p["type"] == "number" else date.fromisoformat(p["value"]) if p["type"] == "date" else p["value"] for p in parameters]
            cursor = con.cursor()
            if dialect == "postgres":
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(f"SET LOCAL statement_timeout = {timeout * 1000}")
            cursor.execute(sql, args)
            names = [column[0] for column in cursor.description]
            rows = [dict(zip(names, row)) for row in cursor.fetchmany(cap + 1)]
        if len(rows) > cap:
            raise AppError(f"More than {cap:,} source rows match. Add a filter; partial totals would be misleading.")
        return rows
    except AppError:
        raise
    except Exception:
        raise AppError("Database read failed. Check the configured driver, connection, column names, and source types.") from None
    finally:
        if con is not None:
            con.close()
