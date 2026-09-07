"""Independent reference calculator for the acceptance suite.

It works from raw text records with Decimal arithmetic and deliberately imports nothing from
data_layer, query_engine, or query_service, so a defect in the production canonicalization,
filtering, aggregation, or follow-up merging cannot hide inside the expected values.
Column names follow the published data contract so results can be compared cell by cell.

reference-2 adds the typed result digest (digest2), ISO date text from typed database columns,
and keyed canonical-grain diagnostics; the aggregation rules are unchanged from reference-1.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

EVALUATOR_VERSION = 'reference-2'
FINGERPRINT_VERSION = 'fp1'
DIGEST_VERSION = 'digest2'

RAW_TEXT = ['opportunity_no', 'product_code', 'subsidiary_subsidiary_code', 'opportunity_name', 'end_customer', 'gscm_product_group_new',
            'pet_name', 'stage', 'opportunity_owner', 'biz_focus', 'business_location', 'division', 'sales_type_detail', 'type',
            'amount_converted_currency', 'opp_amount_converted_currency', 'rollout_period_to', 'rollout_period_from', 'first_channel', 'comment']
RAW_NUMBER = ['quantity', 'amount_converted', 'opp_amount_converted', 'age', 'deal_size_on_pricing_date_usd']
RAW_DATE = ['close_month', 'close_date', 'created_date', 'last_modified_date']
RAW_FIELDS = RAW_TEXT + RAW_NUMBER + ['probability'] + RAW_DATE
# The documented fingerprint field order is this list; the report prints it from here, never from a copy.
FINGERPRINT_FIELDS = list(RAW_FIELDS)
STAGE_MEMBERS = {'Won': ['Won', 'Rollout Started', 'Rollout Finished'], 'Open': ['Identified', 'Qualified', 'Negotiation'], 'Lost': ['Dropped', 'Lost']}
SKU_LEVEL_TEXT = ['gscm_product_group_new', 'pet_name', 'amount_converted_currency']
OPPORTUNITY_TEXT = [f for f in RAW_TEXT if f not in ('opportunity_no', 'product_code') and f not in SKU_LEVEL_TEXT]
ATTRIBUTES = ['first_channel', 'age', 'comment', 'deal_size_on_pricing_date_usd']
CONFLICT_FIELDS = ['opp_amount_converted', 'opportunity_name', 'end_customer', 'pet_name', 'gscm_product_group_new', 'stage', 'opportunity_owner',
                   'amount_converted_currency'] + ATTRIBUTES
SKU_COLUMNS = ['opportunity_no', 'product_code'] + [f for f in RAW_TEXT if f not in ('opportunity_no', 'product_code')] + [
    'quantity', 'sku_amount', 'exported_opp_amount_min', 'exported_opp_amount_max', 'exported_opp_amount_value_count', 'probability',
    'age', 'deal_size_on_pricing_date_usd'] + RAW_DATE + ['source_row_count', 'has_quality_warning']
OPPORTUNITY_COLUMNS = ['opportunity_no'] + OPPORTUNITY_TEXT + ['probability', 'age', 'deal_size_on_pricing_date_usd'] + RAW_DATE + [
    'quantity', 'opportunity_amount', 'sku_count', 'source_row_count', 'product_codes', 'product_names', 'exported_opp_amount_min',
    'exported_opp_amount_max', 'has_amount_discrepancy', 'has_quality_warning']
NUMBER_COLUMNS = {'quantity', 'sku_amount', 'opportunity_amount', 'exported_opp_amount_min', 'exported_opp_amount_max', 'exported_opp_amount_value_count',
                  'probability', 'sku_count', 'source_row_count', 'age', 'deal_size_on_pricing_date_usd', 'amount', 'deal_size', 'opportunity_count',
                  'amount_converted', 'opp_amount_converted'}
BOOL_COLUMNS = {'has_quality_warning', 'has_amount_discrepancy'}
DATE_COLUMNS = set(RAW_DATE)
NUMBER_PATTERN = re.compile(r'^[+-]?[0-9]+(\.[0-9]+)?$')
PROBABILITY_PATTERN = re.compile(r'^[0-9]+(\.[0-9]+)?%?$')
DATE_PATTERN = re.compile(r'^([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})$')
ISO_DATE_PATTERN = re.compile(r'^([0-9]{4})-([0-9]{2})-([0-9]{2})(?:[ T][0-9:.+-]*Z?)?$')


def r_text(value):
    if value is None:
        return None
    value = str(value).strip(' ')
    return value if value else None


def r_number(value):
    value = r_text(value)
    return Decimal(value) if value and NUMBER_PATTERN.match(value) else None


def r_probability(value):
    value = r_text(value)
    return Decimal(value.rstrip('%')) / Decimal(100) if value and PROBABILITY_PATTERN.match(value) else None


def r_date(value):
    """Day-first D/M/YYYY export text, ISO YYYY-MM-DD text from typed database columns, or a native date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    value = r_text(value)
    if not value:
        return None
    match = DATE_PATTERN.match(value)
    if match:
        day, month, year = (int(part) for part in match.groups())
    else:
        match = ISO_DATE_PATTERN.match(value)
        if not match:
            return None
        year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def known(values):
    return [v for v in values if v is not None]


def r_min(values):
    values = known(values)
    return min(values) if values else None


def r_max(values):
    values = known(values)
    return max(values) if values else None


def r_sum(values):
    values = known(values)
    total = Decimal(0)
    for value in values:
        total += value
    return total if values else None


def distinct_count(values):
    return len(set(known(values)))


def column_kind(name):
    """The contract type of a result column: number, date, bool, or text (identifiers stay text)."""
    if name in NUMBER_COLUMNS:
        return 'number'
    if name in DATE_COLUMNS:
        return 'date'
    if name in BOOL_COLUMNS:
        return 'bool'
    return 'text'


def decimal_text(number):
    return format(number.normalize(), 'f') if number != 0 else '0'


def cell_token(value, kind):
    """Typed canonical text for digests and comparisons.

    Numbers become n:<exact decimal without trailing zeros>, dates d:<ISO>, booleans b:true/b:false,
    text s:<text> (so the identifier 000123 never equals the number 123), and null stays null."""
    if value is None:
        return 'null'
    if kind == 'bool':
        if isinstance(value, bool):
            return 'b:true' if value else 'b:false'
        if isinstance(value, str) and value.strip().lower() in ('true', 'false'):
            return 'b:' + value.strip().lower()
        return 's:' + str(value)
    if kind == 'number' and not isinstance(value, bool):
        if isinstance(value, Decimal):
            return 'n:' + decimal_text(value)
        if isinstance(value, (int, float)):
            return 'n:' + decimal_text(Decimal(str(value)))
        text = str(value).strip(' ')
        if NUMBER_PATTERN.match(text) or re.match(r'^[+-]?[0-9]+(\.[0-9]+)?[eE][+-]?[0-9]+$', text):
            try:
                return 'n:' + decimal_text(Decimal(text))
            except InvalidOperation:
                pass
        return 's:' + str(value)
    if kind == 'date':
        parsed = r_date(value)
        return 'd:' + parsed.isoformat() if parsed else 's:' + str(value)
    if isinstance(value, bool):
        return 'b:true' if value else 'b:false'
    if isinstance(value, (Decimal, int, float)):
        return 's:' + (decimal_text(value) if isinstance(value, Decimal) else str(value))
    if isinstance(value, (date, datetime)):
        return 's:' + value.isoformat()
    return 's:' + str(value)


def normalize_cell(value):
    """Untyped text form kept for readable diagnostics: exact decimals, ISO dates, JSON null/bool."""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if NUMBER_PATTERN.match(text) and not text.startswith('+'):
        return decimal_text(Decimal(text))
    return text


def digest_rows(rows, columns, kinds=None):
    """digest2: order-independent, multiplicity-preserving digest over typed cell tokens in result column order."""
    kinds = kinds or {c: column_kind(c) for c in columns}
    hashes = sorted(hashlib.sha256(json.dumps([cell_token(row.get(c), kinds.get(c, 'text')) for c in columns], ensure_ascii=False).encode()).hexdigest() for row in rows)
    return DIGEST_VERSION + ':' + hashlib.sha256('\n'.join(hashes).encode()).hexdigest()


def fingerprint(records, fields=FINGERPRINT_FIELDS):
    """Order-independent fingerprint over trimmed text values, keeping duplicate rows with their multiplicity."""
    hashes = sorted(hashlib.sha256(json.dumps([r_text(record.get(f)) for f in fields], ensure_ascii=False).encode()).hexdigest() for record in records)
    return FINGERPRINT_VERSION + ':' + hashlib.sha256('\n'.join(hashes).encode()).hexdigest()


class ReferenceSource:
    """Raw records reduced to the two business grains with the evaluator's own arithmetic."""
    def __init__(self, records):
        records = [dict(record) for record in records]
        self.raw_count = len(records)
        self.records = records
        self.fingerprint = fingerprint(records)
        normalized = []
        for record in records:
            row = {f: r_text(record.get(f)) for f in RAW_TEXT}
            row.update({f: r_number(record.get(f)) for f in RAW_NUMBER})
            row['probability'] = r_probability(record.get('probability'))
            row.update({f: r_date(record.get(f)) for f in RAW_DATE})
            normalized.append(row)
        self.excluded = sum(1 for row in normalized if row['opportunity_no'] is None or row['product_code'] is None)
        groups = {}
        for row in normalized:
            if row['opportunity_no'] is None or row['product_code'] is None:
                continue
            groups.setdefault((row['opportunity_no'], row['product_code']), []).append(row)
        self.sku = []
        for key in sorted(groups):
            rows = groups[key]
            col = lambda f: [r[f] for r in rows]
            sku = {'opportunity_no': key[0], 'product_code': key[1]}
            for f in RAW_TEXT[2:]:
                sku[f] = r_min(col(f))
            sku['quantity'] = r_sum(col('quantity'))
            sku['sku_amount'] = r_sum(col('amount_converted'))
            sku['exported_opp_amount_min'] = r_min(col('opp_amount_converted'))
            sku['exported_opp_amount_max'] = r_max(col('opp_amount_converted'))
            sku['exported_opp_amount_value_count'] = distinct_count(col('opp_amount_converted'))
            sku['probability'] = r_min(col('probability'))
            sku['age'] = r_min(col('age'))
            sku['deal_size_on_pricing_date_usd'] = r_min(col('deal_size_on_pricing_date_usd'))
            for f in RAW_DATE:
                sku[f] = r_max(col(f)) if f == 'last_modified_date' else r_min(col(f))
            sku['source_row_count'] = len(rows)
            sku['has_quality_warning'] = any(distinct_count(col(f)) > 1 for f in CONFLICT_FIELDS)
            self.sku.append(sku)
        by_opportunity = {}
        for sku in self.sku:
            by_opportunity.setdefault(sku['opportunity_no'], []).append(sku)
        self.opportunity = []
        for opp in sorted(by_opportunity):
            skus = by_opportunity[opp]
            col = lambda f: [s[f] for s in skus]
            row = {'opportunity_no': opp}
            for f in OPPORTUNITY_TEXT:
                row[f] = r_min(col(f))
            row['probability'] = r_min(col('probability'))
            row['age'] = r_min(col('age'))
            row['deal_size_on_pricing_date_usd'] = r_min(col('deal_size_on_pricing_date_usd'))
            for f in RAW_DATE:
                row[f] = r_max(col(f)) if f == 'last_modified_date' else r_min(col(f))
            row['quantity'] = r_sum(col('quantity'))
            amount = r_sum(col('sku_amount'))
            row['opportunity_amount'] = amount
            row['sku_count'] = len(skus)
            row['source_row_count'] = sum(col('source_row_count'))
            row['product_codes'] = ', '.join(sorted(set(known(col('product_code'))))) or None
            row['product_names'] = ', '.join(sorted(set(known(col('pet_name'))))) or None
            low, high = r_min(col('exported_opp_amount_min')), r_max(col('exported_opp_amount_max'))
            row['exported_opp_amount_min'], row['exported_opp_amount_max'] = low, high
            # The only tolerance in the whole evaluator: the documented 0.01 parent-amount rule.
            discrepancy = low is None or high is None or amount is None or low != high or abs(amount - high) > Decimal('0.01')
            row['has_amount_discrepancy'] = discrepancy
            conflict = any(distinct_count(col(f)) > 1 for f in ATTRIBUTES)
            row['has_quality_warning'] = bool(any(col('has_quality_warning')) or discrepancy or conflict)
            self.opportunity.append(row)
        self.sku_by_opportunity = by_opportunity
        self.opportunity_index = {row['opportunity_no']: row for row in self.opportunity}

    def summary(self):
        currencies = {}
        for sku in self.sku:
            currencies[sku['amount_converted_currency']] = currencies.get(sku['amount_converted_currency'], 0) + 1
        return {'raw_rows': self.raw_count, 'excluded_rows': self.excluded, 'opportunities': len(self.opportunity), 'opportunity_sku_pairs': len(self.sku),
                'currencies': {str(k): v for k, v in sorted(currencies.items(), key=lambda item: (item[0] is None, str(item[0])))},
                'fingerprint': self.fingerprint, 'sku_digest': digest_rows(self.sku, SKU_COLUMNS), 'opportunity_digest': digest_rows(self.opportunity, OPPORTUNITY_COLUMNS)}

    def raw_rows_for(self, opportunity_no, product_code=None, limit=5):
        """Raw records (trimmed text) behind one key, for mismatch diagnostics."""
        rows = []
        for record in self.records:
            if r_text(record.get('opportunity_no')) != opportunity_no:
                continue
            if product_code is not None and r_text(record.get('product_code')) != product_code:
                continue
            rows.append({f: r_text(record.get(f)) for f in RAW_FIELDS})
            if len(rows) >= limit:
                break
        return rows


def value_of(row, field, grain, source):
    if field == 'stage_group':
        stage = row.get('stage')
        return next((g for g, members in STAGE_MEMBERS.items() if stage in members), None)
    if field == 'amount':
        return row['opportunity_amount'] if grain == 'opportunity' else row['sku_amount']
    if field == 'deal_size':
        parent = source.opportunity_index.get(row['opportunity_no'])
        return parent['deal_size_on_pricing_date_usd'] if parent else None
    return row.get(field)


def matches(value, op, target):
    if op == 'eq':
        return value == target if target is not None else value is None
    if op == 'ne':
        return value is not None and value != target if target is not None else value is not None
    if op == 'in':
        return value in target
    if op == 'contains':
        return isinstance(value, str) and target.casefold() in value.casefold()
    if value is None:
        return False
    if op == 'between':
        return target[0] <= value <= target[1]
    return {'gt': value > target, 'ge': value >= target, 'lt': value < target, 'le': value <= target}[op]


def stage_filter_matches(value, op, target):
    """Stage filters accept the canonical group names and expand them to their members."""
    expand = lambda items: [member for item in items for member in STAGE_MEMBERS.get(item, [item])]
    if op in ('eq', 'in'):
        return value in expand([target] if op == 'eq' else target)
    if op == 'ne':
        return value is not None and value not in expand([target])
    return matches(value, op, target)


def row_matches(row, clause, grain, source):
    field, op, target = clause['field'], clause['op'], clause['value']
    value = value_of(row, field, grain, source)
    if field == 'stage':
        return stage_filter_matches(value, op, target)
    return matches(value, op, target)


def apply_filters(source, grain, filters):
    """Filters run after grain reduction. Fields foreign to the grain select whole opportunities."""
    rows = source.opportunity if grain == 'opportunity' else source.sku
    own_columns = set(OPPORTUNITY_COLUMNS if grain == 'opportunity' else SKU_COLUMNS) | {'stage_group', 'amount', 'deal_size'}
    own = [c for c in filters if c['field'] in own_columns]
    foreign = [c for c in filters if c['field'] not in own_columns]
    selected = [row for row in rows if all(row_matches(row, c, grain, source) for c in own)]
    if foreign:
        other_grain = 'sku' if grain == 'opportunity' else 'opportunity'
        others = source.sku if grain == 'opportunity' else source.opportunity
        keep = {row['opportunity_no'] for row in others if all(row_matches(row, c, other_grain, source) for c in foreign)}
        selected = [row for row in selected if row['opportunity_no'] in keep]
    return selected


def sort_rows(rows, order, columns_of):
    """Stable multi-key sort applied from the last key to the first; nulls always sort last."""
    result = list(rows)
    for field, ascending in reversed(order):
        nulls = [r for r in result if columns_of(r, field) is None]
        values = [r for r in result if columns_of(r, field) is not None]
        values.sort(key=lambda r: columns_of(r, field), reverse=not ascending)
        result = values + nulls
    return result


def evaluate(source, spec):
    """Compute the complete expected result for an authored specification.

    spec: {'grain': 'opportunity'|'sku', 'intent': 'table'|'metric'|'chart', 'filters': [{'field','op','value'}],
           'columns': [...] (tables), 'group': [...], 'measures': [...] (metrics/charts), 'sort': [(field, ascending)], 'limit': int|None}
    """
    grain = spec['grain']
    rows = apply_filters(source, grain, spec.get('filters', []))
    keys = ['opportunity_no'] if grain == 'opportunity' else ['opportunity_no', 'product_code']
    getter = lambda row, field: value_of(row, field, grain, source)
    if spec['intent'] == 'table':
        columns = list(spec['columns'])
        for key in reversed(keys):
            if key not in columns:
                columns.insert(0, key)
        order = spec.get('sort') or [(k, True) for k in keys]
        ordered = sort_rows(rows, order, getter)
        complete = [{c: getter(row, c) for c in columns} for row in ordered]
        limit = spec.get('limit') or 1000
        totals = {'amount': r_sum([getter(r, 'amount') for r in ordered]), 'quantity': r_sum([r['quantity'] for r in ordered]),
                  'opportunity_count': distinct_count([r['opportunity_no'] for r in ordered]), 'rows': len(ordered)}
        return {'columns': columns, 'keys': keys, 'rows': complete[:limit], 'total': len(ordered), 'totals': totals,
                'digest': digest_rows(complete, columns), 'limit': limit, 'kinds': {c: column_kind(c) for c in columns}}
    group_fields = list(spec.get('group', []))
    measures = list(spec['measures'])
    groups = {}
    for row in rows:
        key = tuple(getter(row, f) for f in group_fields)
        groups.setdefault(key, []).append(row)
    records = []
    for key, members in groups.items():
        record = dict(zip(group_fields, key))
        for measure in measures:
            if measure == 'amount':
                record[measure] = r_sum([getter(r, 'amount') for r in members])
            elif measure == 'quantity':
                record[measure] = r_sum([r['quantity'] for r in members])
            elif measure == 'opportunity_count':
                record[measure] = distinct_count([r['opportunity_no'] for r in members])
            elif measure == 'sku_count':
                record[measure] = sum(r['sku_count'] for r in members) if grain == 'opportunity' else len(members)
            elif measure == 'deal_size':
                seen, total, any_value = set(), Decimal(0), False
                for r in members:
                    if r['opportunity_no'] in seen:
                        continue
                    seen.add(r['opportunity_no'])
                    value = getter(r, 'deal_size')
                    if value is not None:
                        total += value
                        any_value = True
                record[measure] = total if any_value else None
            else:
                raise ValueError('Unknown measure ' + measure)
        records.append(record)
    columns = group_fields + measures
    order = spec.get('sort') or [(f, True) for f in group_fields]
    ordered = sort_rows(records, order, lambda record, field: record.get(field))
    limit = spec.get('limit') or 1000
    return {'columns': columns, 'keys': group_fields, 'rows': ordered[:limit], 'total': len(ordered), 'totals': None,
            'digest': digest_rows(ordered, columns), 'limit': limit, 'kinds': {c: column_kind(c) for c in columns}}


def compare(expected, actual, max_differences=20):
    """Compare a production result payload with the reference result: typed cells, keyed rows, order, counts, totals, digest."""
    differences, checks = [], {}
    kinds = expected.get('kinds') or {c: column_kind(c) for c in expected['columns']}
    token = lambda row, column: cell_token(row.get(column), kinds.get(column, 'text'))
    actual_columns = list(actual.get('columns', []))
    checks['columns'] = set(actual_columns) == set(expected['columns'])
    if not checks['columns']:
        differences.append({'kind': 'columns', 'expected': expected['columns'], 'actual': actual_columns})
    declared = actual.get('column_types') or {}
    wrong_types = {c: declared.get(c) for c in expected['columns'] if c in declared and declared.get(c) != kinds.get(c)}
    checks['types'] = not wrong_types
    if wrong_types:
        differences.append({'kind': 'types', 'expected': {c: kinds[c] for c in wrong_types}, 'actual': wrong_types})
    checks['total_rows'] = actual.get('total_rows') == expected['total']
    if not checks['total_rows']:
        differences.append({'kind': 'count', 'expected': expected['total'], 'actual': actual.get('total_rows')})
    checks['digest'] = actual.get('result_digest') == expected['digest']
    if not checks['digest']:
        differences.append({'kind': 'digest', 'expected': expected['digest'], 'actual': actual.get('result_digest')})
    keys = expected['keys']
    key_of = lambda row: tuple(token(row, k) for k in keys)
    expected_rows = {key_of(row): row for row in expected['rows']}
    actual_rows = {}
    duplicates = 0
    for row in actual.get('rows', []):
        key = key_of(row)
        if key in actual_rows:
            duplicates += 1
        actual_rows[key] = row
    checks['no_duplicates'] = duplicates == 0
    if duplicates:
        differences.append({'kind': 'duplicate_rows', 'count': duplicates})
    missing = [k for k in expected_rows if k not in actual_rows]
    extra = [k for k in actual_rows if k not in expected_rows]
    incorrect, cells_checked = 0, 0
    shared_columns = [c for c in expected['columns'] if c in actual_columns]
    for key, row in expected_rows.items():
        other = actual_rows.get(key)
        if other is None:
            continue
        for column in shared_columns:
            cells_checked += 1
            if token(row, column) != token(other, column):
                incorrect += 1
                if len(differences) < max_differences + 4:
                    differences.append({'kind': 'cell', 'key': key, 'column': column, 'expected': normalize_cell(row.get(column)), 'actual': normalize_cell(other.get(column)),
                                        'expected_token': token(row, column), 'actual_token': token(other, column)})
    for key in missing[:max_differences]:
        differences.append({'kind': 'missing_row', 'key': key})
    for key in extra[:max_differences]:
        differences.append({'kind': 'extra_row', 'key': key})
    checks['preview_cells'] = not missing and not extra and incorrect == 0
    checks['order'] = [key_of(r) for r in actual.get('rows', [])] == [key_of(r) for r in expected['rows']]
    if checks['preview_cells'] and not checks['order']:
        differences.append({'kind': 'order', 'expected': [key_of(r) for r in expected['rows']][:10], 'actual': [key_of(r) for r in actual.get('rows', [])][:10]})
    if expected.get('totals') is not None:
        totals = actual.get('totals') or {}
        checks['totals'] = all(cell_token(expected['totals'][k], 'number') == cell_token(totals.get(k), 'number') for k in expected['totals'])
        if not checks['totals']:
            differences.append({'kind': 'totals', 'expected': {k: normalize_cell(v) for k, v in expected['totals'].items()}, 'actual': {k: normalize_cell(totals.get(k)) for k in expected['totals']}})
    return {'ok': all(checks.values()), 'checks': checks, 'differences': differences[:max_differences],
            'scope': {'preview_rows': len(expected['rows']), 'preview_cells': cells_checked, 'complete_rows': expected['total'], 'complete_verified_by': ['count', 'digest'] + (['totals'] if expected.get('totals') is not None else [])},
            'counts': {'expected_rows': len(expected_rows), 'actual_rows': len(actual_rows), 'missing': len(missing), 'extra': len(extra), 'incorrect_cells': incorrect, 'duplicates': duplicates, 'cells_checked': cells_checked}}


def describe_value(value):
    """A value with its Python type and its serialized form, for mismatch diagnostics."""
    return {'value': value.isoformat() if isinstance(value, (date, datetime)) else (decimal_text(value) if isinstance(value, Decimal) else value),
            'type': type(value).__name__, 'serialized': normalize_cell(value)}


def compare_grains(reference_rows, app_rows, keys, columns, source=None, max_examples=20):
    """Keyed comparison of the application's canonical grain with the reference grain.

    Reports missing, extra, and duplicate keys, differing fields with value types and serialized forms, complete
    difference counts, and the first examples with the raw rows behind each key."""
    kinds = {c: column_kind(c) for c in columns}
    key_of = lambda row: tuple(cell_token(row.get(k), 'text') for k in keys)
    reference, app, duplicates = {}, {}, []
    for row in reference_rows:
        reference[key_of(row)] = row
    for row in app_rows:
        key = key_of(row)
        if key in app:
            duplicates.append(key)
        app[key] = row
    missing = [k for k in reference if k not in app]
    extra = [k for k in app if k not in reference]
    by_column, differing_rows, examples, differing_cells = {}, 0, [], 0
    def context(key):
        plain = tuple(k[2:] if k.startswith('s:') else k for k in key)
        return source.raw_rows_for(plain[0], plain[1] if len(plain) > 1 else None) if source is not None else []
    for key, row in reference.items():
        other = app.get(key)
        if other is None:
            continue
        row_differs = False
        for column in columns:
            expected_token, actual_token = cell_token(row.get(column), kinds[column]), cell_token(other.get(column), kinds[column])
            if expected_token == actual_token:
                continue
            differing_cells += 1
            row_differs = True
            by_column[column] = by_column.get(column, 0) + 1
            if len(examples) < max_examples:
                examples.append({'kind': 'cell', 'key': list(key), 'column': column, 'column_kind': kinds[column], 'reference': describe_value(row.get(column)),
                                 'app': describe_value(other.get(column)), 'reference_token': expected_token, 'app_token': actual_token, 'raw_rows': context(key)})
        differing_rows += row_differs
    for key in missing:
        if len(examples) < max_examples:
            examples.append({'kind': 'missing_key', 'key': list(key), 'raw_rows': context(key)})
    for key in extra:
        if len(examples) < max_examples:
            examples.append({'kind': 'extra_key', 'key': list(key), 'app_row': {c: describe_value(app[key].get(c)) for c in keys}})
    for key in duplicates:
        if len(examples) < max_examples:
            examples.append({'kind': 'duplicate_key', 'key': list(key)})
    ok = not missing and not extra and not duplicates and differing_cells == 0
    return {'ok': ok, 'counts': {'reference_rows': len(reference), 'app_rows': len(app_rows), 'missing_keys': len(missing), 'extra_keys': len(extra), 'duplicate_keys': len(duplicates),
                                 'differing_rows': differing_rows, 'differing_cells': differing_cells, 'by_column': dict(sorted(by_column.items(), key=lambda item: (-item[1], item[0])))},
            'examples': examples}
