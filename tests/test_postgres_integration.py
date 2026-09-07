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

from app_config import AppError,Settings
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
