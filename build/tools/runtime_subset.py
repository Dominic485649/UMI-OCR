"""在全新目录构造明确标识的原生模块子集；原始发行版与RECORD保持不改。"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil


def plain(path: Path) -> Path:
    path = path.absolute()
    for node in (path, *path.parents):
        if node.is_symlink() or node.is_junction():
            raise ValueError('子集输入/输出拒绝链接：' + str(node))
    return path


def sha(path: Path) -> str:
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def native_module_subset(source: Path, destination: Path, keep_extensions: set[str]) -> dict:
    """只选显式扩展；非原生辅助文件全部保留，不据目录名猜测其运行用途。"""
    source, destination = plain(source), plain(destination)
    if not source.is_dir() or destination.exists():
        raise ValueError('输入必须存在，输出必须是全新目录')
    if not keep_extensions or any(not name or '/' in name or '\\' in name or '.' in name for name in keep_extensions):
        raise ValueError('必须显式列出不含路径和ABI后缀的模块名')
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('子集输入输出不能互相嵌套')
    files, found = {}, set()
    # 输入先完整验证，再创建输出，避免在链接或缺失模块上留下貌似有效的子集。
    import os
    for directory, dirs, names in os.walk(source, followlinks=False):
        for name in dirs:
            plain(Path(directory) / name)
        for name in names:
            path = plain(Path(directory) / name)
            if not path.is_file():
                raise ValueError('输入包含非普通文件')
            relative = path.relative_to(source).as_posix()
            if path.suffix.lower() == '.pyd':
                module = path.name.split('.', 1)[0]
                selected = module in keep_extensions
                if selected:
                    if module in found:
                        raise ValueError('同一模块存在多个原生构件，拒绝隐式选择：' + module)
                    found.add(module)
            else:
                selected = True
            files[relative] = {'bytes': path.stat().st_size, 'sha256': sha(path), 'selected': selected}
            if len(files) > 100000:
                raise ValueError('子集输入文件数超出预算')
    if found != keep_extensions:
        raise ValueError('要求保留的扩展缺失：' + ', '.join(sorted(keep_extensions - found)))
    destination.mkdir(parents=True, exist_ok=False)
    for relative, record in files.items():
        if not record['selected']:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
        if sha(target) != record['sha256']:
            raise ValueError('子集复制内容不符：' + relative)
    return {
        'status': 'PROJECTED_NOT_RUNTIME_ACCEPTED',
        'createdUtc': datetime.now(timezone.utc).isoformat(),
        'source': str(source), 'destination': str(destination),
        'keepExtensions': sorted(keep_extensions), 'files': files,
        'inputBytes': sum(row['bytes'] for row in files.values()),
        'outputBytes': sum(row['bytes'] for row in files.values() if row['selected']),
        'omittedBytes': sum(row['bytes'] for row in files.values() if not row['selected']),
        'officialDistributionUnmodified': True,
        'boundary': '明确的运行子集，不是官方完整wheel；还须原生依赖、实际格式和消费者验收。',
    }


def write_receipt(path: Path, record: dict) -> None:
    path = plain(path)
    with path.open('x', encoding='utf-8') as output:
        json.dump(record, output, ensure_ascii=False, indent=2)
        output.write('\n')
