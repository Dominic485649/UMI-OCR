"""离线预览 vendor 必须进入本体、对应源码与构建输入哈希，不放宽推理依赖边界。"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'build/tools'))
import source_snapshot as snapshot
import run_model_settings_build as builder


class PreviewBuildAssets(unittest.TestCase):
    def test_all_locked_browser_assets_are_selected_and_bound(self):
        selected = {path.as_posix() for path in snapshot.files_for_repo(ROOT, public=True)}
        hashes = builder.source_hashes('base')
        manifest = json.loads((ROOT / 'LICENSES/markdown-preview/manifest.json').read_text('utf-8'))
        count = 0
        for package in manifest['packages']:
            for relative, record in package['files'].items():
                name = 'UmiOCR-data/qt_res/preview/vendor/' + relative
                self.assertIn(name, selected)
                self.assertEqual(hashes[name], record['sha256'])
                self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), record['sha256'])
                count += 1
        self.assertGreater(count, 20)

    def test_only_browser_resource_vendor_is_allowed(self):
        for name in ('UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/vendor/paddle.py',
                     'UmiOCR-data/qt_res/preview/vendor/node_modules/private.js',
                     'UmiOCR-data/qt_res/preview/vendor/__pycache__/private.js',
                     'UmiOCR-data/qt_res/preview/vendor/private.py',
                     'docs/vendor/private.js'):
            self.assertTrue(snapshot.is_excluded(Path(name), public=True), name)

    def test_data_and_corresponding_source_mirrors_retain_exact_browser_bytes(self):
        work = ROOT / 'build/tmp/release-312-20261102-r1'
        inputs = {'UmiOCR-data/qt_res/preview/vendor/markdown-it.min.js': b'locked javascript',
                  'UmiOCR-data/qt_res/preview/vendor/katex.min.css': b'locked stylesheet',
                  'UmiOCR-data/qt_res/preview/vendor/fonts/KaTeX_Main-Regular.woff2': b'locked font'}
        with tempfile.TemporaryDirectory(prefix='preview-assets-', dir=work) as temporary:
            repo = Path(temporary)
            for name, content in inputs.items():
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            with patch.object(snapshot, 'relative_entries', return_value=[Path(name) for name in inputs]):
                snapshot.mirror_sources(repo, repo / 'build/data', data_only=True)
                snapshot.mirror_sources(repo, repo / 'build/source')
            for name, content in inputs.items():
                self.assertEqual((repo / 'build/data' / Path(name).relative_to('UmiOCR-data')).read_bytes(), content)
                self.assertEqual((repo / 'build/source' / name).read_bytes(), content)


if __name__ == '__main__':
    unittest.main(verbosity=2)
