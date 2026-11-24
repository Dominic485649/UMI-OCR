"""从本轮本地归档在全新目录重装组件，逐文件核对，不覆盖固定安装。"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
IDS = {"cuda": "win32_PaddleOCRv6_CUDA", "vl": "win32_PaddleOCRVL_1_6"}


def adjacent(name):
    spec = importlib.util.spec_from_file_location("review_install_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


layout = adjacent("runtime_archive_layout")
merge = adjacent("merge_runtime")


def binding(root):
    return {name: layout.sha256_file(path) for name, path in layout.tree_files(root).items()}


def safe_extract(archive_path, target, expected):
    """只接受清单中的普通文件/目录；解包目录独占且初始为空。"""
    target = layout.plain_path(target)
    if target.exists():
        raise FileExistsError("解包只允许全新目录：" + str(target))
    if not isinstance(expected, dict) or not expected:
        raise ValueError("缺少独立打包输入清单")
    for name, checksum in expected.items():
        layout.canonical_relative(name)
        if not isinstance(checksum, str) or len(checksum) != 64:
            raise ValueError("输入哈希清单无效")
    target.mkdir()
    seen, files, folded = set(), set(), set()
    total = 0
    with tarfile.open(archive_path, mode="r|xz") as archive:
        for member in archive:
            name = layout.canonical_relative(member.name.rstrip("/") if member.isdir() else member.name)
            if name.casefold() in folded or not (member.isdir() or member.isfile()):
                raise ValueError("归档包含重复、链接或特殊成员：" + name)
            folded.add(name.casefold())
            seen.add(name)
            if len(seen) > 100000 or member.size < 0:
                raise ValueError("归档成员超过有限预算")
            total += member.size
            if total > 20 * 1024**3:
                raise ValueError("单组件解包超过大小预算")
            path = target / name
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            if name not in expected:
                raise ValueError("归档多出未绑定文件：" + name)
            path.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("归档缺少文件字节：" + name)
            with stream, path.open("xb") as destination:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    destination.write(chunk)
                    digest.update(chunk)
            if digest.hexdigest() != expected[name]:
                raise ValueError("归档恢复内容与打包输入不符：" + name)
            files.add(name)
    if files != set(expected) or binding(target) != expected:
        raise ValueError("重装文件集合/哈希不匹配")
    return {"files": len(files), "logicalBytes": total, "payloadVerified": True}


def write_result(audit, report):
    """先完成并同步临时记录，磁盘失败时不留下可被误读的正式PASS文件。"""
    import os
    pending = audit / "result.incomplete.json"
    with pending.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    pending.rename(audit / "result.json")


def verify_install_capacity(records, target, reserve_bytes=1024**3):
    """本地审查归档要求保留输入；按目标卷簇大小估计，并额外预留1GiB。"""
    import ctypes
    import os
    import shutil
    cluster = 4096
    if os.name == "nt":
        values = [ctypes.c_uint32() for _ in range(4)]
        api = ctypes.WinDLL("kernel32", use_last_error=True).GetDiskFreeSpaceW
        api.argtypes = [ctypes.c_wchar_p] + [ctypes.POINTER(ctypes.c_uint32)] * 4
        api.restype = ctypes.c_int
        if not api(str(target.anchor), *(ctypes.byref(value) for value in values)):
            raise ctypes.WinError(ctypes.get_last_error())
        cluster = max(cluster, values[0].value * values[1].value)
    required = 0
    for component, (_record_path, record, _archive) in records.items():
        source = layout.plain_path(record["inputRoot"])
        allowed = [ROOT / "build"]
        if component == "vl":
            allowed.append(ROOT.parent / "Umi-OCR-Plugin/build")
        if not any(source.is_relative_to(boundary) for boundary in allowed):
            raise ValueError("容量输入不在所选组件的已授权项目 build 内")
        files = layout.tree_files(source)
        if set(files) != set(record["payload"]):
            raise ValueError("容量估计需要仍保留的完整打包输入，不采用未知或已改变目录")
        required += sum(((path.stat().st_size + cluster - 1) // cluster) * cluster for path in files.values())
    free = shutil.disk_usage(target.parent).free
    if free < required + reserve_bytes:
        raise OSError(28, "重装所需空间及额外1GiB余量不足；不创建安装或删除数据")
    return {"freeBytes": free, "clusterBytes": cluster, "payloadClusterUpperBytes": required,
            "reserveBytes": reserve_bytes, "limits": "按保留输入元数据估计，不保证其他进程不会同时消耗空间。"}


def installation_work_root(work_root=None):
    """每次重装使用显式具名任务根；缺省保持原调用的历史边界。"""
    selected = layout.plain_path(work_root or ROOT / "build/tmp/startup-small-files-20261028-r1")
    boundary = layout.plain_path(ROOT / "build/tmp")
    if selected.parent != boundary or not selected.is_dir():
        raise ValueError("重装工作根必须是本项目 build/tmp 下已存在的一级具名目录")
    return selected


def install(base_record, cuda_record, vl_record, target, audit, *, work_root=None):
    started = time.monotonic()
    target, audit = layout.plain_path(target), layout.plain_path(audit)
    boundary = installation_work_root(work_root)
    if target == boundary:
        raise ValueError("安装目标不能覆盖任务工作根本身")
    target.relative_to(boundary)
    audit.relative_to(ROOT / "build/audit")
    if target.exists() or audit.exists():
        raise FileExistsError("重装与审计须使用全新目录")
    records = {}
    for key, path in (("base", base_record), ("cuda", cuda_record), ("vl", vl_record)):
        path = layout.plain_path(path)
        record = layout.read_json(path)
        if (record.get("status") != "PASS" or record.get("purpose") != "local-nonfinal-review-artifact"
                or record.get("component") != key or not record.get("sourceUnchangedDuringPackaging")):
            raise ValueError("不是已核验的本轮本地候选归档记录")
        archive = layout.plain_path(record["archive"]["archive"])
        if layout.sha256_file(archive) != record["archive"]["sha256"]:
            raise ValueError("归档在打包后发生变化")
        records[key] = (path, record, archive)
    capacity = verify_install_capacity(records, target)
    extraction = {"base": target, "cuda": target.parent / (target.name + "-cuda-extract"),
                  "vl": target.parent / (target.name + "-vl-extract")}
    if any(path.exists() for path in extraction.values()):
        raise FileExistsError("每个归档都必须有自己的全新空解包目录")
    audit.mkdir()
    archive_inputs_verified = time.monotonic()
    report = {"status": "FAIL", "target": str(target), "components": {}, "moves": [],
              "capacityPreflight": capacity,
              "archiveInputVerificationSeconds": round(archive_inputs_verified - started, 3),
              "fixedInstallationChanged": False, "publicReleaseAuthorized": False}
    try:
        for key, (record_path, record, archive) in records.items():
            component_started = time.monotonic()
            outcome = safe_extract(archive, extraction[key], record["payload"])
            outcome["elapsedSeconds"] = round(time.monotonic() - component_started, 3)
            report["components"][key] = {"record": str(record_path), "recordSha256": layout.sha256_file(record_path),
                                        "archive": str(archive), "archiveSha256": record["archive"]["sha256"],
                                        "extractedTo": str(extraction[key]), **outcome}
        expected = dict(records["base"][1]["payload"])
        # 同卷重命名已从归档恢复且逐字节核过的组件，避免再复制两份多GB运行时。
        # 不移动历史证据；原解包位置和新位置单独记录，最终组合再次核验。
        for key, plugin_id in IDS.items():
            source = extraction[key]
            if merge.running_processes(source) or merge.running_processes(target):
                raise RuntimeError("新解包目录已有进程使用，停止装配，不终止进程")
            prefixes = ("UmiOCR-data/plugins/" + plugin_id, "LICENSES/plugins/" + plugin_id)
            payload = records[key][1]["payload"]
            if any(not any(name.startswith(prefix + "/") for prefix in prefixes) for name in payload):
                raise ValueError("插件归档含本体根元数据或未声明内容")
            for prefix in prefixes:
                original, destination = source / prefix, target / prefix
                if not original.is_dir() or destination.exists():
                    raise ValueError("组件目标缺失或冲突，禁止覆盖")
                destination.parent.mkdir(parents=True, exist_ok=True)
                original.rename(destination)
                report["moves"].append({"from": str(original), "to": str(destination), "contentCopied": False,
                                         "sourceArchiveExtractionVerified": True})
            if set(expected).intersection(payload):
                raise ValueError("组件之间出现文件冲突")
            expected.update(payload)
        actual = binding(target)
        if actual != expected:
            raise ValueError("最终组合与归档输入集合/字节不一致")
        report.update(status="PASS", files=len(actual), elapsedSeconds=round(time.monotonic() - started, 3),
                      finalPayload=actual,
                      scope="真实归档重装及组合字节核验，不代替运行验收；重命名路径的历史记录没有改写。")
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        write_result(audit, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-record", type=Path, required=True)
    parser.add_argument("--cuda-record", type=Path, required=True)
    parser.add_argument("--vl-record", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, help="本项目 build/tmp 下已存在的一级任务目录")
    args = parser.parse_args()
    report = install(args.base_record, args.cuda_record, args.vl_record, args.target, args.audit, work_root=args.work_root)
    print(json.dumps({key: value for key, value in report.items() if key not in {"finalPayload", "components", "moves"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
