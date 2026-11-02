"""只把显式已构建 VL 组件及其对应源码放进新安装 overlay，不覆盖主程序元数据。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = "win32_PaddleOCRVL_1_6"


def no_links(path, tree=False):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or item.is_junction():
            raise ValueError("拒绝链接或 junction：" + str(item))
    if tree:
        for item in path.rglob("*"):
            if item.is_symlink() or item.is_junction():
                raise ValueError("输入树包含链接或 junction：" + str(item))
    return path


def build_output(path):
    path = no_links(path)
    path.resolve().relative_to((ROOT / "build").resolve())
    return path


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def identity(stage):
    stage = no_links(stage)
    plugin = no_links(stage / "UmiOCR-data/plugins" / PLUGIN, tree=True)
    manifest = json.loads((plugin / "umi-plugin.json").read_text(encoding="utf-8"))
    if manifest.get("id") != PLUGIN or not isinstance(manifest.get("version"), str):
        raise ValueError("输入不是所选 VL 组件。")
    source = no_links(stage / "source", tree=True)
    for relative in ("Build-Plugin.ps1", "VERSION", "requirements.lock", "SOURCE-CODE.md",
                     "tools/bundle_llama_runtime.py", PLUGIN + "/runtime.py", PLUGIN + "/umi-plugin.json"):
        if not (source / relative).is_file():
            raise ValueError("对应源码缺少：" + relative)
    if (source / "VERSION").read_text(encoding="utf-8").strip() != manifest["version"]:
        raise ValueError("对应源码 VERSION 与插件独立版本不符。")
    source_manifest = json.loads((source / PLUGIN / "umi-plugin.json").read_text(encoding="utf-8"))
    if source_manifest != manifest:
        raise ValueError("对应源码中的清单与实际插件不一致。")
    licenses = no_links(stage / "LICENSES", tree=True)
    if not licenses.is_dir():
        raise ValueError("插件许可目录不存在。")
    return stage, plugin, source, licenses, manifest


def preserve(stage, output, *, overlay=False):
    stage, plugin, source, licenses, manifest = identity(stage)
    output = build_output(output)
    if output == stage or output.is_relative_to(stage) or stage.is_relative_to(output):
        raise ValueError("输出必须与只读构建输入分离。")
    source_target = no_links(output / "LICENSES/plugins" / PLUGIN / "source-records")
    if source_target.exists():
        raise FileExistsError("对应源码目标已存在，禁止覆盖。")
    if overlay:
        if output.exists():
            raise FileExistsError("安装 overlay 必须使用新目录。")
        target = output / "UmiOCR-data/plugins" / PLUGIN
        target.parent.mkdir(parents=True)
        shutil.copytree(plugin, target)
        license_target = source_target.parent
        license_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(licenses, license_target)
    else:
        target = output / "UmiOCR-data/plugins" / PLUGIN
        no_links(target, tree=True)
        current = json.loads((target / "umi-plugin.json").read_text(encoding="utf-8"))
        if current != manifest:
            raise ValueError("组合包插件与原构建输入不一致。")
    source_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, source_target)
    hashes = {}
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        copied = source_target / relative
        original_hash = digest(path)
        if digest(copied) != original_hash:
            raise ValueError("源码复制内容不一致：" + relative.as_posix())
        hashes[relative.as_posix()] = original_hash
    return {"operation": "prepare-overlay" if overlay else "retain-corresponding-source",
            "pluginId": PLUGIN, "version": manifest["version"], "input": str(stage), "output": str(output),
            "correspondingSource": str(source_target), "sourceFileHashes": hashes,
            "runtimeCopied": overlay, "runtimeModified": False, "publicReleaseAuthorized": False,
            "boundary": "复制完整原始对应源码，不覆盖主程序根 VERSION/SOURCE-CODE，不把装配当作运行验收。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("overlay", "retain"))
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    audit = build_output(args.audit)
    if audit.exists():
        raise FileExistsError("不覆盖历史装配证据。")
    result = preserve(args.stage, args.output, overlay=args.command == "overlay")
    audit.parent.mkdir(parents=True, exist_ok=True)
    with audit.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({key: value for key, value in result.items() if key != "sourceFileHashes"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
