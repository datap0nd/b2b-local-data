import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app_config import AppError,ROOT,Settings,read_env,verify_release
from updater import rollback


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        for name in ('release_manifest.json','dependencies.lock.json','runtime.lock.json','portable_assets.lock.json'):shutil.copyfile(ROOT/name,self.root/name)
    def tearDown(self):self.temp.cleanup()
    def test_supplied_manifest_matches_contract_and_lock(self):verify_release(self.root,False)
    def test_changed_release_values_block_launch(self):
        original=json.loads((self.root/'release_manifest.json').read_text())
        for key,value in [('app_version','other'),('data_schema_version',1),('query_plan_version',2),('python_tag','cp312'),('platform','win_arm64')]:
            with self.subTest(key=key):
                (self.root/'release_manifest.json').write_text(json.dumps(original|{key:value}))
                with self.assertRaises(AppError):verify_release(self.root,False)
    def test_changed_dependency_lock_blocks_launch(self):
        with (self.root/'dependencies.lock.json').open('a') as stream:stream.write(' ')
        with self.assertRaises(AppError):verify_release(self.root,False)
    def test_changed_portable_locks_block_launch(self):
        for name in ('runtime.lock.json','portable_assets.lock.json'):
            with self.subTest(name=name):
                original=(self.root/name).read_bytes()
                (self.root/name).write_bytes(original+b' ')
                with self.assertRaises(AppError):verify_release(self.root,False)
                (self.root/name).write_bytes(original)
    def test_env_and_manual_names(self):
        (self.root/'.env').write_text('PGURL=database.example:5432/postgres\nRO_SQL_PW="abc#def=$HOME"\nLLM_API_URL=http://127.0.0.1:4002/v1/chat/completions\n')
        with patch.dict('os.environ',{'RO_SQL_PW':'override'},clear=True):
            settings=Settings.load(self.root)
        self.assertEqual(settings.get('DB_KIND'),'postgres')
        self.assertEqual(settings.get('RO_SQL_PW'),'override')
        self.assertEqual(settings.postgres['database'],'postgres')
        self.assertEqual(read_env(self.root/'.env')['RO_SQL_PW'],'abc#def=$HOME')
    def test_mixed_case_env_keys_such_as_DG_GITHUB_TOKEN_are_accepted(self):
        (self.root/'.env').write_text('DG_GITHUB_TOKEN=abc\nDB_KIND=demo\n')
        self.assertEqual(read_env(self.root/'.env')['DG_GITHUB_TOKEN'],'abc')
        with patch.dict('os.environ',{},clear=True):self.assertEqual(Settings.load(self.root).get('DG_GITHUB_TOKEN'),'abc')
        (self.root/'.env').write_text('1BAD=x\n')
        with self.assertRaises(AppError):read_env(self.root/'.env')
    def test_data_governance_variables_configure_database_and_model(self):
        environment={'PGHOST':'db.internal','PGUSER':'reader','PGPASSWORD':'pw','DG_AI_API_URL':'http://10.20.30.40:8000/v1','DG_AI_API_KEY':'k','DG_AI_MODEL':'Qwen/Qwen3.8-27B'}
        with patch.dict('os.environ',environment,clear=True):settings=Settings.load(self.root)
        self.assertEqual(settings.get('DB_KIND'),'postgres');self.assertEqual(settings.postgres,{'host':'db.internal','port':5432,'database':'postgres'})
        self.assertEqual((settings.get('RO_SQL_USER'),settings.get('RO_SQL_PW')),('reader','pw'))
        self.assertEqual((settings.get('LLM_API_URL'),settings.get('LLM_API_KEY'),settings.get('LLM_MODEL_NAME'),settings.get('AI_PROVIDER')),('http://10.20.30.40:8000/v1','k','Qwen/Qwen3.8-27B','openai_compatible'))
        self.assertIn('10.20.30.40',settings.get('B2B_LLM_ALLOWED_HOSTS'))
        self.assertEqual(settings.source_label,'PostgreSQL bi_reporting.b2b_project');self.assertEqual(settings.get('DB_SSL'),'prefer')
        with patch.dict('os.environ',environment|{'DB_SSL':'true'},clear=True):self.assertEqual(Settings.load(self.root).get('DB_SSL'),'true')
        with patch.dict('os.environ',{'DB_KIND':'demo'},clear=True):self.assertEqual(Settings.load(self.root).get('DB_SSL'),'prefer')
        with patch.dict('os.environ',{'DB_KIND':'demo','DB_SSL':'maybe'},clear=True),self.assertRaises(AppError):Settings.load(self.root)
        with patch.dict('os.environ',environment|{'PGPORT':'6543','PGDATABASE':'bi'},clear=True):self.assertEqual(Settings.load(self.root).postgres,{'host':'db.internal','port':6543,'database':'bi'})
        # A model or database chosen in .env beats the data-governance values from the environment.
        (self.root/'.env').write_text('LLM_MODEL_NAME=my-qwen\nPGURL=other.example:5432/app\n')
        with patch.dict('os.environ',environment,clear=True):settings=Settings.load(self.root)
        self.assertEqual(settings.get('LLM_MODEL_NAME'),'my-qwen');self.assertEqual(settings.postgres['host'],'other.example')
        with patch.dict('os.environ',environment|{'LLM_MODEL_NAME':'env-qwen'},clear=True):self.assertEqual(Settings.load(self.root).get('LLM_MODEL_NAME'),'env-qwen')
    def test_pghost_shapes_derive_a_valid_pgurl(self):
        from app_config import derive_pgurl
        self.assertEqual(derive_pgurl('db.internal'),'db.internal:5432/postgres')
        self.assertEqual(derive_pgurl('db.internal:6543','',''),'db.internal:6543/postgres')
        self.assertEqual(derive_pgurl('db.internal','6543','bi'),'db.internal:6543/bi')
        self.assertEqual(derive_pgurl('postgresql://db.internal:6543/bi'),'db.internal:6543/bi')
        self.assertEqual(derive_pgurl('db.internal/bi','abc'),'db.internal:5432/bi')
        for host in ('db.internal:6543','postgresql://db.internal/bi','db.internal/bi/'):
            with patch.dict('os.environ',{'PGHOST':host,'PGUSER':'u','PGPASSWORD':'p'},clear=True):self.assertEqual(Settings.load(self.root).postgres['host'],'db.internal')
    def test_local_ai_variables_configure_the_model(self):
        environment={'local_ai_endpoint':'http://10.1.2.3:8001/v1','LOCAL_AI_API_KEY':'k2','Local_AI_Model':'my-model','DG_AI_API_URL':'http://ignored:1/v1','DG_AI_MODEL':'gemma'}
        with patch.dict('os.environ',environment,clear=True):settings=Settings.load(self.root)
        self.assertEqual((settings.get('LLM_API_URL'),settings.get('LLM_API_KEY'),settings.get('LLM_MODEL_NAME')),('http://10.1.2.3:8001/v1','k2','my-model'))
        self.assertIn('10.1.2.3',settings.get('B2B_LLM_ALLOWED_HOSTS'))
        (self.root/'.env').write_text('local_ai_endpoint=http://192.168.5.5:9000/v1\nLLM_MODEL_NAME=chosen\n')
        with patch.dict('os.environ',{'LOCAL_AI_MODEL':'env-model'},clear=True):settings=Settings.load(self.root)
        self.assertEqual((settings.get('LLM_API_URL'),settings.get('LLM_MODEL_NAME')),('http://192.168.5.5:9000/v1','chosen'))
        self.assertEqual(settings.source_of('LLM_API_URL'),'.env LOCAL_AI_ENDPOINT');self.assertEqual(settings.source_of('LLM_MODEL_NAME'),'.env LLM_MODEL_NAME (overriding LOCAL_AI_MODEL)')
        self.assertEqual(settings.source_of('AI_TIMEOUT_SECONDS'),'default')
    def test_legacy_variables_remain_accepted(self):
        with patch.dict('os.environ',{'DB_KIND':'demo','AI_MODEL':'old-model','AI_BASE_URL':'http://localhost:9000/v1','AI_API_KEY':'local-key'},clear=True):
            settings=Settings.load(self.root)
        self.assertEqual(settings.get('LLM_MODEL_NAME'),'old-model')
        self.assertEqual(settings.get('LLM_API_KEY'),'local-key')
    def test_file_canonical_name_beats_environment_alias(self):
        (self.root/'.env').write_text('LLM_MODEL_NAME=file-model\n')
        with patch.dict('os.environ',{'AI_MODEL':'environment-model'},clear=True):
            settings=Settings.load(self.root)
        self.assertEqual(settings.get('LLM_MODEL_NAME'),'file-model')
        (self.root/'.env').write_text('AI_MODEL=file-alias\n')
        with patch.dict('os.environ',{'AI_MODEL':'environment-alias'},clear=True):self.assertEqual(Settings.load(self.root).get('LLM_MODEL_NAME'),'environment-alias')
    def test_manifest_describes_canonical_data_schema(self):
        manifest=json.loads((self.root/'release_manifest.json').read_text())
        self.assertEqual(manifest['app_version'],'0.6.0');self.assertEqual(manifest['data_schema_version'],2)
        self.assertNotIn('database_schema_version',manifest)
        self.assertEqual((ROOT/'VERSION').read_text().strip(),'0.6.0')
    def test_csv_source_configuration(self):
        (self.root/'.env').write_text('DB_KIND=csv\nB2B_CSV_PATH=exports/salesforce.csv\n')
        with patch.dict('os.environ',{},clear=True):settings=Settings.load(self.root)
        self.assertEqual(settings.csv_path,(self.root/'exports/salesforce.csv').resolve())
        self.assertEqual(settings.source_label,'CSV file salesforce.csv')
        absolute=str((self.root/'elsewhere.csv').resolve())
        with patch.dict('os.environ',{'B2B_CSV_PATH':absolute},clear=True):self.assertEqual(str(Settings.load(self.root).csv_path),absolute)
        (self.root/'.env').write_text('DB_KIND=csv\n')
        with patch.dict('os.environ',{},clear=True),self.assertRaises(AppError):Settings.load(self.root)
        (self.root/'.env').write_text('DB_KIND=sqlite\n')
        with patch.dict('os.environ',{},clear=True),self.assertRaises(AppError):Settings.load(self.root)
        (self.root/'.env').write_text('PGURL=database.example:5432/postgres\nB2B_CSV_PATH=exports/salesforce.csv\n')
        with patch.dict('os.environ',{},clear=True):settings=Settings.load(self.root)
        self.assertEqual(settings.get('DB_KIND'),'postgres');self.assertEqual(settings.source_label,'PostgreSQL bi_reporting.b2b_project')
    def test_rollback_preserves_local_data_and_checks_containment(self):
        release=self.root/'releases/previous';release.mkdir(parents=True);(release/'run.py').write_text('')
        runtime=self.root/'runtime/python';runtime.mkdir(parents=True);(runtime/'python.exe').write_text('')
        pointer={'release':str(release),'python':str(runtime/'python.exe'),'commit':'previous'}
        (self.root/'previous.json').write_text(json.dumps(pointer));(self.root/'.env').write_text('sentinel')
        rollback(self.root)
        self.assertEqual(json.loads((self.root/'current.json').read_text()),pointer)
        self.assertEqual((self.root/'.env').read_text(),'sentinel')
        command=subprocess.run([sys.executable,str(ROOT/'updater.py'),'--home',str(self.root)],cwd=self.root,capture_output=True,text=True)
        self.assertEqual(command.returncode,0,command.stderr)
        self.assertIn('Selected commit: previous',command.stdout)
        (self.root/'previous.json').write_text(json.dumps(pointer|{'release':str(self.root.parent)}))
        with self.assertRaises(AppError):rollback(self.root)
