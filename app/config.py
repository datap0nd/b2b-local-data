from dataclasses import dataclass
import json
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


class AppError(Exception):
    """A message safe to display without credentials or raw database errors."""


def read_env(path):
    values = {}
    if not path.exists():
        return values
    for index, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise AppError(f"Invalid .env entry at line {index}.")
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        values[key] = value
    return values


@dataclass
class Settings:
    home: Path
    values: dict
    schema: dict
    rules: str

    @classmethod
    def load(cls, home):
        home = Path(home).resolve()
        values = read_env(ROOT / ".env.example") | read_env(home / ".env") | dict(os.environ)
        schema_path = home / "schema.json"
        rules_path = home / "business_rules.md"
        if values.get("DB_KIND", "demo") != "demo" and not schema_path.exists():
            raise AppError("Create schema.json with your actual table and column mapping before connecting SQL.")
        schema = json.loads((schema_path if schema_path.exists() else ROOT / "config/schema.example.json").read_text(encoding="utf-8-sig"))
        rules = (rules_path if rules_path.exists() else ROOT / "config/business_rules.example.md").read_text(encoding="utf-8-sig")
        validate_schema(schema)
        return cls(home, values, schema, rules)

    def get(self, key, default=""):
        return self.values.get(key, default)

    def number(self, key, default, low=1, high=100000):
        try:
            value = int(self.get(key, str(default)))
        except ValueError:
            raise AppError(f"{key} must be an integer.") from None
        if not low <= value <= high:
            raise AppError(f"{key} must be between {low} and {high}.")
        return value


def validate_schema(schema):
    try:
        columns = schema["columns"]
        assert isinstance(columns, dict) and 1 <= len(columns) <= 100
        assert isinstance(schema["table"], list) and 1 <= len(schema["table"]) <= 3
        assert all(isinstance(x, str) and x and "\x00" not in x for x in schema["table"])
        assert schema["opportunity_key"] in columns
        assert schema["product_key"] in columns
        for name, spec in columns.items():
            assert re.fullmatch(r"[a-z][a-z0-9_]*", name)
            assert isinstance(spec["source"], str) and spec["source"] and "\x00" not in spec["source"]
            assert spec["type"] in ("text", "number", "date")
            assert spec["level"] in ("opportunity", "product")
        for mode in ("summary", "detail"):
            view = schema["views"][mode]
            assert view["keys"] == ([schema["opportunity_key"]] if mode == "summary" else [schema["opportunity_key"], schema["product_key"]])
            assert all(k in view["columns"] for k in view["keys"])
            for name, reducer in view["columns"].items():
                assert name in columns and reducer in ("unique", "join", "sum")
                if reducer == "sum":
                    assert columns[name]["type"] == "number" and columns[name]["level"] == "product"
                if columns[name]["level"] == "opportunity":
                    assert reducer == "unique"
    except (KeyError, TypeError, AssertionError):
        raise AppError("Invalid schema.json: check column types, levels, view keys, and aggregation rules.") from None
