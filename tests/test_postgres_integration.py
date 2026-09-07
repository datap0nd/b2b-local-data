"""Runs only against an explicitly configured disposable loopback PostgreSQL instance."""
import os
from pathlib import Path
import re
import unittest
import uuid
from urllib.parse import urlsplit

import pg8000.dbapi
from sqlalchemy import URL,create_engine,event

from app_config import ROOT,Settings
from data_layer import RAW_COLUMNS,DataRepository,build_canonical_views,demo_rows


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
        self.engines=[]
        self.cursor.execute(f'CREATE SCHEMA {self.schema}')
        fields=', '.join('"'+name+'" text' for name in RAW_COLUMNS)
        self.cursor.execute(f'CREATE TABLE {self.schema}.b2b_project ({fields})')
        self.rows=demo_rows()+[dict(demo_rows()[0],opportunity_no='OPP-dirty',quantity='bad',amount_converted=None,
            opp_amount_converted=None,close_date='31/04/2026',probability='75%',opportunity_name='  Zeta  '),
            dict(demo_rows()[0],opportunity_no=' '),dict(demo_rows()[0],opportunity_no='OPP-dirty',opportunity_name='Alpha',last_modified_date='29/02/2024')]
        placeholders=', '.join(['%s']*len(RAW_COLUMNS))
        self.cursor.executemany(f'INSERT INTO {self.schema}.b2b_project VALUES ({placeholders})',[[row[name] for name in RAW_COLUMNS] for row in self.rows])
        migration=(ROOT/'migrations/001_canonical_views.sql').read_text().replace('bi_reporting.',self.schema+'.')
        self.cursor.execute(migration)
        self.settings=Settings(Path('.'),{'DB_KIND':'postgres','B2B_RAW_TABLE':self.schema+'.b2b_project',
            'B2B_SKU_VIEW':self.schema+'.b2b_project_sku_v','B2B_OPPORTUNITY_VIEW':self.schema+'.b2b_project_opportunity_v',
            'B2B_SCHEMA_VERSION_TABLE':self.schema+'.b2b_project_schema_version'})
    def tearDown(self):
        for engine in self.engines:engine.dispose()
        if not re.fullmatch(r'b2b_test_[a-f0-9]{32}',self.schema):raise RuntimeError('Unexpected test schema')
        self.cursor.execute(f'DROP SCHEMA {self.schema} CASCADE')
        self.cursor.execute(f'DROP ROLE IF EXISTS {self.role}')
        self.connection.close()
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
    def assert_parity(self,actual):
        expected=build_canonical_views(self.rows)
        for name,keys in [('sku',['opportunity_no','product_code']),('opportunity',['opportunity_no'])]:
            first=getattr(actual,name).sort_values(keys).to_dict('records')
            second=getattr(expected,name).sort_values(keys).to_dict('records')
            self.assertEqual(first,second)
    def test_postgres_views_match_local_reconstruction(self):
        actual=DataRepository(self.settings,self.engine()).load()
        self.assertEqual(actual.source,'database_views');self.assert_parity(actual)
    def test_actual_read_only_role_falls_back_to_raw(self):
        actual=DataRepository(self.settings,self.engine(restricted=True)).load()
        self.assertTrue(actual.fallback_reason);self.assert_parity(actual)
