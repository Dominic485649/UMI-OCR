"""Name Windows GPU deliveries from their sealed runtime, never from the filename or GPU name."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re

_spec = importlib.util.spec_from_file_location('gpu_tier_layout', Path(__file__).with_name('runtime_archive_layout.py'))
layout = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(layout)

IDS = {'cuda': 'win32_PaddleOCRv6_CUDA', 'vl': 'win32_PaddleOCRVL_1_6'}
LABELS = {'cuda': 'CUDA', 'vl': 'PaddleVL'}
FIRST_SPLIT = {'cuda': (3, 0, 8), 'vl': (3, 1, 6)}
VERSIONS = {'12.6': 'cu126', '12.9': 'cu129'}


def read_bounded(path, limit):
    with layout.plain_path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f'GPU 档位记录超过预算：{path.name}')
    return raw, json.loads(raw.decode('utf-8-sig'), object_pairs_hook=layout._json_object)


def tier(root: Path, component: str, version: str) -> str | None:
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('GPU 插件版本无效')
    if tuple(map(int, version.split('.'))) < FIRST_SPLIT[component]:
        return None  # 历史版本沿用当次文件名，不给已有包改名或改证据。
    plugin = root / 'UmiOCR-data/plugins' / IDS[component]
    raw, support = read_bounded(plugin / 'cuda-support.json', 64 * 1024)
    actual = VERSIONS.get(support.get('cuda_version')) if isinstance(support, dict) else None
    if not actual or support.get('schema_version') != 1:
        raise ValueError('无法识别已审定的 CUDA 运行档位')
    _, frozen = read_bounded(plugin / 'runtime.lock.json', 8 * 1024**2)
    if not isinstance(frozen, dict) or frozen.get('pluginId') != IDS[component]:
        raise ValueError('GPU 运行锁组件身份不匹配')
    digest = hashlib.sha256(raw).hexdigest()
    lock_name = f'requirements-gpu-plugin-windows-{actual}.lock'
    if component == 'cuda':
        bound = (frozen.get('gpuSupportSha256') == digest and frozen.get('version') == version
                 and frozen.get('lock') == 'build/' + lock_name)
    else:
        matches = [row for row in frozen.get('files', []) if row.get('path') == 'cuda-support.json']
        bound = len(matches) == 1 and matches[0].get('sha256') == digest
    if not bound:
        raise ValueError('GPU 覆盖记录与已封存运行锁不匹配')
    return actual


def variant_suffix(value: str | None) -> str:
    return '_RTX50' if value == 'cu129' else ''


def runtime_archive_name(component, version, value, *, local_candidate=False):
    candidate_suffix = '-local-candidate' if local_candidate else ''
    return f'Umi-OCR-Plugin_v{version}{candidate_suffix}_Windows_x64_{LABELS[component]}{variant_suffix(value)}.tar.xz'


def source_archive_name(component, version, value):
    return f'Umi-OCR-Plugin_{component}_v{version}{variant_suffix(value)}_CorrespondingSource.tar.xz'
