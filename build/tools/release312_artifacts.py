"""本轮本地归档：插件留在授权插件项目构建，组件逐字节绑定，不公开发布。"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import time

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_PROJECT = ROOT.parent / "Umi-OCR-Plugin"
PLUGIN_ID = "win32_PaddleOCRVL_1_6"


def load(name):
    spec = importlib.util.spec_from_file_location("release312_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


review = load("package_local_review")
fast = load("package_local_review_fast")
vl = load("prepare_vl_overlay")


def new_path(path, boundary):
    path = review.layout.plain_path(path)
    path.relative_to(boundary)
    if path.exists():
        raise FileExistsError(path)
    if not path.parent.is_dir():
        raise ValueError("父目录须先建立并核对：" + str(path.parent))
    return path


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def overlay(args):
    stage = review.layout.plain_path(args.root)
    stage.relative_to(PLUGIN_PROJECT / "build")
    output = new_path(args.output, PLUGIN_PROJECT / "build")
    audit = new_path(args.audit, PLUGIN_PROJECT / "build/audit")
    if output.is_relative_to(stage) or stage.is_relative_to(output):
        raise ValueError("覆盖层必须与原构建树分离")
    if review.merge.running_processes(stage):
        raise RuntimeError("构建输入仍有运行进程；不终止进程")
    stage, plugin, source, licenses, manifest = vl.identity(stage)
    if manifest["version"] != "3.1.2":
        raise ValueError("不是本轮 PaddleVL 3.1.2 输入")
    before = review.payload(stage)
    target = output / "UmiOCR-data/plugins" / PLUGIN_ID
    target.parent.mkdir(parents=True)
    shutil.copytree(plugin, target)
    metadata = output / "LICENSES/plugins" / PLUGIN_ID
    metadata.parent.mkdir(parents=True)
    shutil.copytree(licenses, metadata)
    shutil.copytree(source, metadata / "source-records")
    expected = {}
    for name, checksum in before.items():
        if name.startswith("UmiOCR-data/"):
            expected[name] = checksum
        elif name.startswith("source/"):
            expected["LICENSES/plugins/" + PLUGIN_ID + "/source-records/" + name[7:]] = checksum
        elif name.startswith("LICENSES/"):
            expected["LICENSES/plugins/" + PLUGIN_ID + "/" + name[9:]] = checksum
        elif name in {"COPYING", "LICENSE", "NOTICE.md", "SOURCE-CODE.md"}:
            # 原始根记录也保留，不依赖 source 中是否已有同名副本。
            destination = metadata / name
            if destination.exists():
                if review.layout.sha256_file(destination) != checksum:
                    raise ValueError("根记录与许可目标冲突，不覆盖：" + name)
            else:
                shutil.copy2(stage / name, destination)
            expected["LICENSES/plugins/" + PLUGIN_ID + "/" + name] = checksum
        else:
            raise ValueError("未知构建根文件，不丢弃：" + name)
    if review.payload(stage) != before or review.payload(output) != expected:
        raise ValueError("覆盖层或原构建输入字节发生变化")
    save(audit, {"status": "PASS", "input": str(stage), "output": str(output), "version": manifest["version"],
        "sourceUnchanged": True, "files": len(expected), "payload": expected,
        "driverSha256": review.layout.sha256_file(__file__), "publicReleaseAuthorized": False,
        "scope": "授权插件项目内的新覆盖层；全部运行载荷、对应源码、许可及根记录逐字节保留，不修改原构建。"})
    print(json.dumps({"status": "PASS", "mode": "overlay", "files": len(expected), "output": str(output)}, ensure_ascii=False))


def package(args):
    project = ROOT if args.component == "base" else PLUGIN_PROJECT
    root = review.layout.plain_path(args.root)
    root.relative_to(project / "build")
    output = new_path(args.output, project / "build")
    audit = new_path(args.audit, project / "build/audit")
    if review.merge.running_processes(root):
        raise RuntimeError("候选正在运行，拒绝打包，不终止进程")
    started = time.monotonic()
    before = review.payload(root)
    if args.component == "base" and any(name.startswith("UmiOCR-data/plugins/") for name in before):
        raise ValueError("纯本体不能含推理插件或插件状态")
    result = (review.packaging.create_archive(root, output, streaming=True) if args.component == "base"
              else fast.create_fast_archive(root, output))
    stable = review.payload(root) == before
    record = {"purpose": "local-nonfinal-review-artifact", "component": args.component,
        "status": "PASS" if stable else "FAIL", "inputRoot": str(root), "payload": before,
        "sourceUnchangedDuringPackaging": stable, "archive": result, "formalRelease": False,
        "publicReleaseAuthorized": False, "recordedAt": datetime.now(timezone.utc).isoformat(),
        "elapsedSeconds": time.monotonic() - started, "driverSha256": review.layout.sha256_file(__file__),
        "packagerSha256": review.layout.sha256_file(review.packaging.__file__),
        "limits": "仅本地归档完整性；不替代运行验收和当次程序文案批准，不绕过正式公开发行门禁。"}
    save(audit, record)
    print(json.dumps({key: record[key] for key in ("status", "component", "archive", "elapsedSeconds")}, ensure_ascii=False))
    if not stable:
        raise ValueError("打包期间输入变化")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("overlay", "package"))
    parser.add_argument("--component", choices=("base", "vl"), default="vl")
    for name in ("root", "output", "audit"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    (overlay if args.mode == "overlay" else package)(args)


if __name__ == "__main__":
    main()
