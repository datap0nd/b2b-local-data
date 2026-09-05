from datetime import date
from decimal import Decimal, InvalidOperation

from app.config import AppError


OPERATORS = ("eq", "ne", "contains", "gt", "gte", "lt", "lte", "is_null", "not_null")
PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "question", "view", "product_scope", "filters", "limit"],
    "properties": {
        "kind": {"type": "string", "enum": ["query", "clarify"]},
        "question": {"type": "string"},
        "view": {"type": "string", "enum": ["summary", "detail"]},
        "product_scope": {"type": "string", "enum": ["matching_rows", "whole_opportunities", "unspecified"]},
        "filters": {"type": "array", "maxItems": 20, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["column", "op", "value"],
            "properties": {"column": {"type": "string"}, "op": {"type": "string", "enum": list(OPERATORS)}, "value": {"type": ["string", "number", "null"]}}
        }},
        "limit": {"type": "integer", "minimum": 1, "maximum": 1000}
    }
}


def validate_plan(plan, schema):
    if not isinstance(plan, dict) or set(plan) != set(PLAN_SCHEMA["required"]):
        raise AppError("Qwen returned an unsupported plan. Please rephrase your question.")
    if plan["kind"] not in ("query", "clarify") or not isinstance(plan["view"], str) or plan["view"] not in schema["views"]:
        raise AppError("Qwen returned an invalid table type.")
    if not isinstance(plan["question"], str) or len(plan["question"]) > 2000:
        raise AppError("Invalid clarification response.")
    if type(plan["limit"]) is not int or not 1 <= plan["limit"] <= 1000:
        raise AppError("Table limit must be between 1 and 1000.")
    if plan["product_scope"] not in ("matching_rows", "whole_opportunities", "unspecified"):
        raise AppError("Invalid product filter scope.")
    filters = plan["filters"]
    if not isinstance(filters, list) or len(filters) > 20:
        raise AppError("Too many filters.")
    for item in filters:
        if not isinstance(item, dict) or set(item) != {"column", "op", "value"}:
            raise AppError("Invalid filter.")
        if not isinstance(item["column"], str) or item["column"] not in schema["columns"] or item["op"] not in OPERATORS:
            raise AppError("Unknown column or filter operation.")
        spec, value, op = schema["columns"][item["column"]], item["value"], item["op"]
        if op in ("is_null", "not_null"):
            if value is not None:
                raise AppError("Null filters must use a null value.")
            continue
        if value is None or type(value) not in (str, int, float):
            raise AppError("Invalid filter value.")
        if len(str(value)) > 500:
            raise AppError("Filter value is too long.")
        if spec["type"] == "number":
            try:
                if op == "contains" or not Decimal(str(value)).is_finite():
                    raise InvalidOperation
            except InvalidOperation:
                raise AppError("A numeric filter needs a finite number.") from None
        elif spec["type"] == "date":
            try:
                if op == "contains" or not isinstance(value, str):
                    raise ValueError
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError:
                raise AppError("Date filters must use YYYY-MM-DD.") from None
        elif not isinstance(value, str) or op not in ("eq", "ne", "contains"):
            raise AppError("Text fields accept eq, ne, or contains with text values.")
    if plan["kind"] == "clarify" and not plan["question"].strip():
        raise AppError("Qwen returned an empty clarification.")
    if plan["kind"] == "query" and any(schema["columns"][f["column"]]["level"] == "product" for f in filters) and plan["product_scope"] == "unspecified":
        return {**plan, "kind": "clarify", "question": "Should I include only matching product rows, or all products from the matching opportunities?"}
    return plan


def example_plan(view="summary"):
    return {"kind": "query", "question": "", "view": view, "product_scope": "matching_rows", "filters": [], "limit": 200}
