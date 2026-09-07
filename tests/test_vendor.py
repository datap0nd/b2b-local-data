"""Exercise dependency changes, reuse, and corruption with small local wheel fixtures."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from app_config import ROOT

spec=importlib.util.spec_from_file_location('portable_vendor',ROOT/'scripts/vendor_dependencies.py')
portable_vendor=importlib.util.module_from_spec(spec);spec.loader.exec_module(portable_vendor)


class VendorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.cache=self.root/'downloads';self.cache.mkdir();self.store=self.root/'packages'
        self.lock=self.root/'lock.json';self.target=self.root/'vendor'
    def tearDown(self):self.temp.cleanup()
    def wheel(self,name,version,files):
        filename=f'{name}-{version}-py3-none-any.whl';path=self.cache/filename
        with ZipFile(path,'w') as archive:
            for key,value in files.items():archive.writestr(key,value)
        return {'name':name,'version':version,'filename':filename,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'url':'https://unused.invalid/'+filename}
    def install(self,packages):
        self.lock.write_text(json.dumps({'packages':packages}))
        with patch.object(portable_vendor,'urlopen',side_effect=AssertionError('Offline install attempted a download')):
            return portable_vendor.vendor(self.cache,True,self.target,self.store,self.lock)
    def test_unchanged_packages_are_not_downloaded_or_unpacked(self):
        package=self.wheel('first','1',{'first.py':'value=1'})
        self.assertEqual(self.install([package]),{'downloaded':0,'unpacked':1,'reused':0})
        self.assertEqual(self.install([package]),{'downloaded':0,'unpacked':0,'reused':1})
    def test_only_changed_package_is_unpacked_and_removed_files_disappear(self):
        first=self.wheel('first','1',{'first.py':'value=1','obsolete.py':'old'})
        second=self.wheel('second','1',{'second.py':'value=2'})
        self.install([first,second])
        changed=self.wheel('first','2',{'first.py':'value=3'})
        self.assertEqual(self.install([changed,second]),{'downloaded':0,'unpacked':1,'reused':1})
        self.assertFalse((self.target/'obsolete.py').exists())
        self.assertEqual((self.target/'first.py').read_text(),'value=3')
    def test_corrupt_cached_payload_is_reconstructed(self):
        package=self.wheel('first','1',{'first.py':'value=1'})
        self.install([package])
        directory,_=portable_vendor.cached_package(self.store,package)
        (directory/'first.py').write_text('corrupt')
        self.assertEqual(self.install([package])['unpacked'],1)
        self.assertEqual((self.target/'first.py').read_text(),'value=1')
    def test_corrupt_archive_does_not_replace_current_vendor(self):
        package=self.wheel('first','1',{'first.py':'value=1'});self.install([package])
        changed=self.wheel('first','2',{'first.py':'value=2'})
        (self.cache/changed['filename']).write_text('corrupt archive')
        with self.assertRaises(ValueError):self.install([changed])
        self.assertEqual((self.target/'first.py').read_text(),'value=1')
    def test_archive_path_traversal_is_rejected(self):
        package=self.wheel('first','1',{'../escape.py':'bad'})
        with self.assertRaises(ValueError):self.install([package])
        self.assertFalse((self.root/'escape.py').exists())
