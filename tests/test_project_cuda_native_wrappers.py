"""CUDA包装器派生身份、核心保留、共享归属与重复投影定向测试。"""
import base64
import copy
import csv
import importlib.util
import io
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('tested_cuda_wrapper_projection',ROOT/'build/tools/project_cuda_native_wrappers.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)


def record(payload,dist):
    stream=io.StringIO(newline='');writer=csv.writer(stream,lineterminator='\n')
    for name,data in sorted(payload.items()):
        writer.writerow([name,'sha256='+base64.urlsafe_b64encode(bytes.fromhex(M.digest(data))).rstrip(b'=').decode(),str(len(data))])
    writer.writerow([dist+'/RECORD','',''])
    return stream.getvalue().encode()


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.rules=copy.deepcopy(json.loads((ROOT/'build/runtime-subsets-windows.json').read_text('utf-8'))['cudaNativeWrappers'])
        self.data={}
        for rule in self.rules:
            dist=rule['dist']
            metadata=('Name: '+rule['distribution']+'\nVersion: '+rule['version']+'\nLicense: NVIDIA\n\nfixture\n').encode()
            payload={name:name.encode() for name in rule['requiredFiles']}
            payload.update({'nvidia/__init__.py':b'',rule['package']+'/__init__.py':b'',rule['path']:b'optional wrapper',
                            dist+'/METADATA':metadata,dist+'/License.txt':b'Original NVIDIA license',dist+'/WHEEL':b'wheel fixture'})
            raw=record(payload,dist)
            rule.update(originalRecord=raw.decode(),recordSha256=M.digest(raw),originalMetadata=metadata.decode(),
                        metadataSha256=M.digest(metadata),sha256=M.digest(payload[rule['path']]),bytes=len(payload[rule['path']]))
            payload[dist+'/RECORD']=raw
            self.data.update(payload)

    def run_projection(self):
        self.inspected={}
        def bounded(view,name,limit):
            data=self.data[name.removeprefix('vendor/')]
            if len(data)>limit:raise ValueError('budget')
            return data
        return M.projection(None,set(self.data),'vendor',self.rules,self.inspected,bounded)

    def test_removes_only_optional_wrappers_and_updates_records(self):
        before=dict(self.data)
        additions,omitted,decisions=self.run_projection()
        output={**{n:d for n,d in self.data.items() if n not in omitted},**additions}
        self.assertEqual(before,self.data)
        for rule in self.rules:
            self.assertNotIn(rule['path'],output)
            for name in rule['requiredFiles']:
                self.assertEqual(output[name],before[name])
                self.assertEqual(self.inspected[name],M.digest(before[name]))
            dist=rule['dist'].removesuffix('.dist-info')+'+umi.runtime.1.dist-info'
            self.assertEqual(output[dist+'/License.txt'],b'Original NVIDIA license')
            for name,checksum,size in csv.reader(io.StringIO(output[dist+'/RECORD'].decode())):
                if name.endswith('/RECORD'):
                    self.assertFalse(checksum or size)
                else:
                    self.assertEqual(int(size),len(output[name]))
                    self.assertEqual(checksum,'sha256='+base64.urlsafe_b64encode(bytes.fromhex(M.digest(output[name]))).rstrip(b'=').decode())
        self.assertEqual(len(decisions),2)
        self.assertIn('nvidia/__init__.py',output)

    def test_pep639_license_path_is_preserved(self):
        for rule in self.rules:
            dist = rule['dist']
            license_data = self.data.pop(dist + '/License.txt')
            self.data[dist + '/licenses/License.txt'] = license_data
            owned = {name: data for name, data in self.data.items()
                     if name != dist + '/RECORD' and (name.startswith((rule['package'] + '/', dist + '/')) or name == 'nvidia/__init__.py')}
            raw = record(owned, dist)
            self.data[dist + '/RECORD'] = raw
            rule.update(originalRecord=raw.decode(), recordSha256=M.digest(raw))
        additions, _, _ = self.run_projection()
        for rule in self.rules:
            derived = rule['dist'].removesuffix('.dist-info') + '+umi.runtime.1.dist-info'
            self.assertEqual(additions[derived + '/licenses/License.txt'], b'Original NVIDIA license')

    def test_shared_namespace_is_not_claimed_by_a_nonowner(self):
        rule = self.rules[0]
        dist = rule['dist']
        owned = {name: data for name, data in self.data.items()
                 if name != dist + '/RECORD' and name.startswith((rule['package'] + '/', dist + '/'))}
        raw = record(owned, dist)
        self.data[dist + '/RECORD'] = raw
        rule.update(originalRecord=raw.decode(), recordSha256=M.digest(raw))
        additions, omitted, _ = self.run_projection()
        derived = dist.removesuffix('.dist-info') + '+umi.runtime.1.dist-info'
        self.assertNotIn('nvidia/__init__.py', omitted)
        self.assertNotIn('nvidia/__init__.py', additions[derived + '/RECORD'].decode())
        self.data = {**{n: d for n, d in self.data.items() if n not in omitted}, **additions}
        before = dict(self.data)
        additions, omitted, _ = self.run_projection()
        self.assertEqual(before, {**{n: d for n, d in self.data.items() if n not in omitted}, **additions})
        self.assertEqual(self.data['nvidia/__init__.py'], b'')

    def test_derived_seed_is_exactly_idempotent(self):
        additions,omitted,_=self.run_projection()
        self.data={**{n:d for n,d in self.data.items() if n not in omitted},**additions}
        before=dict(self.data)
        additions,omitted,decisions=self.run_projection()
        self.assertEqual(before,{**{n:d for n,d in self.data.items() if n not in omitted},**additions})
        self.assertTrue(all(item['excludedBytes']==0 for item in decisions))

    def test_shared_wrapper_owner_is_rejected(self):
        self.data['other-1.dist-info/RECORD']=(self.rules[0]['path']+',,\n').encode()
        with self.assertRaisesRegex(ValueError,'共享归属'):
            self.run_projection()

    def test_unknown_wrapper_bytes_are_rejected(self):
        self.data[self.rules[0]['path']]=b'changed'
        with self.assertRaisesRegex(ValueError,'包装器字节'):
            self.run_projection()

    def test_missing_core_or_license_is_rejected(self):
        for name in (self.rules[0]['requiredFiles'][0],self.rules[0]['dist']+'/License.txt'):
            with self.subTest(name=name):
                data=self.data.pop(name)
                with self.assertRaisesRegex(ValueError,'核心DLL或许可'):
                    self.run_projection()
                self.data[name]=data

    def test_original_record_identity_is_required(self):
        self.data[self.rules[0]['dist']+'/RECORD']+=b'new,,\n'
        with self.assertRaisesRegex(ValueError,'RECORD不符'):
            self.run_projection()

    def test_profile_source_hash_is_required(self):
        self.rules[0]['recordSha256']='0'*64
        with self.assertRaisesRegex(ValueError,'归属锁'):
            self.run_projection()

    def test_unrecorded_member_is_rejected(self):
        self.data[self.rules[0]['package']+'/extra.dll']=b'new'
        with self.assertRaisesRegex(ValueError,'未知成员'):
            self.run_projection()

    def test_unmarked_or_tampered_derived_seed_is_rejected(self):
        additions,omitted,_=self.run_projection()
        self.data={**{n:d for n,d in self.data.items() if n not in omitted},**additions}
        marker=next(n for n in self.data if n.endswith('/UMI_RUNTIME_SUBSET.json'))
        self.data[marker]=b'{}'
        with self.assertRaisesRegex(ValueError,'派生标识'):
            self.run_projection()

    def test_changed_core_is_bound_for_copy_time_rejection(self):
        path=self.rules[0]['requiredFiles'][0]
        self.data[path]=b'changed core DLL'
        self.run_projection()
        self.assertNotEqual(self.inspected[path],M.digest(self.data[path]))

    def test_missing_wrapper_cannot_claim_upstream_identity(self):
        self.data.pop(self.rules[0]['path'])
        with self.assertRaisesRegex(ValueError,'完整原版身份'):
            self.run_projection()


if __name__=='__main__':unittest.main()
