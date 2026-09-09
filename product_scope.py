"""Resolve product-name shorthand against the snapshot; never guess family membership."""
import re

from query_engine import parse_plan
from query_models import FilterOperator


def resolve_product_scope(plan, incoming, question, views):
    if plan.result_kind.value == 'clarify':
        return plan
    # An ordinary follow-up can retain confirmed scope. Mentioning the product
    # again ("amount just for Q7") needs review even if the planner omitted the
    # supposedly unchanged contains filter from its refinement.
    mentions_existing = any(
        str(value).casefold() in question.casefold()
        for f in plan.filters if f.field == 'pet_name' and f.value is not None
        for value in (f.value if isinstance(f.value, list) else [f.value])
    )
    if not mentions_existing and not any(f.field == 'pet_name' for f in incoming.filters):
        return plan
    names = sorted({str(v) for v in views.sku.pet_name.dropna()}, key=lambda s: (s.casefold(), s))

    def aliases(value):
        key = str(value).strip().casefold()
        exact = [n for n in names if n.casefold() == key]
        return exact or [n for n in names if n.casefold().endswith(' ' + key)]

    def clarify(value, candidates):
        examples = ', '.join(candidates[:4])
        text = f'Do you mean only the base model "{value}", or several variants? Please specify the exact product names'
        if examples:
            text += f' (for example: {examples})'
        text += '. Include FE or accessories only if you want them.'
        if len(text) > 300:
            text = 'Do you mean only the base model, or several variants? Please list the exact product names, including whether FE or accessories should be included.'
        return parse_plan({'result_kind': 'clarify', 'clarification': text})

    base_request = (r'\b(?:only|just)\s+(?:the\s+)?(?:base|standard)(?:\s+model)?\b'
                    r'|\b(?:base|standard)(?:\s+model)?\s+only\b'
                    r'|^(?:the\s+)?(?:base|standard)(?:\s+model)?[.!]?$')
    explicit_base = bool(re.search(base_request, question.strip(), re.I))
    if re.search(r'\b(?:not|except|exclude|excluding|without)\s+(?:only\s+)?(?:the\s+)?(?:base|standard)\b', question, re.I):
        explicit_base = False
    explicit_contains = bool(re.search(r'\b(?:names?\s+(?:containing|contains)|pet_name\s+contains)\b', question, re.I))
    updated = []
    for clause in plan.filters:
        if clause.field != 'pet_name' or clause.value is None:
            updated.append(clause)
            continue
        operator = clause.operator.value
        values = clause.value if operator == 'in' else [clause.value]
        if operator in ('eq', 'in'):
            resolved = []
            for value in values:
                candidates = aliases(value)
                broader = [n for n in names if str(value).casefold() in n.casefold()]
                if not candidates and str(value).casefold().endswith(' family'):
                    family = str(value)[:-7].strip()
                    family_names = [n for n in names if family.casefold() in n.casefold()]
                    if family_names:
                        return clarify(family, family_names)
                if len(candidates) > 1:
                    return clarify(value, candidates)
                # An explicit list defines its members. A single short base name
                # still leaves exact-model versus family scope undecided.
                if (len(values) == 1 and len(candidates) == 1 and len(broader) > 1
                        and not explicit_base and (candidates[0].casefold() not in question.casefold()
                                                  or re.search(r'\bfamily\b', question, re.I))):
                    return clarify(candidates[0], broader)
                resolved.append(candidates[0] if candidates else value)
            updated.append(clause.model_copy(update={'value': resolved if operator == 'in' else resolved[0]}))
        elif operator == 'contains' and not explicit_contains:
            value = re.sub(r'\s+family$', '', str(clause.value), flags=re.I).strip()
            candidates = aliases(value)
            broader = [n for n in names if value.casefold() in n.casefold()]
            if candidates and explicit_base and len(candidates) == 1:
                updated.append(clause.model_copy(update={'operator': FilterOperator.EQ, 'value': candidates[0]}))
            elif len(broader) > 1:
                return clarify(candidates[0] if len(candidates) == 1 else value, broader)
            else:
                updated.append(clause)
        else:
            updated.append(clause)
    return plan.model_copy(update={'filters': updated})
