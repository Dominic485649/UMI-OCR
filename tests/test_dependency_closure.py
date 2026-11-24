"""依赖闭包的marker、extra、共享文件和ZIP安全定向测试。"""
import argparse
import csv
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('tested_dependency_closure',ROOT/'build/tools/dependency_closure.py')
C=importlib.util.module_from_spec(spec);sys.modules[spec.name]=C;spec.loader.exec_module(C)
WORK=ROOT/'build/tmp/dependency-trim-20261114-r1/unit'

class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=WORK);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.site=self.root/'site';self.site.mkdir()
    def file(self,name,data=b'x'):
        p=self.site/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    def dist(self,name,requires=(),files=(),version='1.0'):
        info=name.replace('-','_')+'-'+version+'.dist-info'
        metadata='Metadata-Version: 2.1\nName: '+name+'\nVersion: '+version+'\n'
        metadata+=''.join('Requires-Dist: '+value+'\n' for value in requires)+'\n'
        self.file(info+'/METADATA',metadata.encode())
        records=io.StringIO();writer=csv.writer(records)
        for path in [*files,info+'/METADATA',info+'/RECORD']: writer.writerow([path,'',''])
        self.file(info+'/RECORD',records.getvalue().encode())
    def report(self,roots,archives=None): return C.report(C.FileIndex(self.site,archives),roots,C.target_environment())
    def test_target_python_marker_not_build_interpreter(self):
        self.dist('root',['old; python_version < "3.14"','new; python_version >= "3.14"','linux; sys_platform == "linux"'])
        self.dist('old');self.dist('new');self.dist('linux')
        report=self.report(['root'])
        self.assertEqual({r['name'] for r in report['selectedDistributions']},{'root','old'})
        self.assertEqual(report['issues'],[])
    def test_extras_are_evaluated_on_parent_and_propagated(self):
        self.dist('root',['base','ocr[image]; extra == "ocr-core"','training; extra == "training"'])
        self.dist('base');self.dist('ocr',['codec; extra == "image"']);self.dist('codec');self.dist('training')
        report=self.report(['root[ocr-core]'])
        self.assertEqual({r['name'] for r in report['selectedDistributions']},{'root','base','ocr','codec'})
    def test_multiple_roots_union_new_extras(self):
        self.dist('root',['a; extra == "a"','b; extra == "b"']);self.dist('a');self.dist('b')
        report=self.report(['root[a]','root[b]'])
        self.assertEqual({r['name'] for r in report['selectedDistributions']},{'root','a','b'})
    def test_shared_namespace_file_counted_once_and_never_orphaned(self):
        self.file('namespace/shared.py',b'shared');self.file('namespace/unused.py',b'unused')
        self.dist('needed',files=['namespace/shared.py']);self.dist('orphan',files=['namespace/shared.py','namespace/unused.py'])
        report=self.report(['needed'])
        self.assertNotIn('namespace/shared.py',report['metadataCandidateFiles'])
        self.assertIn('namespace/unused.py',report['metadataCandidateFiles'])
        selected=[C.FileIndex(self.site).files[p] for p in C.FileIndex(self.site).files if p.startswith('needed-') or p=='namespace/shared.py']
        self.assertEqual(report['selectedLogicalBytes'],sum(entry.bytes for entry in selected))
    def test_zip_member_present_in_record_not_reported_missing(self):
        self.dist('bottle',files=['bottle.py'])
        archive=self.root/'dependencies.zip'
        with zipfile.ZipFile(archive,'x') as out: out.writestr('bottle.py',b'zip-imported')
        report=self.report(['bottle'],[archive])
        self.assertEqual(report['selectedDistributions'][0]['missingRecordFiles'],0)
        self.assertEqual(report['issues'],[])
    def test_zip_and_disk_alias_rejected(self):
        self.file('bottle.py')
        archive=self.root/'dependencies.zip'
        with zipfile.ZipFile(archive,'x') as out: out.writestr('bottle.py',b'other')
        with self.assertRaisesRegex(ValueError,'重复'): C.FileIndex(self.site,[archive])
    def test_zip_case_alias_and_traversal_rejected(self):
        for index,names in enumerate([['../escape.py'],['Package/file.py','package/file.py']]):
            archive=self.root/('bad'+str(index)+'.zip')
            with zipfile.ZipFile(archive,'x') as out:
                for name in names: out.writestr(name,b'x')
            with self.assertRaises(ValueError): C.FileIndex(self.site,[archive])
    def test_quoted_record_filename(self):
        self.file('pkg/a,b.py',b'quoted');self.dist('root',files=['pkg/a,b.py'])
        report=self.report(['root'])
        self.assertEqual(report['selectedDistributions'][0]['missingRecordFiles'],0)
    def test_outside_record_entry_is_not_followed(self):
        self.dist('root',files=['../Scripts/tool.exe'])
        report=self.report(['root'])
        self.assertEqual(report['selectedDistributions'][0]['outsideRecordFiles'],1)
    def test_nested_vendored_metadata_is_not_an_installed_distribution(self):
        self.dist('packaging',version='1.0')
        nested='bootstrap/_vendor/packaging-99.dist-info/METADATA'
        self.file(nested,b'Name: packaging\nVersion: 99\n\n')
        self.dist('bootstrap',files=[nested])
        report=self.report(['packaging','bootstrap'])
        self.assertEqual({r['name']:r['version'] for r in report['selectedDistributions']},{'packaging':'1.0','bootstrap':'1.0'})
    def test_missing_and_version_mismatch_are_visible(self):
        self.dist('root',['absent','old>=2']);self.dist('old',version='1.0')
        types={r['type'] for r in self.report(['root'])['issues']}
        self.assertEqual(types,{'missing-distribution','version-mismatch'})
    def test_unowned_files_not_automatic_delete_candidates(self):
        self.file('runtime-special.dll');self.dist('root')
        report=self.report(['root'])
        self.assertIn('runtime-special.dll',report['unownedFiles'])
        self.assertNotIn('runtime-special.dll',report['metadataCandidateFiles'])

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--work',type=Path,default=WORK);args,other=parser.parse_known_args()
    WORK=args.work.absolute();WORK.relative_to(ROOT/'build');WORK.mkdir(parents=True,exist_ok=True)
    unittest.main(argv=[sys.argv[0],*other])
