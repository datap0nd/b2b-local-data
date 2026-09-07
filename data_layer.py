"""Canonical Salesforce grains, built by one shared parser from a CSV file or the raw PostgreSQL table."""
import codecs
import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import re
import ssl

import pandas as pd
from sqlalchemy import URL, create_engine, text

from app_config import AppError

# The canonical data schema: every raw Salesforce column, its exact PostgreSQL column name, and its parser.
# Canonical field names are lower snake_case identifiers starting with a letter. The SQL column name is
# identical unless it is not a valid identifier, in which case the manual alias below applies.
SOURCE_FIELDS = [
    ('opportunity_no', 'opportunity_no', 'text'),
    ('product_code', 'product_code', 'text'),
    ('subsidiary_subsidiary_code', 'subsidiary_subsidiary_code', 'text'),
    ('opportunity_name', 'opportunity_name', 'text'),
    ('end_customer', 'end_customer', 'text'),
    ('gscm_product_group_new', 'gscm_product_group_new', 'text'),
    ('pet_name', 'pet_name', 'text'),
    ('stage', 'stage', 'text'),
    ('opportunity_owner', 'opportunity_owner', 'text'),
    ('biz_focus', 'biz_focus', 'text'),
    ('business_location', 'business_location', 'text'),
    ('division', 'division', 'text'),
    ('sales_type_detail', 'sales_type_detail', 'text'),
    ('type', 'type', 'text'),
    ('amount_converted_currency', 'amount_converted_currency', 'text'),
    ('opp_amount_converted_currency', 'opp_amount_converted_currency', 'text'),
    ('rollout_period_to', 'rollout_period_to', 'text'),
    ('rollout_period_from', 'rollout_period_from', 'text'),
    ('first_channel', '1st_channel', 'text'),
    ('comment', 'comment', 'text'),
    ('quantity', 'quantity', 'number'),
    ('amount_converted', 'amount_converted', 'number'),
    ('opp_amount_converted', 'opp_amount_converted', 'number'),
    ('probability', 'probability', 'probability'),
    ('age', 'age', 'number'),
    ('deal_size_on_pricing_date_usd', 'deal_size_on_pricing_date_usd', 'number'),
    ('close_month', 'close_month', 'date'),
    ('close_date', 'close_date', 'date'),
    ('created_date', 'created_date', 'date'),
    ('last_modified_date', 'last_modified_date', 'date'),
]
FIELD_KINDS = {name: kind for name, _, kind in SOURCE_FIELDS}
SQL_COLUMNS = {name: column for name, column, _ in SOURCE_FIELDS}
RAW_COLUMNS = [name for name, _, _ in SOURCE_FIELDS]
# Manual header aliases, keyed by normalized header text (see normalize_header).
HEADER_ALIASES = {
    '1st_channel': 'first_channel',
    'first_channel': 'first_channel',
    'opportunity_amount_converted': 'opp_amount_converted',
    'opportunity_amount_converted_currency': 'opp_amount_converted_currency',
    'comments': 'comment',
    'deal_size_on_pricing_date': 'deal_size_on_pricing_date_usd',
    'deal_size_usd': 'deal_size_on_pricing_date_usd',
}
TEXT_FIELDS = [name for name, kind in FIELD_KINDS.items() if kind == 'text']
DATE_FIELDS = [name for name, kind in FIELD_KINDS.items() if kind == 'date']
# Added attributes describe the opportunity; they are selected deterministically, never summed.
OPPORTUNITY_ATTRIBUTES = ['first_channel', 'age', 'comment', 'deal_size_on_pricing_date_usd']
ATTRIBUTE_NUMBERS = ['age', 'deal_size_on_pricing_date_usd']
SKU_METADATA = [f for f in TEXT_FIELDS if f not in ('opportunity_no', 'product_code')]
SKU_ONLY_METADATA = ('gscm_product_group_new', 'pet_name', 'amount_converted_currency')
OPPORTUNITY_METADATA = [f for f in SKU_METADATA if f not in SKU_ONLY_METADATA]
QUALITY_FIELDS = ['exported_opp_amount', 'opportunity_name', 'end_customer', 'pet_name', 'gscm_product_group_new',
                  'stage', 'opportunity_owner', 'amount_converted_currency'] + OPPORTUNITY_ATTRIBUTES
SKU_COLUMNS = ['opportunity_no', 'product_code'] + SKU_METADATA + ['quantity', 'sku_amount', 'exported_opp_amount_min',
    'exported_opp_amount_max', 'exported_opp_amount_value_count', 'probability'] + ATTRIBUTE_NUMBERS + DATE_FIELDS + ['source_row_count', 'has_quality_warning']
OPPORTUNITY_COLUMNS = ['opportunity_no'] + OPPORTUNITY_METADATA + ['probability'] + ATTRIBUTE_NUMBERS + DATE_FIELDS + ['quantity', 'opportunity_amount',
    'sku_count', 'source_row_count', 'product_codes', 'product_names', 'exported_opp_amount_min', 'exported_opp_amount_max',
    'has_amount_discrepancy', 'has_quality_warning']
NUMBER_FIELDS = {'quantity', 'sku_amount', 'opportunity_amount', 'exported_opp_amount_min', 'exported_opp_amount_max', 'exported_opp_amount_value_count',
                 'probability', 'sku_count', 'source_row_count'} | set(ATTRIBUTE_NUMBERS)
BOOL_FIELDS = {'has_quality_warning', 'has_amount_discrepancy'}
STAGE_GROUPS = {'Won': ('Won', 'Rollout Started', 'Rollout Finished'), 'Open': ('Identified', 'Qualified', 'Negotiation'), 'Lost': ('Dropped', 'Lost')}
NUMERIC = re.compile(r'^[+-]?[0-9]+([.][0-9]+)?$')
PROBABILITY = re.compile(r'^[0-9]+([.][0-9]+)?%?$')
DAY_FIRST = re.compile(r'^([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})$')


def clean_text(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    # Match PostgreSQL btrim(text): trim U+0020, retaining embedded whitespace. Identifiers stay text.
    value = str(value).strip(' ')
    return value or None


def clean_number(value, probability=False):
    value = clean_text(value)
    if not value or not (PROBABILITY if probability else NUMERIC).fullmatch(value):
        return None
    return Decimal(value.rstrip('%')) / 100 if probability else Decimal(value)


def clean_date(value):
    if isinstance(value, date):
        return value.date() if isinstance(value, datetime) else value
    value = clean_text(value)
    match = DAY_FIRST.fullmatch(value) if value else None
    if not match:
        return None
    try:
        day, month, year = (int(part) for part in match.groups())
        return date(year, month, day)
    except ValueError:
        return None


PARSERS = {'text': clean_text, 'number': clean_number, 'probability': lambda value: clean_number(value, True), 'date': clean_date}


def normalize_header(header):
    """Lowercase, replace punctuation/space runs with '_', and trim: 'Opportunity No.' -> 'opportunity_no'."""
    return re.sub(r'[^0-9a-z]+', '_', str(header).strip().casefold()).strip('_')


def resolve_columns(names, source='source'):
    """Map source column names to the 30 canonical fields; report missing or ambiguous columns."""
    by_normalized = {normalize_header(column): name for name, column, _ in SOURCE_FIELDS}
    by_normalized.update({normalize_header(name): name for name in RAW_COLUMNS})
    by_normalized.update(HEADER_ALIASES)
    matches = {}
    for name in names:
        field = by_normalized.get(normalize_header(name))
        if field:
            matches.setdefault(field, []).append(str(name))
    ambiguous = {field: found for field, found in matches.items() if len(found) > 1}
    if ambiguous:
        detail = '; '.join(f"{field}: {', '.join(found)}" for field, found in sorted(ambiguous.items()))
        raise AppError(f'The {source} has ambiguous columns for one field. Keep exactly one of each: {detail}.')
    missing = [name for name in RAW_COLUMNS if name not in matches]
    if missing:
        detail = ', '.join(f'{name} ({SQL_COLUMNS[name]})' if SQL_COLUMNS[name] != name else name for name in missing)
        raise AppError(f'The {source} is missing required Salesforce columns: {detail}.')
    return {field: found[0] for field, found in matches.items()}


def present(values):
    return [v for v in values if v is not None and not pd.isna(v)]


def sql_min(values):
    return min(present(values), default=None)


def sql_max(values):
    return max(present(values), default=None)


def sql_sum(values):
    items = present(values)
    return sum(items, Decimal(0)) if items else None


def conflicting(values):
    return len(set(present(values))) > 1


def stage_group(value):
    return next((name for name, stages in STAGE_GROUPS.items() if value in stages), None)


@dataclass
class CanonicalViews:
    sku: pd.DataFrame
    opportunity: pd.DataFrame
    source: str = 'pandas'
    source_name: str = ''
    excluded_rows: int = 0


def build_canonical_views(raw):
    raw = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw, dtype=object)
    if raw.empty and not len(raw.columns):
        raw = pd.DataFrame(columns=RAW_COLUMNS, dtype=object)
    missing = set(RAW_COLUMNS) - set(raw.columns)
    if missing:
        raise AppError('Raw Salesforce source is missing required columns: ' + ', '.join(sorted(missing)))
    normalized = []
    excluded = 0
    for source in raw.to_dict('records'):
        row = {name: clean_text(source[name]) for name in TEXT_FIELDS}
        if row['opportunity_no'] is None or row['product_code'] is None:
            excluded += 1
            continue
        row.update({name: PARSERS[FIELD_KINDS[name]](source[name]) for name in RAW_COLUMNS if FIELD_KINDS[name] != 'text'})
        row['exported_opp_amount'] = row.pop('opp_amount_converted')
        normalized.append(row)
    # Reduce record groups before constructing DataFrames. Creating one Series per
    # field per group dominates runtime for tens of thousands of small groups.
    by_sku = {}
    for row in normalized:
        by_sku.setdefault((row['opportunity_no'], row['product_code']), []).append(row)
    sku_rows = []
    for (opportunity, product), group in sorted(by_sku.items()):
        values = {name: [row[name] for row in group] for name in group[0]}
        row = {'opportunity_no': opportunity, 'product_code': product}
        row.update({name: sql_min(values[name]) for name in SKU_METADATA + ATTRIBUTE_NUMBERS})
        row.update({name: (sql_max if name == 'last_modified_date' else sql_min)(values[name]) for name in DATE_FIELDS})
        row.update(quantity=sql_sum(values['quantity']), sku_amount=sql_sum(values['amount_converted']),
                   exported_opp_amount_min=sql_min(values['exported_opp_amount']), exported_opp_amount_max=sql_max(values['exported_opp_amount']),
                   exported_opp_amount_value_count=len(set(present(values['exported_opp_amount']))), probability=sql_min(values['probability']),
                   source_row_count=len(group), has_quality_warning=any(conflicting(values[name]) for name in QUALITY_FIELDS))
        sku_rows.append(row)
    sku = pd.DataFrame(sku_rows, columns=SKU_COLUMNS, dtype=object)
    by_opportunity = {}
    for row in sku_rows:
        by_opportunity.setdefault(row['opportunity_no'], []).append(row)
    opportunity_rows = []
    for opportunity, group in sorted(by_opportunity.items()):
        values = {name: [row[name] for row in group] for name in group[0]}
        row = {'opportunity_no': opportunity}
        row.update({name: sql_min(values[name]) for name in OPPORTUNITY_METADATA + ATTRIBUTE_NUMBERS})
        row.update({name: (sql_max if name == 'last_modified_date' else sql_min)(values[name]) for name in DATE_FIELDS})
        amount = sql_sum(values['sku_amount'])
        lower, upper = sql_min(values['exported_opp_amount_min']), sql_max(values['exported_opp_amount_max'])
        discrepancy = lower is None or upper is None or amount is None or lower != upper or abs(amount - upper) > Decimal('0.01')
        # Opportunity attributes must agree across an opportunity's SKU rows; disagreement is flagged, never summed away.
        attribute_conflict = any(conflicting(values[name]) for name in OPPORTUNITY_ATTRIBUTES)
        row.update(probability=sql_min(values['probability']), quantity=sql_sum(values['quantity']), opportunity_amount=amount,
                   sku_count=len(group), source_row_count=int(sum(values['source_row_count'])),
                   product_codes=', '.join(sorted(set(present(values['product_code'])))) or None,
                   product_names=', '.join(sorted(set(present(values['pet_name'])))) or None,
                   exported_opp_amount_min=lower, exported_opp_amount_max=upper, has_amount_discrepancy=discrepancy,
                   has_quality_warning=bool(any(values['has_quality_warning']) or discrepancy or attribute_conflict))
        opportunity_rows.append(row)
    return CanonicalViews(sku, pd.DataFrame(opportunity_rows, columns=OPPORTUNITY_COLUMNS, dtype=object), excluded_rows=excluded)


def demo_rows():
    def row(opp, sku, amount, quantity, parent, **extra):
        return dict.fromkeys(RAW_COLUMNS) | {'opportunity_no': opp, 'product_code': sku, 'amount_converted': str(amount),
            'quantity': str(quantity), 'opp_amount_converted': str(parent), 'stage': 'Won', 'opportunity_owner': 'Alex',
            'end_customer': 'Example North', 'opportunity_name': 'Example project', 'pet_name': sku + ' product',
            'amount_converted_currency': 'EUR', 'opp_amount_converted_currency': 'EUR', 'probability': '75%',
            'close_date': '15/10/2026', 'close_month': '01/10/2026', 'first_channel': 'Partner', 'age': '30',
            'comment': 'Fictional note', 'deal_size_on_pricing_date_usd': str(parent)} | extra
    return [row('OPP-001', 'SKU-A', 400, 2, 750), row('OPP-001', 'SKU-A', 200, 1, 750), row('OPP-001', 'SKU-B', 150, 1, 750),
            row('OPP-002', 'SKU-B', 450, 3, 500, stage='Rollout Started', opportunity_owner='Blair', first_channel='Direct', age='12'),
            row('OPP-003', 'SKU-C', 2400, 2, 2400, stage='Qualified', end_customer='Example East', age='45')]


def quoted_relation(name):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*', name):
        raise AppError('Invalid database relation configuration.')
    return '.'.join('"' + part + '"' for part in name.split('.'))


def quoted_identifier(name):
    if not name or '\0' in name or len(name) > 63:
        raise AppError('Invalid database column name in the raw source.')
    return '"' + name.replace('"', '""') + '"'


def read_csv_source(path, encoding='utf-8-sig', cap=100000):
    """Read every value as text from a local CSV export; the shared parser applies the canonical rules."""
    path = Path(path)
    try:
        codecs.lookup(encoding)
    except LookupError:
        raise AppError('B2B_CSV_ENCODING is not a known text encoding.') from None
    if not path.is_file():
        raise AppError(f'The CSV source file does not exist: {path}. Check B2B_CSV_PATH.')
    try:
        with path.open('r', encoding=encoding, newline='') as stream:
            header = next(csv.reader(stream), None)
        if not header or not any(name.strip() for name in header):
            raise AppError(f'The CSV source file has no header row: {path.name}.')
        mapping = resolve_columns(header, f'CSV file {path.name}')
        positions = {field: header.index(name) for field, name in mapping.items()}
        # Every column is read so a row with extra fields is reported as malformed instead of silently trimmed.
        frame = pd.read_csv(path, header=None, skiprows=1, names=[f'column_{i}' for i in range(len(header))],
                            dtype=str, keep_default_na=False, na_filter=False, encoding=encoding, nrows=cap + 1, engine='c')
    except AppError:
        raise
    except UnicodeDecodeError:
        raise AppError(f'The CSV source file is not {encoding} text: {path.name}. Set B2B_CSV_ENCODING to match the export.') from None
    except (OSError, ValueError, pd.errors.ParserError) as error:
        raise AppError(f'The CSV source file is malformed: {path.name}. {str(error).splitlines()[0][:200]}') from None
    if len(frame) > cap:
        raise AppError(f'The source exceeds {cap:,} rows. Increase MAX_SOURCE_ROWS before computing complete totals.')
    frame = frame.rename(columns={f'column_{position}': field for field, position in positions.items()})
    return frame.loc[:, RAW_COLUMNS].astype(object)


class DataRepository:
    def __init__(self, settings, engine=None):
        self.settings, self.engine = settings, engine

    def _engine(self):
        if self.engine is None:
            options = self.settings.postgres
            context = ssl.create_default_context(cafile=self.settings.get('DB_CA_FILE') or None) if self.settings.flag('DB_SSL', True) else False
            url = URL.create('postgresql+pg8000', username=self.settings.get('RO_SQL_USER') or self.settings.get('DB_USER'),
                password=self.settings.get('RO_SQL_PW') or self.settings.get('DB_PASSWORD'), **options)
            self.engine = create_engine(url, connect_args={'ssl_context': context, 'timeout': self.settings.number('DB_TIMEOUT_SECONDS', 30, high=300)},
                isolation_level='REPEATABLE READ', pool_pre_ping=True, hide_parameters=True, pool_size=2, max_overflow=0)
        return self.engine

    def _cap(self):
        return self.settings.number('MAX_SOURCE_ROWS', 100000, high=1000000)

    def _columns(self, connection, relation):
        schema, table = relation.split('.')
        rows = connection.execute(text('SELECT column_name FROM information_schema.columns WHERE table_schema = :schema AND table_name = :table ORDER BY ordinal_position'),
                                  {'schema': schema, 'table': table}).fetchall()
        if not rows:
            raise AppError(f'The raw table {relation} does not exist or is not readable by the configured read-only user.')
        return resolve_columns([row[0] for row in rows], f'raw table {relation}')

    def _read(self, connection, relation, mapping):
        cap = self._cap()
        selected = ', '.join(f'{quoted_identifier(mapping[field])} AS {quoted_identifier(field)}' for field in RAW_COLUMNS)
        rows = connection.execute(text(f'SELECT {selected} FROM {quoted_relation(relation)} LIMIT :cap'), {'cap': cap + 1}).fetchall()
        if len(rows) > cap:
            raise AppError(f'The source exceeds {cap:,} rows. Increase MAX_SOURCE_ROWS before computing complete totals.')
        return pd.DataFrame(rows, columns=RAW_COLUMNS, dtype=object)

    def load_raw(self):
        """Read the configured source once and return (raw frame, source kind, source name)."""
        kind = self.settings.get('DB_KIND', 'demo')
        if kind == 'demo':
            return pd.DataFrame(demo_rows(), columns=RAW_COLUMNS, dtype=object), 'demo', 'fictional demo data'
        if kind == 'csv':
            path = self.settings.csv_path
            return read_csv_source(path, self.settings.get('B2B_CSV_ENCODING') or 'utf-8-sig', self._cap()), 'csv', path.name
        relation = self.settings.get('B2B_RAW_TABLE') or 'bi_reporting.b2b_project'
        try:
            with self._engine().connect() as connection:
                with connection.begin():
                    # One read-only, repeatable-read transaction per snapshot.
                    connection.execute(text('SET TRANSACTION READ ONLY'))
                    connection.execute(text(f"SET LOCAL statement_timeout = {self.settings.number('DB_TIMEOUT_SECONDS', 30, high=300) * 1000}"))
                    raw = self._read(connection, relation, self._columns(connection, relation))
        except AppError:
            raise
        except Exception:
            raise AppError('PostgreSQL read failed. Check the read-only credentials, source schema, TLS, and connection timeout.') from None
        return raw, 'postgres', relation

    def load(self):
        raw, source, source_name = self.load_raw()
        views = build_canonical_views(raw)
        views.source, views.source_name = source, source_name
        return views
