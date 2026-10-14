"""测量基础包与 GPU OCR 插件各自的 site-packages 依赖闭包。

用途：为"把 CUDA / Paddle / 模型迁出基础包"提供可复现的证据，
避免凭直觉删 DLL 或 Python 包。

方法：
1. 读每个 dist-info 的 RECORD ，建立 发行版 → 文件集合 的映射。
   【必须按文件而不是按顶层目录归属】：8 个 nvidia-*-cu12 wheel 共用同一个
   nvidia/ 命名空间目录，PySide6 / PySide6_Essentials / PySide6_Addons 共用
   同一个 PySide6/ 目录，按目录归属会把同一份字节重复计入每个发行版。
2. 用各发行版 METADATA 的 Requires-Dist 建立依赖图，按需展开 extra 。
3. 从两组根需求分别求传递闭包：
   - base ：界面、任务调度、PDF、图像解码、二维码、HTTP、热键
   - gpu  ：paddlepaddle-gpu / paddleocr / paddlex[ocr-core] / opencv
4. 分组体积 = 该组所有发行版【文件并集】的字节数，共享文件只计一次。

用法：
    python build/tools/measure_closure.py <UmiOCR-data 路径> [--out report.json]
"""

import argparse
import json
import re
import sys
from pathlib import Path

# 基础包的根需求【从 py_src 的实际 import 扫描得出】，不靠人工声明。
#
# 第一版这里是手写清单，漏掉了 cv2 ：utils/image_decoder.py 模块级
# import cv2 ，而它被二维码（mission_qrcode）和 HTTP 服务（web_server）
# 依赖。基础包缺了它会在图像解码和二维码功能上直接崩。
# 手写清单必然会漏，因此改为扫描。
#
# 少数模块名与发行版名对不上，需要显式映射。
MODULE_TO_DIST = {
    "cv2": "opencv-contrib-python",
    "fitz": "pymupdf",
    "pymupdf": "pymupdf",
    "PIL": "pillow",
    "PySide6": "pyside6",
    "shiboken6": "shiboken6",
    "zxingcpp": "zxing-cpp",
    "yaml": "pyyaml",
    "dateutil": "python-dateutil",
    "google": "protobuf",
    "bidi": "python-bidi",
    "pypdfium2": "pypdfium2",
}

# py_src/imports 下的自有模块，通过 site.addsitedir 以顶层名导入，
# 不是第三方依赖。
LOCAL_TOP_LEVEL = {"umi_log", "umi_about", "plugin_i18n", "call_func", "py_src"}

# 【AST 扫描原理上抓不到的运行时依赖】：第三方库在某个 API 内部惰性 import
# 的包。源码里没有 import 语句，但缺了就会在运行时报错。
# 每一项都必须写明触发点，新增时同理。
BASE_RUNTIME_EXTRAS = {
    # ocr/output/output_pdf_layered.py 调 PyMuPDF 的 subset_fonts()，
    # 该 API 内部惰性 import fontTools 来构建字体子集。
    "fonttools": "pymupdf.subset_fonts() @ ocr/output/output_pdf_layered.py",
}

# GPU OCR 插件的根需求。paddlex 的 ocr-core extra 带来 shapely / pyclipper /
# python-bidi / imagesize / pypdfium2 等，必须一并纳入闭包。
GPU_ROOTS = [
    "paddlepaddle-gpu",
    "paddleocr",
    "paddlex",
    "opencv-contrib-python",
]
# 需要展开的 extra ： {发行版: {extra 名}}
ROOT_EXTRAS = {"paddlex": {"ocr-core", "ocr_core"}}

_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_EXTRA_VALUE = re.compile(r"""extra\s*==\s*['"]([^'"]+)['"]""")


def canon(name):
    return re.sub(r"[-_.]+", "-", str(name)).strip().lower()


def scanBaseRoots(pySrc, sitePackages):
    """扫描 py_src 的全部 import ，得出基础包真正的第三方根依赖。

    只取顶层模块名；相对 import、标准库和 py_src/imports 下的自有模块都排除。
    扫描的是【模块名】，再经 MODULE_TO_DIST 与 site-packages 的实际目录名
    映射到发行版名。
    """
    import ast

    modules = set()
    for path in sorted(Path(pySrc).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text("utf-8", errors="replace"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # 相对 import ，是本项目自己的模块
                    continue
                if node.module:
                    modules.add(node.module.split(".", 1)[0])

    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    thirdParty = {
        name
        for name in modules
        if name and name not in stdlib and name not in LOCAL_TOP_LEVEL
        and not name.startswith("_")
    }

    roots, unresolved = set(), set()
    for name in sorted(thirdParty):
        if name in MODULE_TO_DIST:
            roots.add(canon(MODULE_TO_DIST[name]))
            continue
        # 模块名与发行版名一致的常见情况
        if (Path(sitePackages) / name).exists() or (Path(sitePackages) / f"{name}.py").exists():
            roots.add(canon(name))
        else:
            unresolved.add(name)

    for dist, reason in BASE_RUNTIME_EXTRAS.items():
        roots.add(canon(dist))
        print(f"  运行时依赖（扫描不到，显式登记）: {dist}  <- {reason}")

    return sorted(roots), sorted(unresolved), sorted(thirdParty)


def loadDistributions(sitePackages):
    """返回 {发行版规范名: {"version", "files": set, "requires": set, "extras": dict}}"""
    dists = {}
    fileSizes = {}

    def sizeOf(relative):
        if relative not in fileSizes:
            target = sitePackages / relative
            try:
                fileSizes[relative] = target.stat().st_size if target.is_file() else 0
            except OSError:
                fileSizes[relative] = 0
        return fileSizes[relative]

    for infoDir in sorted(sitePackages.glob("*.dist-info")):
        metadataPath = infoDir / "METADATA"
        if not metadataPath.is_file():
            continue
        name, version = None, ""
        requires = set()
        extras = {}
        for line in metadataPath.read_text("utf-8", errors="replace").splitlines():
            if not line.strip():
                break  # 头部结束，正文开始
            lowered = line.lower()
            if lowered.startswith("name:"):
                name = line.split(":", 1)[1].strip()
            elif lowered.startswith("version:"):
                version = line.split(":", 1)[1].strip()
            elif lowered.startswith("requires-dist:"):
                spec = line.split(":", 1)[1].strip()
                extraName = None
                if ";" in spec:
                    head, marker = spec.split(";", 1)
                    found = _EXTRA_VALUE.search(marker)
                    if found:
                        extraName = canon(found.group(1))
                    spec = head
                match = _NAME.match(spec)
                if not match:
                    continue
                target = canon(match.group(1))
                if extraName:
                    extras.setdefault(extraName, set()).add(target)
                else:
                    requires.add(target)
        if not name:
            continue

        # RECORD 给出该 wheel 实际安装的每一个文件，是唯一可靠的归属依据。
        files = set()
        recordPath = infoDir / "RECORD"
        if recordPath.is_file():
            for row in recordPath.read_text("utf-8", errors="replace").splitlines():
                relative = row.split(",", 1)[0].strip()
                if not relative or relative.startswith(("..", "/")):
                    continue
                relative = relative.replace("\\", "/")
                if "__pycache__" in relative:
                    continue
                files.add(relative)

        dists[canon(name)] = {
            "name": name,
            "version": version,
            "files": files,
            "requires": requires,
            "extras": extras,
        }
    return dists, sizeOf


def closure(roots, dists, rootExtras=None):
    rootExtras = rootExtras or {}
    seen, missing = set(), set()
    stack = [canon(r) for r in roots]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        if current not in dists:
            missing.add(current)
            continue
        seen.add(current)
        stack.extend(dists[current]["requires"])
        for extraName in rootExtras.get(current, ()):
            stack.extend(dists[current]["extras"].get(canon(extraName), ()))
    return seen, missing


def unionFiles(names, dists):
    """分组的文件并集。共用命名空间目录的发行版不会被重复计算。"""
    files = set()
    for name in names:
        if name in dists:
            files |= dists[name]["files"]
    return files


def total(names, dists, sizeOf):
    return sum(sizeOf(f) for f in unionFiles(names, dists))


def distBytes(name, dists, sizeOf):
    return sum(sizeOf(f) for f in dists[name]["files"]) if name in dists else 0


def table(title, names, dists, sizeOf, limit=None):
    rows = sorted(
        (
            (distBytes(n, dists, sizeOf), dists[n]["name"], dists[n]["version"])
            for n in names
            if n in dists
        ),
        reverse=True,
    )
    grouped = total(names, dists, sizeOf)
    naive = sum(r[0] for r in rows)
    note = ""
    if naive > grouped:
        note = f"（各发行版相加 {naive / 1024 / 1024:,.1f} MiB，含共用目录重复）"
    print(f"\n{title}  —  {len(rows)} 个发行版, 去重后 {grouped / 1024 / 1024:,.1f} MiB {note}")
    print(f"  {'MiB':>10}  {'发行版':<34} 版本")
    for size, name, version in rows[: limit or len(rows)]:
        print(f"  {size / 1024 / 1024:>10,.1f}  {name:<34} {version}")
    if limit and len(rows) > limit:
        rest = sum(r[0] for r in rows[limit:])
        print(f"  {rest / 1024 / 1024:>10,.1f}  ... 其余 {len(rows) - limit} 个")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    sitePackages = args.data_root.resolve() / "site-packages"
    if not sitePackages.is_dir():
        raise SystemExit(f"site-packages 不存在：{sitePackages}")

    dists, sizeOf = loadDistributions(sitePackages)
    print(f"site-packages: {sitePackages}")
    print(f"发行版总数    : {len(dists)}")

    pySrc = args.data_root.resolve() / "py_src"
    baseRoots, unresolved, scanned = scanBaseRoots(pySrc, sitePackages)
    print(f"py_src 第三方 import: {len(scanned)} 个模块 -> {len(baseRoots)} 个根发行版")
    print(f"  根依赖: {', '.join(baseRoots)}")
    if unresolved:
        # 未解析的多半是可选依赖或其它平台专用（如 Xlib / pyobjc）。
        print(f"  [注意] 未能映射到发行版的模块: {', '.join(unresolved)}")

    baseSet, baseMissing = closure(baseRoots, dists)
    gpuSet, gpuMissing = closure(GPU_ROOTS, dists, ROOT_EXTRAS)

    shared = baseSet & gpuSet
    baseOnly = baseSet - gpuSet
    gpuOnly = gpuSet - baseSet
    orphan = set(dists) - baseSet - gpuSet

    table("【共享】base 与 GPU 插件都需要（必须留在基础包）", shared, dists, sizeOf)
    table("【base 独占】", baseOnly, dists, sizeOf)
    table("【GPU 插件独占】可迁出", gpuOnly, dists, sizeOf, limit=25)
    table("【未被任一闭包覆盖】需人工判定", orphan, dists, sizeOf)

    if baseMissing:
        print(f"\n基础闭包中未找到 dist-info 的名字（多为其它平台依赖）: {sorted(baseMissing)}")
    if gpuMissing:
        print(f"GPU 闭包中未找到 dist-info 的名字: {sorted(gpuMissing)}")

    # 实际磁盘占用 vs RECORD 可归属部分，差额是构建过程产生的非 wheel 文件。
    onDisk = sum(f.stat().st_size for f in sitePackages.rglob("*") if f.is_file())
    attributed = total(set(dists), dists, sizeOf)
    baseTotal = total(baseSet, dists, sizeOf)
    gpuTotal = total(gpuSet, dists, sizeOf)

    print("\n===== 汇总（文件级去重）=====")
    print(f"site-packages 实际磁盘占用   : {onDisk / 1024 / 1024:,.1f} MiB")
    print(f"  RECORD 可归属               : {attributed / 1024 / 1024:,.1f} MiB")
    print(f"  未被任何 RECORD 覆盖        : {(onDisk - attributed) / 1024 / 1024:,.1f} MiB")
    print(f"  共享（必须留 base）         : {total(shared, dists, sizeOf) / 1024 / 1024:,.1f} MiB")
    print(f"  base 独占                   : {total(baseOnly, dists, sizeOf) / 1024 / 1024:,.1f} MiB")
    print(f"  GPU 插件独占（可迁出）      : {total(gpuOnly, dists, sizeOf) / 1024 / 1024:,.1f} MiB")
    print(f"  未覆盖（人工判定）          : {total(orphan, dists, sizeOf) / 1024 / 1024:,.1f} MiB")
    print(f"\n  base 闭包合计               : {baseTotal / 1024 / 1024:,.1f} MiB")
    print(f"  GPU 闭包合计（含共享）      : {gpuTotal / 1024 / 1024:,.1f} MiB")
    print(
        f"\n迁出后基础包 site-packages 预估: {baseTotal / 1024 / 1024:,.1f} MiB"
        f"   （较当前减少 {(onDisk - baseTotal) / 1024 / 1024:,.1f} MiB）"
    )

    if args.out:
        report = {
            "sitePackages": str(sitePackages),
            "baseRoots": baseRoots,
            "baseRootsScannedModules": scanned,
            "gpuRoots": GPU_ROOTS,
            "rootExtras": {k: sorted(v) for k, v in ROOT_EXTRAS.items()},
            "groups": {},
            "totals": {},
        }
        for label, names in (
            ("shared", shared),
            ("baseOnly", baseOnly),
            ("gpuOnly", gpuOnly),
            ("orphan", orphan),
        ):
            report["groups"][label] = sorted(
                (
                    {
                        "name": dists[n]["name"],
                        "version": dists[n]["version"],
                        "bytes": distBytes(n, dists, sizeOf),
                        "fileCount": len(dists[n]["files"]),
                    }
                    for n in names
                    if n in dists
                ),
                key=lambda d: -d["bytes"],
            )
            report["totals"][label] = total(names, dists, sizeOf)
        report["totals"]["baseClosure"] = baseTotal
        report["totals"]["gpuClosure"] = gpuTotal
        report["totals"]["onDisk"] = onDisk
        report["totals"]["attributed"] = attributed
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
        print(f"\n报告已写入: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
