"""冻结原生闭包，并把已审定 GPU 覆盖与精确核心字节绑定。"""

import argparse
import hashlib
import json
from pathlib import Path
import re


SUPPORT_NAME = "cuda-support.json"
CORE_PROVIDERS = {"vendor/paddle/base/libpaddle.pyd", "vendor/paddle/libs/phi.dll"}


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def apply_support(plugin, profile):
    """只接受与已审定核心哈希完全匹配的覆盖，不在运行时重扫 DLL。"""
    plugin, profile = Path(plugin), Path(profile)
    with profile.open("rb") as stream:
        raw = stream.read(64 * 1024 + 1)
    if len(raw) > 64 * 1024:
        raise ValueError("GPU 支持记录超过预算")
    record = json.loads(raw)
    providers = record.get("providers", [])
    if record.get("schema_version") != 1 or len(providers) != len(CORE_PROVIDERS):
        raise ValueError("GPU 支持记录格式不符")
    if {item.get("path") for item in providers} != CORE_PROVIDERS:
        raise ValueError("GPU 支持记录必须独立覆盖两个核心提供者")
    for item in providers:
        path = plugin.joinpath(*item["path"].split("/"))
        node = path
        while node != plugin:
            if node.is_symlink() or node.is_junction():
                raise ValueError(f"GPU 核心路径不允许链接：{node}")
            node = node.parent
        if not path.is_file() or digest(path) != item["sha256"]:
            raise ValueError(f"GPU 核心字节与覆盖记录不匹配：{item['path']}")
    target = plugin / SUPPORT_NAME
    if target.exists():
        if target.is_symlink() or target.read_bytes() != raw:
            raise ValueError("拒绝覆盖不同的 GPU 支持记录")
    else:
        with target.open("xb") as stream:
            stream.write(raw)
    return record


def generate(plugin, lock_reference="build/requirements-gpu-plugin-windows-cu126.lock", support_profile=None):
    plugin = Path(plugin)
    if support_profile is not None:
        apply_support(plugin, support_profile)
    manifest = json.loads((plugin / "umi-plugin.json").read_text(encoding="utf-8"))
    files = sorted(path for path in plugin.rglob("*") if path.is_file()
                   and path.name not in {"runtime.lock.json", "gpu-e2e-evidence.json"}
                   and "__pycache__" not in path.relative_to(plugin).parts)
    native = [{"path": path.relative_to(plugin).as_posix(), "sha256": digest(path)}
              for path in files if path.suffix.lower() in {".dll", ".pyd"}
              or path.relative_to(plugin).as_posix() == "UmiOCR-CudaWorker.exe"]
    record = {
        "pluginId": manifest["id"], "version": manifest["version"],
        "lock": str(lock_reference),
        "fileCount": len(files), "totalBytes": sum(path.stat().st_size for path in files),
        "nativeBinaryCount": len(native), "files": native,
        "count_excludes": ["runtime.lock.json", "gpu-e2e-evidence.json", "__pycache__"],
    }
    support = plugin / SUPPORT_NAME
    if support.is_file():
        record["gpuSupportSha256"] = digest(support)
    (plugin / "runtime.lock.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print("GPU native closure frozen:", len(native), "binaries; E2E evidence excluded from its inputs.")


def project_lock(old, binding, shared, development, projected, group, *, record_changes=None):
    """绑定投影后的私有文件和共享提供者；仅接受裁剪工具派生的具名 RECORD。"""
    runtime = {'runtime.lock.json', 'gpu-e2e-evidence.json'}
    native_suffixes = {'.dll', '.pyd', '.exe'}
    record_changes = record_changes or {}
    for name, (before, after) in record_changes.items():
        if (not re.fullmatch(r'vendor/[a-z0-9_.+!-]+\.dist-info/RECORD', name)
                or name in shared or name in development or not isinstance(before, bytes)
                or not isinstance(after, bytes) or before == after or projected.get(name) != after):
            raise ValueError('投影 RECORD 未绑定原始与派生字节：' + name)
    rows, external, seen = [], [], set()
    for item in old['files']:
        name = item['path']
        if name.casefold() in seen:
            raise ValueError('原生锁有重复成员：' + name)
        seen.add(name.casefold())
        native = Path(name).suffix.lower() in native_suffixes
        if name in development:
            if native:
                raise ValueError('开发裁剪误伤原生运行项：' + name)
            continue
        if name in shared:
            logical = name.removeprefix('vendor/')
            if native:
                if group['files'].get(logical, {}).get('sha256') != item['sha256']:
                    raise ValueError('外置提供者字节与插件原生锁不一致：' + name)
                external.append({**item, 'groupSha256': binding['groups'][0]['sha256'], 'member': logical})
            continue
        source = projected.get(name)
        if source is None and name in {'.runtime-archive-candidate.json', 'runtime-archive-inputs.json', 'gpu-e2e-evidence.json'}:
            continue  # 全文件锁中的开发审计副本随来源材料分发。
        if name in record_changes:
            before, after = record_changes[name]
            if hashlib.sha256(before).hexdigest() != item['sha256']:
                raise ValueError('原始 RECORD 字节与全文件锁不一致：' + name)
            rows.append({**item, 'sha256': hashlib.sha256(after).hexdigest()})
            continue
        if isinstance(source, bytes) and name in {'umi-plugin.json', 'runtime-archives.json', 'vendor.zip'}:
            rows.append({**item, 'sha256': hashlib.sha256(source).hexdigest()})
            continue
        if not isinstance(source, Path) or digest(source) != item['sha256']:
            raise ValueError('投影私有文件与原锁不一致：' + name)
        rows.append(item)
    kept = {item['path'] for item in rows}
    if not CORE_PROVIDERS <= kept:
        raise ValueError('私有 Paddle 核心或覆盖证明在投影中丢失')
    if 'nativeBinaryCount' not in old and not record_changes.keys() <= kept:
        raise ValueError('全文件锁缺少请求改写的原始 RECORD')
    files = [value for name, value in projected.items() if name not in runtime]
    return {**old, 'fileCount': len(files), 'totalBytes': sum(len(f) if isinstance(f, bytes) else f.stat().st_size for f in files),
            'nativeBinaryCount': sum(Path(name).suffix.lower() in native_suffixes for name in kept),
            'files': rows, 'sharedRuntime': binding, 'sharedNative': external}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("plugin", type=Path)
    parser.add_argument("--lock-reference", default="build/requirements-gpu-plugin-windows-cu126.lock")
    parser.add_argument("--support-profile", type=Path)
    parser.add_argument("--support-only", action="store_true")
    args = parser.parse_args()
    if args.support_only:
        if args.support_profile is None:
            parser.error("--support-only 必须指定 --support-profile")
        apply_support(args.plugin.resolve(), args.support_profile)
        print("GPU support record bound to the exact core binaries.")
    else:
        generate(args.plugin.resolve(), args.lock_reference, args.support_profile)
