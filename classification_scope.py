"""Enforce topic vocabulary before execution; ambiguous combinations need confirmation."""
import json
import re
from pathlib import Path

from query_models import FilterClause, ResultKind


def b2b_definitions():
    return json.loads((Path(__file__).parent / 'config/b2b_classifications.json').read_text(encoding='utf-8'))


def definition_guidance():
    config = b2b_definitions()
    return 'Authoritative B2B definitions: ' + '; '.join(
        f'"{d["term"]}" means {d["field"]} eq {d["value"]}' for d in config['definitions']
    ) + '. Bare flagship includes all generations; never add a generation restriction unless requested.'


def resolve_classification_scope(plan, question, config=None):
    config = config or b2b_definitions()
    text = re.sub(r'[-\s]+', ' ', question.casefold())
    matches = []
    # Consume specific phrases before their broader suffixes.
    remaining = text
    for definition in sorted(config['definitions'], key=lambda d: -len(d['term'])):
        pattern = r'\b' + re.escape(definition['term']) + r's?\b'
        if re.search(pattern, remaining):
            matches.append(definition)
            remaining = re.sub(pattern, ' ', remaining)
    if not matches or plan.result_kind == ResultKind.CLARIFY:
        return plan

    # Do not silently erase an explicit exclusion, comparison, or another level.
    # These requests need a confirmed scope rather than an optimistic rewrite.
    ambiguous = (len(matches) != 1 or re.search(
        r'\b(not|non|except|excluding|exclude|without|remove|drop|clear|versus|vs|or|only current|only previous|'
        r'latest|older|newest|current|previous|generation|segment|seg_[123]|series)\b|\bs\s*\(n', remaining))
    # A matching word inside a named customer/product is not a category request.
    named_entity = any(
        f.field not in {'biz_group','seg_1','seg_2','seg_3','series'} and
        any(d['term'] in str(v).casefold() for d in matches
            for v in (f.value if isinstance(f.value,list) else [f.value]))
        for f in plan.filters
    )
    if named_entity:
        from query_engine import parse_plan
        return parse_plan({'result_kind': 'clarify', 'clarification':
            'Does "flagship" refer to the product classification, or to a named customer or product? '
            'Please specify the intended field and name.'})
    if ambiguous:
        from query_engine import parse_plan
        return parse_plan({'result_kind': 'clarify', 'clarification':
            'Which classification scope do you want: all flagship products (Segment 1 = FLAGSHIP), '
            'current-generation flagship (Segment 3 = S(N)), or previous-generation flagship '
            '(Segment 3 = S(N-1))? Please state any additional restriction or exclusion.'})

    definition = matches[0]
    result = plan.model_copy(deep=True)
    replaced_fields = {d['field'] for d in config['definitions']}
    result.filters = [f for f in result.filters if f.field not in replaced_fields]
    result.filters.append(FilterClause(field=definition['field'], operator='eq', value=definition['value']))
    return result
