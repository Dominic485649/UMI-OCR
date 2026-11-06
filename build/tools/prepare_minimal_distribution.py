"""从完整组件生成最简运行树；源码/审计留在外置材料根，逐项绑定，不改原件。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil


def adjacent(name):
    spec = importlib.util.spec_from_file_location("minimal_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


layout = adjacent("runtime_archive_layout")
packaging = adjacent("package_tar_xz")
merge = adjacent("merge_runtime")
FORMAT = "umi-minimal-distribution-v1"
ROOT = Path(__file__).resolve().parents[2]
IDS = {"cuda": "win32_PaddleOCRv6_CUDA", "vl": "win32_PaddleOCRVL_1_6"}
ROOT_RECORDS = {"COPYING", "LICENSE", "NOTICE.md", "SOURCE-CODE.md", "VERSION", "source-export.json",
                "source-snapshot.zip", "source-snapshot.json", "source-provenance.json", "PUBLIC_DELIVERY.json"}
RUNTIME_AUDITS = {"runtime-archive-inputs.json", ".runtime-archive-candidate.json", "gpu-e2e-evidence.json"}
LEGAL_NAMES = {"COPYING", "LICENSE", "NOTICE.md", "GPL-3.0.txt", "LGPL-2.1.txt", "LGPL-3.0.txt",
               "PyMuPDF-AGPL-3.0.txt", "THIRD_PARTY_COMPONENTS.md", "THIRD_PARTY_NOTICES.md", "VL_EXTRA_THIRD_PARTY_NOTICES.md"}


def payload(root):
    return {name: layout.sha256_file(path) for name, path in layout.tree_files(root).items()}


def work_path(path, component):
    path = layout.plain_path(path)
    allowed = [ROOT / "build"]
    if component == "vl":
        allowed.append(ROOT.parent / "Umi-OCR-Plugin/build")
    if not any(path.is_relative_to(boundary) and path != boundary for boundary in allowed):
        raise ValueError("分包工作路径必须留在本组件授权项目的 build 内")
    return path


def identity(root, component):
    if component == "base":
        metadata = root
        record = layout.read_json(root / "UmiOCR-data/about.json")
        value = record["version"]
        version = ".".join(str(value[key]) for key in ("major", "minor", "patch")) if isinstance(value, dict) else value
        plugin = None
        if not (root / "Umi-OCR.exe").is_file() or (root / "UmiOCR-data/plugins").exists():
            raise ValueError("纯本体须含启动器且不能包含推理插件目录")
    else:
        plugin = IDS[component]
        record = layout.read_json(root / "UmiOCR-data/plugins" / plugin / "umi-plugin.json")
        if record["id"] != plugin:
            raise ValueError("插件身份不匹配")
        version = record["version"]
        nested = root / "LICENSES/plugins" / plugin
        metadata = nested if nested.is_dir() else root
    if not (metadata / "COPYING").is_file() or not (metadata / "LICENSE").is_file():
        raise ValueError("完整输入缺少原始许可")
    if not any((metadata / name).is_dir() for name in ("source", "source-records")):
        raise ValueError("必须提供完整源码/审计输入，不从已经剥离的运行包猜测来源")
    return metadata, str(version), plugin


def classifications(root, component):
    metadata, version, plugin = identity(root, component)
    entries = layout.tree_files(root)
    runtime, external = {}, {}
    for name, path in entries.items():
        parts = Path(name).parts
        if parts[0] == "UmiOCR-data":
            if component != "base" and not name.startswith("UmiOCR-data/plugins/" + plugin + "/"):
                raise ValueError("插件输入包含其它组件运行载荷：" + name)
            if path.name in RUNTIME_AUDITS:
                external[name] = "runtime-audit"
            elif path.name == "Umi-OCR-UIUnlock.dll" or any(part in {".settings", ".pre_settings", ".plugins_state", "__pycache__", "logs", "temp_doc", ".download"} for part in parts):
                raise ValueError("输入混有用户状态/私有文件：" + name)
            else:
                runtime[name] = path
        elif component == "base" and name == "Umi-OCR.exe":
            runtime[name] = path
        elif parts[0] in {"LICENSES", "source", "source-records"} or name in ROOT_RECORDS:
            external[name] = "corresponding-source-or-evidence"
        else:
            raise ValueError("未知组件根文件，不静默丢弃：" + name)
    if not runtime:
        raise ValueError("运行载荷为空")
    return metadata, version, plugin, entries, runtime, external


def legal_files(metadata):
    result = {}
    for name in LEGAL_NAMES:
        path = metadata / name
        if path.is_file():
            result[name] = path
    licenses = metadata / "LICENSES"
    if licenses.is_dir():
        for name, path in layout.tree_files(licenses).items():
            if name.startswith("plugins/") or path.name == "RELEASE_EVIDENCE.md":
                continue
            license_name = not path.suffix and path.name.upper().startswith(("LICENSE", "COPYING", "NOTICE", "COPYRIGHT", "AUTHORS", "PATENTS"))
            if license_name or path.suffix.lower() in {".txt", ".md", ".html"} or path.name == "model-rights.json" or "third-party-notices" in path.name.lower():
                result["LICENSES/" + name] = path
            elif path.suffix.lower() not in {".json", ".zip", ".gz", ".xz", ".tgz"}:
                raise ValueError("未知许可材料类型，须人工分类：" + name)
    return result


def external_metadata(original, supplied, component, version):
    if component != "vl":
        raise ValueError("只有独立 PaddleVL 流程接受外置完整材料根")
    supplied = work_path(supplied, component)
    if not supplied.is_dir() or not (supplied / "source").is_dir():
        raise ValueError("外置材料缺少完整对应源码根")
    if (supplied / "VERSION").read_text("utf-8-sig").strip() != version:
        raise ValueError("外置材料组件版本不匹配")
    for name in ("COPYING", "LICENSE"):
        if layout.sha256_file(supplied / name) != layout.sha256_file(original / name):
            raise ValueError("外置材料不能替换组件原始许可")
    return supplied, payload(supplied)


def prepare(root, output, component, report, *, source_url=None, metadata_root=None):
    root, output, report = (work_path(path, component) for path in (root, output, report))
    if output.exists() or report.exists() or not output.parent.is_dir() or not report.parent.is_dir():
        raise ValueError("运行暂存/清单必须是已有父目录中的新路径")
    if output.is_relative_to(root) or root.is_relative_to(output) or report.is_relative_to(root) or report.is_relative_to(output):
        raise ValueError("输入、运行暂存与外置清单必须分离")
    if merge.running_processes(root):
        raise ValueError("完整输入正在运行，不改变其来源边界")
    metadata, version, plugin, entries, runtime, external = classifications(root, component)
    metadata_payload = None
    if metadata_root is not None:
        metadata, metadata_payload = external_metadata(metadata, metadata_root, component, version)
        if any(metadata == other or metadata in other.parents or other in metadata.parents for other in (root, output, report)):
            raise ValueError("外置材料必须与完整输入、运行树和清单分离")
        if merge.running_processes(metadata):
            raise ValueError("外置材料正在被运行")
    before = {name: layout.sha256_file(path) for name, path in entries.items()}
    legal = legal_files(metadata)
    output.mkdir()
    copied = {}
    for name, path in runtime.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied[name] = before[name]
    # 最小许可仅保留一份；第三方运行包自带许可保持原位和原字节。
    prefix = Path() if component == "base" else Path("UmiOCR-data/plugins") / plugin
    for name in ("COPYING", "LICENSE"):
        target = output / prefix / name
        if target.exists() and layout.sha256_file(target) != layout.sha256_file(metadata / name):
            raise ValueError("插件运行根存在冲突的许可证：" + name)
        if not target.exists():
            shutil.copy2(metadata / name, target)
        copied[target.relative_to(output).as_posix()] = layout.sha256_file(target)
    notice_sections, archive_notices = [], {}
    seen = {layout.sha256_file(metadata / name) for name in ("COPYING", "LICENSE")}
    for name, path in sorted(legal.items()):
        checksum = layout.sha256_file(path)
        if checksum in seen:
            continue
        seen.add(checksum)
        if path.suffix.lower() == ".zip":
            target = output / prefix / "notices" / Path(name).name
            if target.exists():
                raise ValueError("第三方声明文件名冲突")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            archive_notices[name] = target.relative_to(output).as_posix()
            copied[target.relative_to(output).as_posix()] = checksum
        else:
            notice_sections.append("\n\n===== " + name + " =====\n\n" + path.read_text("utf-8-sig"))
    notice = output / prefix / "THIRD_PARTY_NOTICES.txt"
    if notice.exists():
        raise ValueError("运行根已有同名第三方声明，不覆盖")
    notice.write_text("第三方许可与版权声明（相同原文已去重，原组件许可分别适用）。\n" + "".join(notice_sections), encoding="utf-8")
    copied[notice.relative_to(output).as_posix()] = layout.sha256_file(notice)
    source_record = output / prefix / "SOURCE.txt"
    if source_record.exists():
        raise ValueError("运行根已有源码指引，不覆盖")
    source_name = f"Umi-OCR{'-Plugin' if plugin else ''}_{component}_v{version}_CorrespondingSource.tar.xz"
    source_record.write_text(f"组件：{component} {version}\n此为最简运行包，完整对应源码独立提供。\n"
        f"对应源码：{source_name}\n从取得本运行包的同一交付位置免费取得相同版本的独立对应源码包。\n"
        + (f"公开源码位置：{source_url}\n" if source_url else "本地候选尚未公开发布；正式分发前必须提供有效的对应源码位置。\n")
        + "AGPL 覆盖内容的复制、修改与再分发权利不受收费或分包方式限制。\n", encoding="utf-8")
    copied[source_record.relative_to(output).as_posix()] = layout.sha256_file(source_record)
    actual = payload(output)
    if actual != copied or payload(root) != before:
        raise ValueError("分包过程中输入或运行副本发生变化")
    record = {"format": FORMAT, "component": component, "version": version, "status": "PASS",
        "scope": "MINIMAL_LAYOUT_AND_SOURCE_BINDING_ONLY", "publicReleaseAuthorized": False,
        "createdUtc": datetime.now(timezone.utc).isoformat(), "completeRoot": str(root), "metadataRoot": str(metadata),
        "runtimeRoot": str(output), "completePayload": before, "runtimePayload": actual,
        "unchangedRuntime": {name: before[name] for name in runtime}, "externalFiles": external,
        "legalInputs": {name: layout.sha256_file(path) for name, path in legal.items()}, "archivedNotices": archive_notices,
        "correspondingSourceArchiveName": source_name, "sourceUrl": source_url,
        "inputBytes": sum(path.stat().st_size for path in entries.values()),
        "runtimeBytes": sum(path.stat().st_size for path in layout.tree_files(output).values()),
        "driverSha256": layout.sha256_file(__file__)}
    if metadata_payload is not None:
        if payload(metadata) != metadata_payload:
            raise ValueError("分包过程中外置完整材料发生变化")
        record["externalMetadataPayload"] = metadata_payload
    with report.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return record


def verify(report, *, mutable=()):
    """同时核对实际最简包和外置源码材料；本函数不授予公开发布权限。"""
    record = layout.read_json(layout.plain_path(report))
    if record.get("format") != FORMAT or record.get("status") != "PASS":
        raise ValueError("不是本工具生成的有效分包清单")
    root, output = (work_path(path, record["component"]) for path in (record["completeRoot"], record["runtimeRoot"]))
    actual_complete = payload(root)
    before = record["completePayload"]
    if (set(actual_complete) - set(mutable) != set(before) - set(mutable)
            or any(actual_complete.get(name) != checksum for name, checksum in before.items() if name not in mutable)
            or payload(output) != record["runtimePayload"]):
        raise ValueError("最简载荷或外置材料与清单不匹配")
    original_metadata, version, _, _, runtime, _ = classifications(root, record["component"])
    if "externalMetadataPayload" in record:
        _, actual_metadata = external_metadata(original_metadata, record["metadataRoot"], record["component"], version)
        if actual_metadata != record["externalMetadataPayload"]:
            raise ValueError("外置对应源码或许可材料与分包清单不匹配")
    elif Path(record["metadataRoot"]) != original_metadata:
        raise ValueError("完整输入不能指向未绑定的其它材料根")
    expected = {name: record["completePayload"][name] for name in runtime}
    if expected != record["unchangedRuntime"] or any(record["runtimePayload"].get(name) != checksum for name, checksum in expected.items()):
        raise ValueError("最简包改变或遗漏了运行文件")
    return record


def package(record_path, output, source_output, *, formal=False):
    record = verify(record_path)
    output, source_output = (work_path(path, record["component"]) for path in (output, source_output))
    if output.exists() or source_output.exists():
        raise FileExistsError("不覆盖既有运行/源码归档")
    if not output.parent.is_dir() or not source_output.parent.is_dir():
        raise ValueError("归档父目录必须存在")
    # 公共正式路径须由 finalizer 的门禁调用；本地 CLI 不接受 formal 绕过参数。
    if formal and not record.get("sourceUrl"):
        raise ValueError("正式运行包必须声明明确对应源码下载位置")
    metadata = layout.plain_path(record["metadataRoot"])
    fast = adjacent("package_local_review_fast")
    source = fast.create_fast_archive(metadata, source_output) if metadata != Path(record["completeRoot"]) else None
    if source is None:
        # 独立材料只封装非运行顶层，不能把程序再打进源码包。
        source_stage = source_output.parent / (source_output.name + ".materials")
        if source_stage.exists():
            raise FileExistsError(source_stage)
        source_stage.mkdir()
        for child in metadata.iterdir():
            if child.name in {"UmiOCR-data", "Umi-OCR.exe"}:
                continue
            if child.is_dir():
                shutil.copytree(child, source_stage / child.name)
            else:
                shutil.copy2(child, source_stage / child.name)
        source = fast.create_fast_archive(source_stage, source_output)
    result = fast.create_fast_archive(Path(record["runtimeRoot"]), output)
    verify(record_path)
    return {"status": "PASS", "formalRelease": formal, "publicReleaseAuthorized": False,
            "component": record["component"], "version": record["version"], "archive": result,
            "correspondingSource": source, "distributionRecord": str(Path(record_path).absolute()),
            "distributionRecordSha256": layout.sha256_file(record_path),
            "inputBytes": record["inputBytes"], "runtimeBytes": record["runtimeBytes"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify", "package"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--component", choices=tuple(["base", *IDS]))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-url")
    parser.add_argument("--metadata-root", type=Path, help="PaddleVL 独立来源/许可材料根，必须逐文件绑定")
    parser.add_argument("--source-output", type=Path)
    parser.add_argument("--package-record", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        if not args.root or not args.output or not args.component:
            parser.error("prepare 需要 root、output 和 component")
        result = prepare(args.root, args.output, args.component, args.report, source_url=args.source_url,
                         metadata_root=args.metadata_root)
        print(json.dumps({key: result[key] for key in ("status", "component", "version", "inputBytes", "runtimeBytes", "runtimeRoot")}, ensure_ascii=False))
    elif args.command == "verify":
        result = verify(args.report)
        print(json.dumps({"status": "PASS", "runtimeFiles": len(result["runtimePayload"]), "completeFiles": len(result["completePayload"])}, ensure_ascii=False))
    else:
        if not args.output or not args.source_output or not args.package_record:
            parser.error("package 需要 output、source-output 和 package-record")
        record = layout.plain_path(args.package_record)
        if record.exists():
            raise FileExistsError(record)
        result = package(args.report, args.output, args.source_output)
        with record.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps({key: value for key, value in result.items() if key != "archive"} | {"archiveBytes": result["archive"]["bytes"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
