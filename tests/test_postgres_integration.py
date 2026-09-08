"""Runs only against an explicitly configured disposable loopback PostgreSQL instance."""
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
import uuid
from urllib.parse import urlsplit

import pg8000.dbapi
from sqlalchemy import URL,create_engine,event

from app_config import ROOT,AppError,Settings
from data_layer import RAW_COLUMNS,SQL_COLUMNS,DataRepository,build_canonical_views
from query_engine import QueryExecutor,parse_plan

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_csv_source import fixture_rows,write_export


@unittest.skipUnless(os.environ.get('B2B_TEST_PGURL'),'Disposable PostgreSQL is not configured')
class PostgreSQLParityTests(unittest.TestCase):
    def setUp(self):
        parsed=urlsplit('postgresql://'+os.environ['B2B_TEST_PGURL'])
        if parsed.hostname not in ('127.0.0.1','localhost','::1'):
            raise RuntimeError('Integration tests require a disposable loopback database.')
        self.options={'host':parsed.hostname,'port':parsed.port or 5432,'database':parsed.path.lstrip('/'),
            'user':os.environ.get('B2B_TEST_PGUSER','postgres'),'password':os.environ.get('B2B_TEST_PGPASSWORD',''),'ssl_context':False,'timeout':10}
        self.connection=pg8000.dbapi.connect(**self.options);self.connection.autocommit=True
        self.cursor=self.connection.cursor();self.schema='b2b_test_'+uuid.uuid4().hex;self.role=self.schema+'_reader'
        self.engines=[];self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.cursor.execute(f'CREATE SCHEMA {self.schema}')
        # The raw table stores every one of the 30 columns as text, exactly as the extract does; 1st_channel needs quoting.
        fields=', '.join('"'+SQL_COLUMNS[name]+'" text' for name in RAW_COLUMNS)
        self.cursor.execute(f'CREATE TABLE {self.schema}.b2b_project ({fields})')
        self.rows=fixture_rows()
        placeholders=', '.join(['%s']*len(RAW_COLUMNS))
        self.cursor.executemany(f'INSERT INTO {self.schema}.b2b_project VALUES ({placeholders})',[[row[name] for name in RAW_COLUMNS] for row in self.rows])
        self.settings=Settings(self.home,{'DB_KIND':'postgres','B2B_RAW_TABLE':self.schema+'.b2b_project'})
    def tearDown(self):
        for engine in self.engines:engine.dispose()
        if not re.fullmatch(r'b2b_test_[a-f0-9]{32}',self.schema):raise RuntimeError('Unexpected test schema')
        self.cursor.execute(f'DROP SCHEMA {self.schema} CASCADE')
        self.cursor.execute(f'DROP ROLE IF EXISTS {self.role}')
        self.connection.close();self.temp.cleanup()
    def test_segmented_materialized_view_is_discovered_and_read(self):
        self.cursor.execute(f"UPDATE {self.schema}.b2b_project SET biz_group='SMART', seg_1='FLAGSHIP', seg_2='S', seg_3='S(N)', series='Example series'")
        self.cursor.execute(f'CREATE MATERIALIZED VIEW {self.schema}.b2b_project_segmented AS SELECT * FROM {self.schema}.b2b_project')
        settings = Settings(self.home, {'DB_KIND':'postgres', 'B2B_RAW_TABLE':self.schema+'.b2b_project_segmented'})
        raw, source, relation = DataRepository(settings, self.engine()).load_raw()
        self.assertEqual((source, relation), ('postgres', self.schema+'.b2b_project_segmented'))
        self.assertEqual(set(raw['seg_3']), {'S(N)'})
        self.assertEqual(len(raw), len(self.rows))
    def engine(self,restricted=False):
        url=URL.create('postgresql+pg8000',username=self.options['user'],password=self.options['password'],host=self.options['host'],port=self.options['port'],database=self.options['database'])
        engine=create_engine(url,isolation_level='REPEATABLE READ',connect_args={'ssl_context':False},hide_parameters=True)
        if restricted:
            self.cursor.execute(f'CREATE ROLE {self.role}')
            self.cursor.execute(f'GRANT USAGE ON SCHEMA {self.schema} TO {self.role}')
            self.cursor.execute(f'GRANT SELECT ON {self.schema}.b2b_project TO {self.role}')
            @event.listens_for(engine,'connect')
            def set_role(connection,record):
                cursor=connection.cursor();cursor.execute(f'SET ROLE {self.role}');connection.commit();cursor.close()
        self.engines.append(engine);return engine
    def assert_parity(self,actual,expected):
        for name,keys in [('sku',['opportunity_no','product_code']),('opportunity',['opportunity_no'])]:
            first=getattr(actual,name).sort_values(keys).to_dict('records')
            second=getattr(expected,name).sort_values(keys).to_dict('records')
            self.assertEqual(first,second)
        self.assertEqual(actual.excluded_rows,expected.excluded_rows)
    def test_raw_table_matches_local_parser(self):
        actual=DataRepository(self.settings,self.engine()).load()
        self.assertEqual((actual.source,actual.source_name),('postgres',self.schema+'.b2b_project'))
        self.assert_parity(actual,build_canonical_views(self.rows))
        self.assertEqual(len(actual.opportunity),4);self.assertEqual(len(actual.sku),5);self.assertEqual(actual.excluded_rows,1)
        self.assertEqual(actual.sku.set_index(['opportunity_no','product_code']).loc[('00042','0007')].subsidiary_subsidiary_code,'010')
    def test_select_only_role_reads_the_raw_table(self):
        actual=DataRepository(self.settings,self.engine(restricted=True)).load()
        self.assert_parity(actual,build_canonical_views(self.rows))
    def test_declared_sql_adapter_mapping_has_hand_derived_asymmetric_totals(self):
        # Adapter behavior is tested against invented source definitions. This
        # does not confirm what similarly named columns mean in a live export.
        self.cursor.execute(f'DELETE FROM {self.schema}.b2b_project')
        rows=[]
        for product,line in [('A','40'),('B','60')]:
            rows.append(dict.fromkeys(RAW_COLUMNS)|{'opportunity_no':'CONTRACT-1','product_code':product,'amount_converted':'100',
                'opp_amount_converted':line,'amount_converted_currency':'EUR','opp_amount_converted_currency':'USD','quantity':'1'})
        self.cursor.executemany(f'INSERT INTO {self.schema}.b2b_project VALUES ({", ".join(["%s"]*len(RAW_COLUMNS))})',[[row[name] for name in RAW_COLUMNS] for row in rows])
        actual=DataRepository(self.settings,self.engine(restricted=True)).load()
        self.assertEqual([str(value) for value in actual.sku.sku_amount],['40','60'])
        self.assertEqual(str(actual.opportunity.iloc[0].opportunity_amount),'100')
        self.assertEqual(actual.opportunity.iloc[0].opp_amount_converted_currency,'USD')
        self.assertEqual(actual.opportunity.iloc[0].exported_opp_amount_currency,'EUR')
    def test_csv_and_all_text_postgres_inputs_produce_identical_tables_and_totals(self):
        write_export(self.home/'export.csv',self.rows)
        from_csv=DataRepository(Settings(self.home,{'DB_KIND':'csv','B2B_CSV_PATH':'export.csv'})).load()
        from_sql=DataRepository(self.settings,self.engine(restricted=True)).load()
        self.assert_parity(from_sql,from_csv)
        executor=QueryExecutor()
        for values in [{},{'grain':'opportunity_sku'},{'intent':'metric','measures':['amount','quantity','deal_size','opportunity_count','sku_count']},
                       {'intent':'metric','grain':'opportunity_sku','dimensions':['stage_group','first_channel'],'measures':['amount','deal_size']}]:
            with self.subTest(values=values):
                plan=parse_plan(values)
                left,right=executor.execute(from_sql,plan),executor.execute(from_csv,plan)
                self.assertEqual(left['rows'],right['rows']);self.assertEqual(left['source_rows'],right['source_rows'])
        totals=executor.execute(from_sql,parse_plan({'intent':'metric','measures':['amount','deal_size','opportunity_count']}))['rows']
        self.assertEqual(totals,[{'amount':'3610.50','deal_size':'1260.50','opportunity_count':4}])
    def test_missing_column_and_unreadable_table_are_reported(self):
        self.cursor.execute(f'ALTER TABLE {self.schema}.b2b_project DROP COLUMN "1st_channel"')
        with self.assertRaises(AppError) as error:DataRepository(self.settings,self.engine()).load()
        self.assertIn('first_channel (1st_channel)',str(error.exception))
        missing=Settings(self.home,{'DB_KIND':'postgres','B2B_RAW_TABLE':self.schema+'.absent'})
        with self.assertRaises(AppError) as error:DataRepository(missing,self.engine()).load()
        self.assertIn('not readable',str(error.exception))


@unittest.skipUnless(os.environ.get('B2B_TEST_PGURL'),'Disposable PostgreSQL is not configured')
class LegacyViewMigrationTests(unittest.TestCase):
    """Historical date/attribute parsing compatibility only, not current money-contract parity."""
    def setUp(self):
        parsed=urlsplit('postgresql://'+os.environ['B2B_TEST_PGURL'])
        if parsed.hostname not in ('127.0.0.1','localhost','::1'):raise RuntimeError('Integration tests require a disposable loopback database.')
        self.connection=pg8000.dbapi.connect(host=parsed.hostname,port=parsed.port or 5432,database=parsed.path.lstrip('/'),user=os.environ.get('B2B_TEST_PGUSER','postgres'),password=os.environ.get('B2B_TEST_PGPASSWORD',''),ssl_context=False,timeout=10)
        self.connection.autocommit=True;self.cursor=self.connection.cursor();self.schema='b2b_test_'+uuid.uuid4().hex
        self.cursor.execute(f'CREATE SCHEMA {self.schema}')
        self.cursor.execute(f'CREATE TABLE {self.schema}.b2b_project ('+', '.join('"'+SQL_COLUMNS[n]+'" text' for n in RAW_COLUMNS)+')')
        for name in ('001_canonical_views.sql','002_legacy_views_unpadded_dates_and_added_columns.sql'):
            self.cursor.execute((ROOT/'migrations'/name).read_text().replace('bi_reporting.',self.schema+'.'))
    def tearDown(self):
        if not re.fullmatch(r'b2b_test_[a-f0-9]{32}',self.schema):raise RuntimeError('Unexpected test schema')
        self.cursor.execute(f'DROP SCHEMA {self.schema} CASCADE');self.connection.close()
    def test_view_dates_and_added_columns_match_the_local_parser(self):
        dates=['1/12/2022','01/12/2022','29/02/2024','29/02/2023','31/04/2026','9/9/2025','09/9/2025','1/1/26','2026-01-01','','  5/3/2026 ','32/01/2026','0/1/2026',None]
        rows=[]
        for index,value in enumerate(dates):
            rows.append(dict.fromkeys(RAW_COLUMNS)|{'opportunity_no':f'O{index:02d}','product_code':'P','close_month':value,'close_date':value,'created_date':value,'last_modified_date':value,
                                              'quantity':'1','amount_converted':'2.50','opp_amount_converted':'2.50','amount_converted_currency':'USD','opp_amount_converted_currency':'USD',
                                              'first_channel':'Web','age':'12','comment':'note','deal_size_on_pricing_date_usd':'99.5'})
        rows.append(dict(rows[0],comment='other'))   # conflicting attribute inside a pair
        self.cursor.executemany(f'INSERT INTO {self.schema}.b2b_project VALUES ({", ".join(["%s"]*len(RAW_COLUMNS))})',[[r[n] for n in RAW_COLUMNS] for r in rows])
        self.cursor.execute(f'SELECT opportunity_no, close_month, close_date, created_date, last_modified_date, first_channel, age, comment, deal_size_on_pricing_date_usd, has_quality_warning FROM {self.schema}.b2b_project_sku_v ORDER BY opportunity_no')
        local={r['opportunity_no']:r for r in build_canonical_views(rows).sku.to_dict('records')}
        for opp,close_month,close_date,created,modified,channel,age,comment,deal,warning in self.cursor.fetchall():
            with self.subTest(opportunity=opp,raw=dates[int(opp[1:])]):
                mine=local[opp]
                self.assertEqual((close_month,close_date,created,modified),(mine['close_month'],mine['close_date'],mine['created_date'],mine['last_modified_date']))
                self.assertEqual((channel,str(age),comment,str(deal),warning),(mine['first_channel'],str(mine['age']),mine['comment'],str(mine['deal_size_on_pricing_date_usd']),bool(mine['has_quality_warning'])))
        self.cursor.execute(f'SELECT max(version) FROM {self.schema}.b2b_project_schema_version');self.assertEqual(self.cursor.fetchone()[0],2)
        self.cursor.execute(f'SELECT opportunity_no, first_channel, deal_size_on_pricing_date_usd, has_quality_warning FROM {self.schema}.b2b_project_opportunity_v WHERE opportunity_no=%s',('O00',))
        self.assertEqual([tuple(map(str,r)) for r in self.cursor.fetchall()],[('O00','Web','99.5','True')])
