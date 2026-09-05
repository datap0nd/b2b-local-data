from collections import defaultdict
from decimal import Decimal, InvalidOperation

from app.config import AppError


def normalize(value, spec):
    if value is None:
        return None
    if spec["type"] == "number":
        try:
            number = Decimal(str(value))
            if not number.is_finite():
                raise InvalidOperation
            return number
        except InvalidOperation:
            raise AppError("A numeric source column contains an invalid number.") from None
    return str(value)


def make_table(rows, schema, plan):
    view = schema["views"][plan["view"]]
    groups = defaultdict(list)
    opportunity_values = {}
    for source in rows:
        row = {name: normalize(source[name], spec) for name, spec in schema["columns"].items()}
        key = tuple(row[k] for k in view["keys"])
        if any(x is None or x == "" for x in key):
            raise AppError("A source row has a missing opportunity or SKU key. Correct the source or the grouping rule.")
        opportunity = row[schema["opportunity_key"]]
        attributes = {name: row[name] for name, spec in schema["columns"].items() if spec["level"] == "opportunity"}
        if opportunity in opportunity_values and opportunity_values[opportunity] != attributes:
            raise AppError("Conflicting opportunity attributes across product rows. Check repeated amounts, dates, owners, and currency.")
        opportunity_values[opportunity] = attributes
        groups[key].append(row)
    output = []
    for key in sorted(groups):
        record = {}
        for name, reducer in view["columns"].items():
            values = [row[name] for row in groups[key]]
            if reducer == "sum":
                record[name] = None if None in values else sum(values, Decimal(0))
            elif reducer == "join":
                record[name] = " | ".join(sorted({str(v) for v in values if v is not None}))
            else:
                unique = set(values)
                if len(unique) != 1:
                    raise AppError(f"Conflicting values in '{name}' within a {plan['view']} row. Confirm the grouping or fix the source.")
                record[name] = values[0]
        output.append(record)
    total = len(output)
    # Serialize Decimal as text to preserve exact money values in the browser/export.
    output = [{k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()} for row in output[:plan["limit"]]]
    return {"columns": list(view["columns"]), "rows": output, "total_rows": total,
            "source_rows": len(rows), "truncated": total > plan["limit"], "view": plan["view"],
            "product_scope": plan["product_scope"], "filters": plan["filters"]}
