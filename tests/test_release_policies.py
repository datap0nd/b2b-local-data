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
        for name in ('release_manifest.json','dependencies.lock.json'):shutil.copyfile(ROOT/name,self.root/name)
    def tearDown(self):self.temp.cleanup()
    def test_supplied_manifest_matches_contract_and_lock(self):verify_release(self.root,False)
    def test_changed_release_values_block_launch(self):
        original=json.loads((self.root/'release_manifest.json').read_text())
        for key,value in [('app_version','other'),('database_schema_version',2),('query_plan_version',2),('python_tag','cp312'),('platform','win_arm64')]:
            with self.subTest(key=key):
                (self.root/'release_manifest.json').write_text(json.dumps(original|{key:value}))
                with self.assertRaises(AppError):verify_release(self.root,False)
    def test_changed_dependency_lock_blocks_launch(self):
        with (self.root/'dependencies.lock.json').open('a') as stream:stream.write(' ')
        with self.assertRaises(AppError):verify_release(self.root,False)
    def test_env_and_manual_names(self):
        (self.root/'.env').write_text('PGURL=database.example:5432/postgres\nRO_SQL_PW="abc#def=$HOME"\nLLM_API_URL=http://127.0.0.1:4002/v1/chat/completions\n')
        with patch.dict('os.environ',{'RO_SQL_PW':'override'},clear=True):
            settings=Settings.load(self.root)
        self.assertEqual(settings.get('DB_KIND'),'postgres')
        self.assertEqual(settings.get('RO_SQL_PW'),'override')
        self.assertEqual(settings.postgres['database'],'postgres')
        self.assertEqual(read_env(self.root/'.env')['RO_SQL_PW'],'abc#def=$HOME')
    def test_legacy_variables_remain_accepted(self):
        with patch.dict('os.environ',{'DB_KIND':'demo','AI_MODEL':'old-model','AI_BASE_URL':'http://localhost:9000/v1','AI_API_KEY':'local-key'},clear=True):
            settings=Settings.load(self.root)
        self.assertEqual(settings.get('LLM_MODEL_NAME'),'old-model')
        self.assertEqual(settings.get('LLM_API_KEY'),'local-key')
    def test_environment_alias_overrides_file_canonical_name(self):
        (self.root/'.env').write_text('LLM_MODEL_NAME=file-model\n')
        with patch.dict('os.environ',{'AI_MODEL':'environment-model'},clear=True):
            settings=Settings.load(self.root)
        self.assertEqual(settings.get('LLM_MODEL_NAME'),'environment-model')
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
