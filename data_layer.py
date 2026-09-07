"""Canonical Salesforce grains, with matching database-view and Pandas paths."""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import re
import ssl

import pandas as pd
from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import DBAPIError

from app_config import AppError, SCHEMA_VERSION

TEXT_FIELDS = ['opportunity_no','product_code','subsidiary_subsidiary_code','opportunity_name','end_customer',
               'gscm_product_group_new','pet_name','stage','opportunity_owner','biz_focus','business_location',
               'division','sales_type_detail','type','amount_converted_currency','opp_amount_converted_currency',
               'rollout_period_to','rollout_period_from']
DATE_FIELDS = ['close_month','close_date','created_date','last_modified_date']
RAW_COLUMNS = TEXT_FIELDS + ['quantity','amount_converted','opp_amount_converted','probability'] + DATE_FIELDS
SKU_METADATA = [f for f in TEXT_FIELDS if f not in ('opportunity_no','product_code')]
OPPORTUNITY_METADATA = [f for f in SKU_METADATA if f not in ('gscm_product_group_new','pet_name','amount_converted_currency')]
QUALITY_FIELDS = ['exported_opp_amount','opportunity_name','end_customer','pet_name','gscm_product_group_new',
                  'stage','opportunity_owner','amount_converted_currency']
SKU_COLUMNS = ['opportunity_no','product_code'] + SKU_METADATA + ['quantity','sku_amount','exported_opp_amount_min',
    'exported_opp_amount_max','exported_opp_amount_value_count','probability'] + DATE_FIELDS + ['source_row_count','has_quality_warning']
OPPORTUNITY_COLUMNS = ['opportunity_no'] + OPPORTUNITY_METADATA + ['probability'] + DATE_FIELDS + ['quantity','opportunity_amount',
    'sku_count','source_row_count','product_codes','product_names','exported_opp_amount_min','exported_opp_amount_max',
    'has_amount_discrepancy','has_quality_warning']
NUMBER_FIELDS = {'quantity','sku_amount','opportunity_amount','exported_opp_amount_min','exported_opp_amount_max','exported_opp_amount_value_count',
                 'probability','sku_count','source_row_count'}
BOOL_FIELDS = {'has_quality_warning','has_amount_discrepancy'}
STAGE_GROUPS = {'Won':('Won','Rollout Started','Rollout Finished'), 'Open':('Identified','Qualified','Negotiation'), 'Lost':('Dropped','Lost')}
NUMERIC = re.compile(r'^[+-]?[0-9]+([.][0-9]+)?$')
PROBABILITY = re.compile(r'^[0-9]+([.][0-9]+)?%?$')


def clean_text(value):
    if value is None or pd.isna(value):
        return None
    # Match PostgreSQL btrim(text): trim U+0020, retaining embedded whitespace.
    value = str(value).strip(' ')
    return value or None


def clean_number(value, probability=False):
    value = clean_text(value)
    if not value or not (PROBABILITY if probability else NUMERIC).fullmatch(value):
        return None
    return Decimal(value.rstrip('%')) / 100 if probability else Decimal(value)


def clean_date(value):
    if isinstance(value,date):
        return value.date() if isinstance(value,datetime) else value
    value = clean_text(value)
    if not value or not re.fullmatch(r'[0-9]{2}/[0-9]{2}/[0-9]{4}',value):
        return None
    try:
        return datetime.strptime(value,'%d/%m/%Y').date()
    except ValueError:
        return None


def present(values):
    return [v for v in values if v is not None and not pd.isna(v)]


def sql_min(values):
    return min(present(values),default=None)


def sql_max(values):
    return max(present(values),default=None)


def sql_sum(values):
    items = present(values)
    return sum(items,Decimal(0)) if items else None


def stage_group(value):
    return next((name for name,stages in STAGE_GROUPS.items() if value in stages),None)


@dataclass
class CanonicalViews:
    sku: pd.DataFrame
    opportunity: pd.DataFrame
    source: str = 'pandas'
    excluded_rows: int | None = 0
    fallback_reason: str | None = None


def build_canonical_views(raw):
    raw = raw if isinstance(raw,pd.DataFrame) else pd.DataFrame(raw,dtype=object)
    if raw.empty and not len(raw.columns):
        raw = pd.DataFrame(columns=RAW_COLUMNS,dtype=object)
    missing = set(RAW_COLUMNS) - set(raw.columns)
    if missing:
        raise AppError('Raw Salesforce source is missing required columns: ' + ', '.join(sorted(missing)))
    normalized = []
    excluded = 0
    for source in raw.to_dict('records'):
        row = {name:clean_text(source[name]) for name in TEXT_FIELDS}
        if row['opportunity_no'] is None or row['product_code'] is None:
            excluded += 1
            continue
        row.update({name:clean_date(source[name]) for name in DATE_FIELDS})
        row.update(quantity=clean_number(source['quantity']), amount_converted=clean_number(source['amount_converted']),
                   exported_opp_amount=clean_number(source['opp_amount_converted']), probability=clean_number(source['probability'],True))
        normalized.append(row)
    # Reduce record groups before constructing DataFrames. Creating one Series per
    # field per group dominates runtime for tens of thousands of small groups.
    by_sku={}
    for row in normalized:
        by_sku.setdefault((row['opportunity_no'],row['product_code']),[]).append(row)
    sku_rows = []
    for (opportunity,product),group in sorted(by_sku.items()):
        values={name:[row[name] for row in group] for name in group[0]}
        row = {'opportunity_no':opportunity,'product_code':product}
        row.update({name:sql_min(values[name]) for name in SKU_METADATA})
        row.update({name:(sql_max if name=='last_modified_date' else sql_min)(values[name]) for name in DATE_FIELDS})
        row.update(quantity=sql_sum(values['quantity']),sku_amount=sql_sum(values['amount_converted']),
                   exported_opp_amount_min=sql_min(values['exported_opp_amount']),exported_opp_amount_max=sql_max(values['exported_opp_amount']),
                   exported_opp_amount_value_count=len(set(present(values['exported_opp_amount']))), probability=sql_min(values['probability']),
                   source_row_count=len(group), has_quality_warning=any(len(set(present(values[name])))>1 for name in QUALITY_FIELDS))
        sku_rows.append(row)
    sku = pd.DataFrame(sku_rows,columns=SKU_COLUMNS,dtype=object)
    by_opportunity={}
    for row in sku_rows:
        by_opportunity.setdefault(row['opportunity_no'],[]).append(row)
    opportunity_rows = []
    for opportunity,group in sorted(by_opportunity.items()):
        values={name:[row[name] for row in group] for name in group[0]}
        row = {'opportunity_no':opportunity}
        row.update({name:sql_min(values[name]) for name in OPPORTUNITY_METADATA})
        row.update({name:(sql_max if name=='last_modified_date' else sql_min)(values[name]) for name in DATE_FIELDS})
        amount = sql_sum(values['sku_amount'])
        lower,upper = sql_min(values['exported_opp_amount_min']),sql_max(values['exported_opp_amount_max'])
        discrepancy = lower is None or upper is None or amount is None or lower != upper or abs(amount-upper)>Decimal('0.01')
        row.update(probability=sql_min(values['probability']),quantity=sql_sum(values['quantity']),opportunity_amount=amount,
                   sku_count=len(group),source_row_count=int(sum(values['source_row_count'])),
                   product_codes=', '.join(sorted(set(present(values['product_code'])))) or None,
                   product_names=', '.join(sorted(set(present(values['pet_name'])))) or None,
                   exported_opp_amount_min=lower,exported_opp_amount_max=upper,has_amount_discrepancy=discrepancy,
                   has_quality_warning=bool(any(values['has_quality_warning']) or discrepancy))
        opportunity_rows.append(row)
    return CanonicalViews(sku,pd.DataFrame(opportunity_rows,columns=OPPORTUNITY_COLUMNS,dtype=object),excluded_rows=excluded)


def demo_rows():
    def row(opp,sku,amount,quantity,parent,**extra):
        return dict.fromkeys(RAW_COLUMNS) | {'opportunity_no':opp,'product_code':sku,'amount_converted':str(amount),
            'quantity':str(quantity),'opp_amount_converted':str(parent),'stage':'Won','opportunity_owner':'Alex',
            'end_customer':'Example North','opportunity_name':'Example project','pet_name':sku+' product',
            'amount_converted_currency':'EUR','opp_amount_converted_currency':'EUR','probability':'75%',
            'close_date':'15/10/2026','close_month':'01/10/2026'} | extra
    return [row('OPP-001','SKU-A',400,2,750),row('OPP-001','SKU-A',200,1,750),row('OPP-001','SKU-B',150,1,750),
            row('OPP-002','SKU-B',450,3,500,stage='Rollout Started',opportunity_owner='Blair'),
            row('OPP-003','SKU-C',2400,2,2400,stage='Qualified',end_customer='Example East')]


def quoted_relation(name):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*',name):
        raise AppError('Invalid database relation configuration.')
    return '.'.join('"'+part+'"' for part in name.split('.'))


class DataRepository:
    def __init__(self,settings,engine=None):
        self.settings,self.engine = settings,engine

    def _engine(self):
        if self.engine is None:
            options = self.settings.postgres
            context = ssl.create_default_context(cafile=self.settings.get('DB_CA_FILE') or None) if self.settings.flag('DB_SSL',True) else False
            url = URL.create('postgresql+pg8000',username=self.settings.get('RO_SQL_USER') or self.settings.get('DB_USER'),
                password=self.settings.get('RO_SQL_PW') or self.settings.get('DB_PASSWORD'),**options)
            self.engine = create_engine(url,connect_args={'ssl_context':context,'timeout':self.settings.number('DB_TIMEOUT_SECONDS',30,high=300)},
                isolation_level='REPEATABLE READ',pool_pre_ping=True,hide_parameters=True,pool_size=2,max_overflow=0)
        return self.engine

    def _read(self,connection,relation,columns):
        cap = self.settings.number('MAX_SOURCE_ROWS',100000,high=1000000)
        selected = ', '.join('"'+column+'"' for column in columns)
        rows = connection.execute(text(f'SELECT {selected} FROM {quoted_relation(relation)} LIMIT :cap'),{'cap':cap+1}).fetchall()
        if len(rows)>cap:
            raise AppError(f'The source exceeds {cap:,} rows. Increase MAX_SOURCE_ROWS before computing complete totals.')
        return pd.DataFrame(rows,columns=columns,dtype=object)

    def load(self):
        if self.settings.get('DB_KIND','demo') == 'demo':
            views=build_canonical_views(demo_rows()); views.source='demo'; return views
        try:
            with self._engine().connect() as connection:
                with connection.begin():
                    connection.execute(text('SET TRANSACTION READ ONLY'))
                    connection.execute(text(f"SET LOCAL statement_timeout = {self.settings.number('DB_TIMEOUT_SECONDS',30,high=300)*1000}"))
                    try:
                        # The savepoint is rolled back on a denied/missing view before raw fallback.
                        with connection.begin_nested():
                            version_table=quoted_relation(self.settings.get('B2B_SCHEMA_VERSION_TABLE','bi_reporting.b2b_project_schema_version'))
                            version=connection.execute(text(f'SELECT max(version) FROM {version_table}')).scalar()
                            if version != SCHEMA_VERSION:
                                raise AppError('Database schema version differs from this release. Apply the matching migration or use a compatible release.')
                            sku=self._read(connection,self.settings.get('B2B_SKU_VIEW','bi_reporting.b2b_project_sku_v'),SKU_COLUMNS)
                            opportunity=self._read(connection,self.settings.get('B2B_OPPORTUNITY_VIEW','bi_reporting.b2b_project_opportunity_v'),OPPORTUNITY_COLUMNS)
                        return CanonicalViews(sku,opportunity,source='database_views',excluded_rows=None)
                    except DBAPIError as error:
                        original=error.orig
                        code=getattr(original,'pgcode',None) or getattr(original,'sqlstate',None)
                        if not code and original.args and isinstance(original.args[0],dict):
                            code=original.args[0].get('C')
                        if code not in ('42P01','42501'):
                            raise
                        raw=self._read(connection,self.settings.get('B2B_RAW_TABLE','bi_reporting.b2b_project'),RAW_COLUMNS)
                        views=build_canonical_views(raw)
                        views.fallback_reason='Canonical views or version metadata are missing or not readable.'
                        return views
        except AppError:
            raise
        except Exception:
            raise AppError('PostgreSQL read failed. Check the read-only credentials, source schema, TLS, and connection timeout.') from None
