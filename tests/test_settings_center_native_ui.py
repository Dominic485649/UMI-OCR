"""本轮设置集中/GPU 下拉的真实 Windows Qt 源运行验收；准备阶段不创建窗口。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import socket
import stat
import sys
import time
import traceback
import xml.etree.ElementTree as ET


REPO = Path(__file__).resolve().parents[1]
AUDIT_ROOT = REPO / "build/audit/settings-gpu-20261027-r1"
DEFAULT_RUNTIME = REPO / "release/Umi-OCR/UmiOCR-data"
DEFAULT_VL = Path("D:/Code/Python/Umi-OCR-Plugin/win32_PaddleOCRVL_1_6")
PP = "win32_PaddleOCRv6_CUDA"
VL = "win32_PaddleOCRVL_1_6"
LANGUAGES = ("zh_CN", "en_US", "ja_JP", "pt", "ru_RU", "ta", "zh_TW")
TASKS = (("ScreenshotOCR", "ScreenshotOCR"), ("BatchOCR", "BatchOCR"), ("BatchDOC", "BatchPDF"))
GLOBAL_TITLES = ("界面和外观", "插件管理", "模型设置", "截图识别参数", "批量图片识别参数", "批量文档识别参数")
DEVICE_TEXTS = ("正在读取 NVIDIA 显卡…", "未发现可用的 NVIDIA GPU", "未找到 NVIDIA 驱动", "读取显卡超时，请刷新重试", "读取显卡失败，请刷新重试", "已保存但当前不可用：%1", "刷新显卡列表")
RUNTIME_READY = "已发现 {count} 个 NVIDIA 设备。"
FORBIDDEN_MODULES = {"paddle", "paddleocr", "paddlex", "onnxruntime", "torch", "transformers", "tensorrt", "cupy"}
CHECKS = ("首帧", "源码来源", "先开设置的参数来源", "活动布局与插件末尾GPU", "实际安装模型枚举", "共享模型与生命周期", "OCR终止范围", "插件禁用与恢复", "GPU真实点击", "无推理与进程回收", "输入未变化") + tuple("任务来源." + key for key, _ in TASKS) + tuple("热切语言." + code for code in LANGUAGES)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json_new(path, value):
    path = Path(path)
    require(path.parent.is_dir(), "审计输出的父目录不存在：" + str(path.parent))
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def reject_links(path):
    """拒绝实际路径及其已存在祖先中的符号链接和目录联接。"""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if not part.exists():
            continue
        details = part.lstat()
        require(not stat.S_ISLNK(details.st_mode) and not getattr(details, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
                "本轮源沙盒不允许链接或 junction：" + str(part))
    return path


def checked_sandbox(path):
    path = reject_links(path)
    allowed = (REPO / "build/tmp", REPO / "build/staging")
    require(any(path.is_relative_to(root) for root in allowed), "源沙盒必须位于本项目 build/tmp 或 build/staging")
    require(path.name.startswith("settings-gpu-20261027-"), "源沙盒必须使用本轮独立名称")
    return path


def checked_output(path):
    path = reject_links(path)
    require(path.is_relative_to(AUDIT_ROOT) and path.suffix == ".json", "审计记录必须位于本轮工作根，且使用新的 JSON 文件")
    require(not path.exists(), "不得覆盖历史审计记录：" + str(path))
    return path


def source_files(root):
    """仅枚举源码树；明确排除字节码，不跟随任何链接。"""
    root = reject_links(root)
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(name for name in directories if name != "__pycache__")
        for name in directories:
            reject_links(Path(current) / name)
        for name in sorted(files):
            path = reject_links(Path(current) / name)
            if path.suffix.lower() in {".pyc", ".pyo"}:
                continue
            require(path.name not in {"app.zip", "ui.rcc"}, "源码输入不应包含旧应用载荷：" + str(path))
            yield path


def csv_expected(path, source):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row.get("zh_CN") == source]
    require(len(rows) == 1, "本轮运行译文必须有唯一真实源行：" + source)
    return {code: rows[0].get(code, "").strip() for code in LANGUAGES}


def translation_inputs(source, vl_root):
    expected, inputs, warnings = {}, {}, []
    for code in LANGUAGES:
        values = {"GlobalConfigs": {}, "NvidiaDeviceConfig": {}}
        pairs = (("GlobalConfigs", GLOBAL_TITLES), ("NvidiaDeviceConfig", DEVICE_TEXTS))
        if code == "zh_CN":
            for context, messages in pairs:
                values[context] = dict(zip(messages, messages))
        else:
            path = source / ("dev-tools/i18n/release/" + code + ".ts")
            reject_links(path)
            inputs[str(path)] = sha256(path)
            tree = ET.parse(path)
            for context, messages in pairs:
                candidates = [node for node in tree.getroot().findall("context") if node.findtext("name") == context]
                for message in messages:
                    nodes = [node for group in candidates for node in group.findall("message") if node.findtext("source") == message]
                    target = nodes[0].find("translation") if len(nodes) == 1 else None
                    text = "".join(target.itertext()) if target is not None and target.get("type") not in {"unfinished", "obsolete", "vanished"} else ""
                    values[context][message] = text
                    if not text.strip():
                        warnings.append(code + " 缺少已完成译文：" + context + "/" + message)
        expected[code] = values
    for name, path, message in (("ready", source / "UmiOCR-data/i18n/runtime.csv", RUNTIME_READY),
                                ("pp_device", source / ("UmiOCR-data/plugins/" + PP + "/i18n.csv"), "CUDA 设备"),
                                ("vl_device", vl_root / "i18n.csv", "版面检测设备")):
        inputs[str(path)] = sha256(path)
        values = csv_expected(path, message)
        for code in LANGUAGES:
            expected[code][name] = values[code]
            if not values[code]:
                warnings.append(code + " 缺少运行译文：" + message)
    return expected, inputs, warnings


def prepare(args):
    """只复制已授权轻量输入，不导入 Qt，不创建窗口，不作验收通过结论。"""
    source, runtime, vl_root = (reject_links(path) for path in (args.source_root, args.runtime_data, args.vl_root))
    require(source == REPO, "本轮主源码必须为当前项目")
    require(runtime == DEFAULT_RUNTIME and vl_root == DEFAULT_VL, "只允许本轮指定的只读便携依赖和授权 VL 源码")
    sandbox, output = checked_sandbox(args.sandbox), checked_output(args.output)
    require(not sandbox.exists(), "准备必须使用全新源沙盒：" + str(sandbox))
    require(sandbox.parent.is_dir(), "源沙盒父目录不存在")
    expected, translation_hashes, warnings = translation_inputs(source, vl_root)
    sandbox.mkdir()
    data = sandbox / "UmiOCR-data"
    data.mkdir()
    originals, copies, total = {}, {}, 0

    def copy_one(origin, destination):
        nonlocal total
        origin = reject_links(origin)
        require(origin.is_file() and origin.stat().st_size <= 32 * 1024 * 1024, "轻量源运行输入缺失或意外过大：" + str(origin))
        before = sha256(origin)
        destination.parent.mkdir(parents=True, exist_ok=True)
        require(not destination.exists(), "禁止覆盖沙盒已有输入：" + str(destination))
        shutil.copy2(origin, destination)
        require(sha256(origin) == before == sha256(destination), "输入在复制期间变化：" + str(origin))
        total += origin.stat().st_size
        require(total < 128 * 1024 * 1024, "轻量沙盒超过预期范围，拒绝复制大型载荷")
        originals[str(origin)] = before
        copies[str(destination)] = before

    source_data = source / "UmiOCR-data"
    for name in ("main.py", "about.json"):
        copy_one(source_data / name, data / name)
    for name in ("py_src", "qt_res", "i18n"):
        for path in source_files(source_data / name):
            copy_one(path, data / path.relative_to(source_data))
    plugin_files = {
        PP: (source_data / "plugins" / PP, ("__init__.py", "api.py", "config.py", "i18n_helpers.py", "i18n.csv", "umi-plugin.json")),
        VL: (vl_root, ("__init__.py", "api.py", "ocr_api.py", "checks.py", "asset_paths.py", "budgets.py", "runtime.py", "page.py", "StructuredDocument.qml", "i18n.csv", "umi-plugin.json")),
    }
    for plugin_id, (origin, names) in plugin_files.items():
        for name in names:
            copy_one(origin / name, data / "plugins" / plugin_id / name)
    copy_one(runtime.parent / "Umi-OCR.exe", sandbox / "Umi-OCR.exe")
    # 后续驱动迭代不能抹掉本轮复现输入；这里只存原始字节，不从迁移路径执行。
    copy_one(Path(__file__).resolve(), sandbox / "native-driver-inputs/test_settings_center_native_ui.py")
    copy_one(REPO / "tests/test_hot_ui.py", sandbox / "native-driver-inputs/test_hot_ui.py")
    dependency_names = ("runtime/python.exe", "runtime/python313.dll", "runtime/python313.zip",
                        "site-packages/shiboken6/Shiboken.pyd", "site-packages/shiboken6/shiboken6.abi3.dll",
                        "site-packages/PySide6/QtCore.pyd", "site-packages/PySide6/QtQml.pyd", "site-packages/PySide6/QtQuick.pyd",
                        "site-packages/PySide6/Qt6Core.dll", "site-packages/PySide6/Qt6Qml.dll", "site-packages/PySide6/Qt6Quick.dll",
                        "site-packages/PySide6/plugins/platforms/qwindows.dll")
    dependencies = {str(reject_links(runtime / name)): sha256(runtime / name) for name in dependency_names}
    for name in ("os-temp", "os-cache", "os-roaming", "os-local", "qt-cache"):
        (sandbox / name).mkdir()
    driver_inputs = {str(Path(__file__).resolve()): sha256(__file__), str(REPO / "tests/test_hot_ui.py"): sha256(REPO / "tests/test_hot_ui.py")}
    manifest = {"format": "settings-center-native-source-v1", "status": "PREPARED_NOT_RUN", "acceptance": "NOT_RUN",
                "scope": "源运行，不是包内/归档验收；不重打包、不安装、不替换 release", "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "sandbox": str(sandbox), "source_root": str(source), "vl_source": str(vl_root), "runtime_data": str(runtime),
                "runtime_python": str(runtime / "runtime/python.exe"), "python_preparation": sys.version,
                "source_inputs": {**originals, **translation_hashes}, "snapshot_inputs": copies, "dependency_inputs": dependencies,
                "driver_inputs": driver_inputs, "translation_expected": expected, "preparation_warnings": warnings,
                "copied_file_count": len(copies), "copied_bytes": total,
                "excluded": ["旧 app.zip/ui.rcc", "用户配置/日志/任务数据", "插件 vendor/models/模型与推理二进制", "插件推理 worker 与锁的伪造"],
                "read_only_shared_dependencies": str(runtime / "site-packages"),
                "model_acceptance": "未执行；插件 ready 仅表示轻量注册，不代表健康检查或推理验收"}
    write_json_new(output, manifest)
    print(json.dumps({"status": manifest["status"], "manifest": str(output), "sandbox": str(sandbox), "files": len(copies), "bytes": total, "warnings": warnings}, ensure_ascii=False))
    return 0


def changed_inputs(mapping):
    return [path for path, digest in mapping.items() if not Path(path).is_file() or sha256(path) != digest]


def trusted_probe(executable, argv, cwd, expected_python, expected_code_root, bootstrap):
    """同时核对构造参数及Windows标准库实际审计形态，不宽松拆分命令行。"""
    expected = [str(expected_python), "-I", "-B", "-X", "utf8", "-u", "-c", bootstrap, str(expected_code_root)]
    if isinstance(argv, (list, tuple)):
        valid_arguments = list(argv) == expected
        effective_executable = executable if executable is not None else (argv[0] if argv else None)
    elif os.name == "nt" and isinstance(argv, str):
        import subprocess
        # Windows在审计前调用list2cmdline，未显式传executable时该字段仍为None。
        valid_arguments = argv == subprocess.list2cmdline(expected)
        effective_executable = executable if executable is not None else expected[0]
    else:
        return False
    try:
        return (valid_arguments and os.path.normcase(os.path.abspath(effective_executable)) == os.path.normcase(str(expected_python))
                and cwd is not None and os.path.normcase(os.path.abspath(cwd)) == os.path.normcase(str(expected_code_root)))
    except (TypeError, ValueError, OSError):
        return False


def embedded_qt_support(name, module):
    """只识别真实内嵌载入器及其同一模块别名，不放行任意相对路径。"""
    import io
    import zipfile
    canonical = getattr(module, "__name__", "")
    if canonical != "shibokensupport" and not canonical.startswith("shibokensupport."):
        return None
    alias = "PySide6.support" + canonical[len("shibokensupport"):]
    if name not in {canonical, alias} or sys.modules.get(canonical) is not module:
        return None
    root = sys.modules.get("shibokensupport")
    loader = getattr(module, "__loader__", None)
    if (loader is None or loader is not getattr(root, "__loader__", None)
            or type(loader).__module__ != "signature_bootstrap"
            or type(loader).__qualname__ != "EmbeddableZipImporter"):
        return None
    origin = getattr(module, "__file__", None)
    stem = canonical.replace(".", "/")
    if origin not in {stem + ".py", stem + "/__init__.py"}:
        return None
    archive = getattr(loader, "zfile", None)
    if not isinstance(archive, zipfile.ZipFile) or not isinstance(archive.fp, io.BytesIO):
        return None
    try:
        info = archive.getinfo(origin)
        if info.file_size > 1024 * 1024:
            return None
        payload = archive.read(info)
    except (KeyError, OSError, ValueError, zipfile.BadZipFile):
        return None
    return {"canonical_module": canonical, "virtual_file": origin,
            "loader": "signature_bootstrap.EmbeddableZipImporter",
            "embedded_source_sha256": hashlib.sha256(payload).hexdigest()}


def qt_dependency_sources(packages, dependencies):
    packages = Path(packages).resolve(strict=True)
    owner = packages / "shiboken6/Shiboken.pyd"
    loaded = sys.modules.get("shiboken6.Shiboken")
    require(loaded is not None and Path(getattr(loaded, "__file__", "")).resolve() == owner,
            "Shiboken内嵌模块的拥有者不是指定便携扩展")
    digest = sha256(owner)
    require(dependencies.get(str(owner)) == digest, "Shiboken拥有者不在本轮锁定依赖中或哈希已改变")
    files, embedded = {}, {}
    for name, module in list(sys.modules.items()):
        if name.split(".")[0] not in {"PySide6", "shiboken6", "shibokensupport"}:
            continue
        origin = getattr(module, "__file__", None)
        if not origin:
            continue
        path = Path(origin)
        if path.is_absolute():
            require(path.resolve().is_relative_to(packages), "Qt依赖不是指定只读便携依赖：" + origin)
            files[name] = str(path.resolve())
        else:
            record = embedded_qt_support(name, module)
            require(record is not None, "Qt相对来源不是已核对的内嵌模块：" + name + " " + origin)
            embedded[name] = record
    return {"file_modules": files, "embedded_modules": embedded,
            "embedded_owner": {"path": str(owner), "sha256": digest}}


def acceptance(report):
    missing = [key for key in CHECKS if report["checks"].get(key, {}).get("status") != "PASS"]
    complete = (report.get("scenario_completed") is True and report.get("normal_exit") is True
                and not report.get("errors") and not report.get("safety_blocks") and not missing and len(report.get("screenshots", [])) >= 2)
    return {"status": "PASS" if complete else "INCOMPLETE", "complete": complete, "required_not_pass": missing,
            "scope": "仅所记录输入的真实 Windows Qt 源运行；不代表包内、归档、插件健康或模型推理验收"}


def load_scheduler():
    path = REPO / "tests/test_hot_ui.py"
    spec = importlib.util.spec_from_file_location("settings_center_native_scheduler", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_native(args):
    require(args.execute_authorized, "必须先收到主线程“可以执行”，再显式使用 --execute-authorized；本命令不会自行授权")
    manifest_path = reject_links(args.manifest)
    require(manifest_path.is_relative_to(AUDIT_ROOT), "只运行本轮审计根中的准备清单")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("format") == "settings-center-native-source-v1", "准备清单格式不匹配")
    sandbox, output = checked_sandbox(manifest["sandbox"]), checked_output(args.output)
    data, runtime = sandbox / "UmiOCR-data", reject_links(manifest["runtime_data"])
    python = reject_links(manifest["runtime_python"])
    require(runtime == DEFAULT_RUNTIME and Path(sys.executable).resolve() == python.resolve(), "必须使用已记录的现有便携 Python，不复制或切换运行时")
    report = {"mode": "真实Windows-Qt-源运行", "scope": manifest["scope"], "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path),
              "sandbox": str(sandbox), "runtime_data": str(runtime), "executable": sys.executable, "python": sys.version,
              "settings_scope": "只读写本次全新源沙盒；不读取或恢复真实用户配置", "checks": {key: {"status": "NOT_RUN"} for key in CHECKS},
              "errors": [], "safety_blocks": [], "allowed_device_processes": [], "screenshots": [], "operation_events": [],
              "scenario_completed": False, "normal_exit": False, "model_inference": "NOT_RUN", "package_archive_acceptance": "NOT_RUN"}
    started, engines, processes = time.monotonic(), [], []
    previous_engine = previous_installer = previous_popen = finder = None
    app = None
    active_check = "首帧"

    def check(key, **details):
        report["checks"][key] = {"status": "PASS", **details}

    try:
        for field in ("source_inputs", "snapshot_inputs", "dependency_inputs", "driver_inputs"):
            differences = changed_inputs(manifest[field])
            require(not differences, "准备输入已变化，必须用当前源码建立另一个全新沙盒，不得冻结旧PASS：" + json.dumps(differences, ensure_ascii=False))
        require(not manifest["preparation_warnings"], "翻译准备尚未完成，不能开始原生验收：" + json.dumps(manifest["preparation_warnings"], ensure_ascii=False))
        require(not (data / "app.zip").exists() and not (data / "ui.rcc").exists(), "源沙盒含旧应用归档")
        write_json_new(sandbox / ".native-run-owner.json", {"pid": os.getpid(), "manifest": str(manifest_path), "created": time.time()})
        sys.dont_write_bytecode = True
        for variable, name in (("TEMP", "os-temp"), ("TMP", "os-temp"), ("XDG_CACHE_HOME", "os-cache"), ("APPDATA", "os-roaming"), ("LOCALAPPDATA", "os-local"), ("QT_SHADER_CACHE_PATH", "qt-cache")):
            os.environ[variable] = str(sandbox / name)
        os.environ["QML_DISABLE_DISK_CACHE"] = "1"
        packages = runtime / "site-packages"
        sys.path[:] = [entry for entry in sys.path if "app.zip" not in entry.replace("\\", "/").lower()]
        sys.path.insert(0, str(packages))
        dll_handles = [os.add_dll_directory(str(packages / "PySide6"))]
        namespace = runpy.run_path(str(data / "main.py"), run_name="settings_center_source_bootstrap")
        namespace["initRuntimeEnvironment"]()
        import site
        site.addsitedir(str(data / "py_src/imports"))
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(packages / "PySide6/plugins/platforms")
        from PySide6 import QtCore, QtQml
        from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPointF, QSettings, QTimer, Qt
        from PySide6.QtGui import QGuiApplication, QMouseEvent
        from PySide6.QtQml import QQmlEngine, QQmlExpression
        from PySide6.QtQuickControls2 import QQuickStyle
        from PySide6.QtWidgets import QApplication
        import PySide6
        import psutil
        import shiboken6
        QCoreApplication.setLibraryPaths([str(packages / "PySide6/plugins")])
        report["versions"] = {"PySide6": PySide6.__version__, "Qt": QtCore.qVersion(), "platform": str(sys.getwindowsversion())}
        require(sys.version_info[:3] == (3, 13, 16) and QtCore.qVersion() == "6.11.2", "实际便携运行时版本与本轮指定不符")
        occupied = []
        for process in psutil.process_iter(["pid", "exe", "cwd"]):
            if process.pid == os.getpid():
                continue
            if any(value and Path(value).is_relative_to(sandbox) for value in (process.info.get("exe"), process.info.get("cwd"))):
                occupied.append(process.info)
        require(not occupied, "新沙盒意外被其它进程占用，未停止任何进程：" + str(occupied))
        report["process_preflight"] = {"sandbox_occupants": occupied, "self_pid": os.getpid(), "other_processes_stopped": False}
        os.MessageBox = lambda message, *_a, **_k: report["errors"].append("真实启动诊断：" + str(message))
        from py_src.utils import cuda_device_probe
        from py_src.utils.doc_probe import _runtime_paths
        paths = _runtime_paths()
        require(paths[0] == data and paths[1] == data and paths[2] == runtime and paths[3] == python, "设备发现未使用当前源代码和指定便携解释器：" + str(paths))
        bootstrap = cuda_device_probe._WORKER_BOOTSTRAP
        report["probe_contract"] = {"code_root": str(data), "cwd": str(data), "runtime_python": str(python), "bootstrap_sha256": hashlib.sha256(bootstrap.encode()).hexdigest(),
                                    "environment": {key: os.environ.get(key) for key in ("CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER")}, "meaning": "仅 CUDA 逻辑设备枚举，不是插件健康检查或模型启动"}

        class NoInferenceImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split(".")[0] in FORBIDDEN_MODULES or fullname in {PP + ".worker", VL + ".worker"}:
                    report["safety_blocks"].append({"kind": "推理模块", "module": fullname})
                    raise RuntimeError("本轮源GUI验收禁止推理模块导入：" + fullname)
                return None

        finder = NoInferenceImports()
        sys.meta_path.insert(0, finder)

        def audit(event, values):
            if event == "subprocess.Popen":
                executable, argv, cwd, _environment = values
                if not trusted_probe(executable, argv, cwd, python, data, bootstrap):
                    report["safety_blocks"].append({"kind": "非设备发现子进程", "executable": str(executable), "argv": [str(value)[:300] for value in argv] if isinstance(argv, (list, tuple)) else str(argv)[:600], "cwd": str(cwd)})
                    raise RuntimeError("本轮只允许精确可信 CUDA 设备发现子进程，禁止模型/健康探测及其它子进程")
                require(len(report["allowed_device_processes"]) < 40, "设备发现次数超过本轮有限预算")
                canonical_argv = [str(python), "-I", "-B", "-X", "utf8", "-u", "-c", bootstrap, str(data)]
                report["allowed_device_processes"].append({"executable": str(python), "argv": canonical_argv, "cwd": str(cwd),
                    "audit_executable": str(executable) if executable is not None else None,
                    "audit_command_line": argv if isinstance(argv, str) else None})
            elif event in {"os.system", "os.posix_spawn", "os.spawn"}:
                report["safety_blocks"].append({"kind": "其它进程启动接口", "event": event})
                raise RuntimeError("源GUI验收禁止其它进程启动接口")
            elif event == "ctypes.dlopen" and re.search(r"(?:nvcuda|cudnn|cublas|paddle|llama)", str(values[0]), re.I):
                report["safety_blocks"].append({"kind": "宿主推理动态库", "library": str(values[0])})
                raise RuntimeError("宿主进程不得加载推理/CUDA动态库")

        sys.addaudithook(audit)
        import subprocess
        previous_popen = subprocess.Popen

        class TrackedPopen(previous_popen):
            def __init__(self, *arguments, **keywords):
                # Windows审计字符串之外，再在真实构造入口逐项校验原始argv及隐藏窗口边界。
                argv = keywords.get("args", arguments[0] if arguments else None)
                executable, cwd = keywords.get("executable"), keywords.get("cwd")
                valid = (isinstance(argv, (list, tuple)) and trusted_probe(executable, argv, cwd, python, data, bootstrap)
                         and keywords.get("shell", False) is False
                         and keywords.get("creationflags") == subprocess.CREATE_NO_WINDOW
                         and keywords.get("stdin") == subprocess.DEVNULL and keywords.get("stdout") == subprocess.PIPE
                         and keywords.get("stderr") == subprocess.DEVNULL)
                if not valid:
                    report["safety_blocks"].append({"kind": "非可信Popen构造参数", "executable": str(executable), "argv": str(argv)[:600], "cwd": str(cwd)})
                    raise RuntimeError("真实Popen构造参数不符合本轮唯一CUDA设备发现契约")
                report.setdefault("probe_constructor_checks", []).append({"executable": str(argv[0]), "cwd": str(cwd),
                    "argv_exact": True, "shell": False, "creationflags": keywords["creationflags"], "stdio": "DEVNULL/PIPE/DEVNULL"})
                super().__init__(*arguments, **keywords)
                processes.append(self)
                report["allowed_device_processes"][-1]["pid"] = self.pid

        subprocess.Popen = TrackedPopen
        report["qt_messages"] = []
        previous_installer = QtCore.qInstallMessageHandler

        def install_observer(handler):
            def observed(kind, context, text):
                # PySide 6.11的IntEnum字符串可为数字，必须用枚举名保留严重级别。
                name = getattr(kind, "name", None) or {QtCore.QtMsgType.QtDebugMsg: "QtDebugMsg", QtCore.QtMsgType.QtInfoMsg: "QtInfoMsg",
                    QtCore.QtMsgType.QtWarningMsg: "QtWarningMsg", QtCore.QtMsgType.QtCriticalMsg: "QtCriticalMsg", QtCore.QtMsgType.QtFatalMsg: "QtFatalMsg"}.get(kind, str(kind))
                counts = report.setdefault("qt_message_counts", {})
                counts[name] = counts.get(name, 0) + 1
                entry = {"type": name, "file": context.file, "line": context.line, "text": text}
                problem = kind in {QtCore.QtMsgType.QtWarningMsg, QtCore.QtMsgType.QtCriticalMsg, QtCore.QtMsgType.QtFatalMsg}
                if len(report["qt_messages"]) < 500:
                    report["qt_messages"].append(entry)
                elif problem:
                    # 七语重载的普通日志不能挤掉后半程QML警告/错误；溢出也必须使验收失败。
                    extra = report.setdefault("qt_problems_after_debug_budget", [])
                    if len(extra) < 200:
                        extra.append(entry)
                    else:
                        report["qt_problem_overflow"] = report.get("qt_problem_overflow", 0) + 1
                if handler is not None:
                    handler(kind, context, text)
            return previous_installer(observed)

        QtCore.qInstallMessageHandler = install_observer
        settings = QSettings(str(data / ".settings"), QSettings.Format.IniFormat)
        settings.setFallbacksEnabled(False)
        require(not settings.allKeys(), "全新源沙盒不应含既有配置")
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        initial = {"Global/server.enable": False, "Global/server.host": "127.0.0.1", "Global/server.port": port,
                   "Global/ocr.lifecycle.warmupMode": "lazy", "Global/ocr.lifecycle.cleanupPolicy": "never",
                   "Global/ui.theme": "Default Light", "Global/window.startupInvisible": False,
                   "Global/window.messageMemory": ["globalConfigsKey"], "Global/window.simpleNotificationType": "none",
                   "TabPageManager/openPageList": ["Navigation"], "TabPageManager/showPageIndex": 0,
                   "ScreenshotOCR/hotkey.screenshot": "", "ScreenshotOCR/hotkey.paste": "", "ScreenshotOCR/hotkey.reScreenshot": ""}
        for key, value in initial.items():
            settings.setValue(key, value)
        settings.sync()
        require(settings.status() == QSettings.Status.NoError, "隔离配置写入失败")
        del settings
        write_json_new(data / ".pre_settings", {"i18n": "zh_CN", "opengl": "", "server_port": port, "last_pid": -1, "last_ptime": -1})
        write_json_new(data / "plugins/.plugins_state", {})
        report["initial_settings"] = initial
        scheduler = load_scheduler()
        previous_engine = QtQml.QQmlApplicationEngine

        def evaluate(obj, code):
            expression = QQmlExpression(QQmlEngine.contextForObject(obj), obj, code)
            value = expression.evaluate()
            require(not expression.hasError(), "真实QML观测异常：" + expression.error().toString())
            if isinstance(value, tuple):
                value = value[0]
            return value.toVariant() if hasattr(value, "toVariant") else value

        class Engine(previous_engine):
            def load(self, *values):
                nonlocal active_check
                report["engine_load"] = [str(value) for value in values]
                super().load(*values)
                engines.append(self)
                require(bool(self.rootObjects()), "当前源码没有创建真实主窗口")
                window = self.rootObjects()[0]
                self.finished = self.begun = False

                def js(code, obj=window):
                    return evaluate(obj, code)

                def jjson(code, obj=window):
                    encoded = js("JSON.stringify(" + code + ")", obj)
                    require(isinstance(encoded, str), "真实QML对象无法序列化：" + code[:200])
                    return json.loads(encoded)

                observed_global = js("qmlapp.globalConfigs")
                report["cuda_snapshot_events"] = []

                def observe_cuda_snapshot():
                    if self.finished:
                        return
                    try:
                        actual = observed_global.property("cudaDeviceSnapshot")
                        actual = actual.toVariant() if hasattr(actual, "toVariant") else actual
                        actual = json.loads(json.dumps(actual, ensure_ascii=False))
                        from py_src.utils.i18n_configs import I18n
                        report["cuda_snapshot_events"].append({"seconds": round(time.monotonic() - started, 4), "language": I18n.langCode, "snapshot": actual})
                        require(len(report["cuda_snapshot_events"]) <= 128, "设备快照事件超过本轮有限预算")
                    except Exception as exc:
                        report["errors"].append("实际CUDA快照留存失败：" + repr(exc))

                observed_global.cudaDeviceSnapshotChanged.connect(observe_cuda_snapshot)
                self.cuda_snapshot_observer = observe_cuda_snapshot
                observe_cuda_snapshot()

                def finish(error=None):
                    if self.finished:
                        return
                    self.finished = True
                    if error is not None:
                        report["errors"].append("".join(traceback.format_exception(type(error), error, error.__traceback__)))
                        report["checks"][active_check] = {"status": "FAIL", "reason": str(error)}
                        try:
                            report["failure_task_sources"] = jjson("(function(){const m=qmlapp.globalConfigs.ocrManager;const out={apiKey:m.apiKey,taskSourcesRevision:m.taskSourcesRevision,sources:{}};for(const category of ['ScreenshotOCR','BatchOCR','BatchPDF']){const s=m.taskSources[category];if(!s){out.sources[category]={exists:false};continue}try{const definitions={};for(const key in s.originDict){const origin=s.originDict[key];definitions[key]={title:origin.title===undefined?null:origin.title,type:origin.type,fullKey:origin.fullKey}}out.sources[category]={exists:true,object:String(s),category:s.category_,configKeys:Object.keys(s.configDict),definitions:definitions,values:s.getValueDict(),parameterKeys:m.taskParameterItems(s).map(item=>item.key),subscription:s.reloadSubscriptionGroup,panelBuilt:s.panelBuilt}}catch(e){out.sources[category]={exists:true,error:String(e)}}}return out})()")
                            report["failure_layout"] = layout()
                            report["failure_bound_models"] = jjson("(function(){const root=qmlapp.globalConfigs.panelLayout||[];const plugins=root.find(item=>item.key==='plugins');const models=plugins&&(plugins.items||[]).find(item=>item.key==='plugins.models');return {topKeys:root.map(item=>item.key),modelChildren:models?(models.items||[]).map(item=>item.key):null,profiles:models?(models.items||[]).filter(item=>item.key.startsWith('plugins.models.')).map(item=>({key:item.key,title:item.origin?item.origin.title:null,parameterKeys:(item.items||[]).map(child=>child.key)})):null}})()")
                            report["failure_active_items"] = titles()
                            report["failure_component_records"] = jjson("qmlapp.globalConfigs.compList.map((item,index)=>({index:index,exists:!!item,key:item?item.key:null,title:item&&item.title!==undefined?item.title:null,object:item?String(item):null,parentKey:item&&item.parent?item.parent.key:null,sourceKey:item?item.sourceKey:null}))")
                        except Exception as diagnostics_error:
                            report["failure_source_diagnostic_error"] = str(diagnostics_error)
                        try:
                            capture("失败现场")
                        except Exception as capture_error:
                            report["failure_capture_error"] = str(capture_error)
                    QApplication.instance().quit()

                def settled():
                    return bool(js("qmlapp.globalConfigs.applyPhase===0 && !qmlapp.globalConfigs.backendApplyPending && !qmlapp.globalConfigs.pluginRefreshPending && !qmlapp.globalConfigs.ocrManager.applying && !qmlapp.globalConfigs.documentManager.applying && !qmlapp.msnConnector.isBusy()"))

                def wait(predicate, label, timeout=2.5):
                    yield from scheduler.wait_transition(predicate, timeout=timeout, label=label)

                def activate(key):
                    page = js("qmlapp.tab.openTabPageByKey(" + json.dumps(key) + ")")
                    require(page is not None, "真实任务页未能打开：" + key)
                    return page

                def comp(key):
                    result = js("qmlapp.globalConfigs.compList.find(item=>item.key===" + json.dumps(key) + ") || null")
                    require(result is not None, "活动控件不存在：" + key)
                    return result

                def set_global(key, value):
                    js("value(" + json.dumps(value, ensure_ascii=False) + ")", comp(key))

                def identity(item):
                    return int(shiboken6.getCppPointer(item)[0])

                def walk(root):
                    pending = [root]
                    while pending:
                        item = pending.pop(0)
                        yield item
                        pending.extend(item.childItems())

                def exposed(item):
                    if not item.isVisible() or item.width() <= 0 or item.height() <= 0:
                        return False
                    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
                    if not (0 <= point.x() < window.width() and 0 <= point.y() < window.height()):
                        return False
                    ancestor = item
                    while ancestor is not None:
                        if not ancestor.isVisible() or ancestor.opacity() < .95:
                            return False
                        if ancestor.clip() and not ancestor.boundingRect().contains(ancestor.mapFromScene(point)):
                            return False
                        ancestor = ancestor.parentItem()
                    return True

                def visible_text(text):
                    return [{"text": str(item.property("text")), "width": item.width(), "height": item.height()}
                            for item in walk(window.contentItem()) if item.metaObject().indexOfProperty("text") >= 0
                            and text in str(item.property("text") or "") and exposed(item)]

                def show_item(item):
                    viewport = js("qmlapp.globalConfigs.panelComponent.contentItem")
                    require(viewport is not None and viewport.metaObject().indexOfProperty("contentY") >= 0, "真实设置滚动容器不可观测")
                    content = viewport.property("contentItem")
                    point = item.mapToItem(content, QPointF(0, 0))
                    maximum = max(0.0, float(viewport.property("contentHeight")) - viewport.height())
                    viewport.setProperty("contentY", min(maximum, max(0.0, point.y() - viewport.height() * .35)))

                def control_geometry(item):
                    if item is None or not shiboken6.isValid(item):
                        return {"valid": False}
                    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
                    chain, ancestor = [], item
                    while ancestor is not None and len(chain) < 20:
                        local = ancestor.mapFromScene(point)
                        chain.append({"class": ancestor.metaObject().className(), "key": str(ancestor.property("key") or ""),
                                      "visible": ancestor.isVisible(), "enabled": ancestor.isEnabled(), "opacity": ancestor.opacity(), "clip": ancestor.clip(),
                                      "width": ancestor.width(), "height": ancestor.height(), "contains_center": ancestor.boundingRect().contains(local)})
                        ancestor = ancestor.parentItem()
                    return {"valid": True, "identity": identity(item), "center": [point.x(), point.y()], "exposed": exposed(item), "ancestors": chain}

                def click(item, label):
                    ready = exposed(item) and item.isEnabled()
                    if not ready:
                        report.setdefault("unclickable_controls", []).append({"label": label, "geometry": control_geometry(item)})
                    require(ready, "真实控件不可点击：" + label)
                    point = QPointF(item.width() / 2, item.height() / 2)
                    local, global_point = item.mapToScene(point), item.mapToGlobal(point)
                    events = ((QEvent.Type.MouseMove, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton),
                              (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
                              (QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))
                    for kind, button, buttons in events:
                        QCoreApplication.sendEvent(window, QMouseEvent(kind, local, global_point, button, buttons, Qt.KeyboardModifier.NoModifier))
                    report["operation_events"].append({"operation": label, "input": "仅向本QQuickWindow发送QMouseEvent，无系统全局鼠标或键盘", "position": [local.x(), local.y()]})

                def ready_control(key, object_name, label):
                    # 面板重建会复位滚动位置；每轮重新取得实际活动对象，仍只给2500ms可见收敛预算。
                    phase = {"key": key, "object_name": object_name, "label": label, "samples": []}
                    report.setdefault("control_position_samples", []).append(phase)
                    start, last_identity, stable = time.monotonic(), None, 0
                    while True:
                        require(time.monotonic() - start < 2.5, "真实活动控件在2500ms内未可见收敛：" + json.dumps(phase, ensure_ascii=False))
                        try:
                            item = comp(key)
                            original_identity = identity(item)
                            show_item(item)
                        except (AssertionError, RuntimeError) as exc:
                            phase["samples"].append({"ms": round((time.monotonic() - start) * 1000, 2), "error": str(exc)})
                            stable = 0
                            yield 50
                            continue
                        yield 50
                        current = comp(key)
                        control = current.findChild(QObject, object_name)
                        geometry = control_geometry(control)
                        ready = (identity(current) == original_identity and geometry.get("exposed") and control.isEnabled())
                        stable = stable + 1 if ready and identity(current) == last_identity else (1 if ready else 0)
                        last_identity = identity(current)
                        viewport = js("qmlapp.globalConfigs.panelComponent.contentItem")
                        phase["samples"].append({"ms": round((time.monotonic() - start) * 1000, 2), "same_active_object": identity(current) == original_identity,
                                                 "ready": bool(ready), "stable": stable, "contentY": viewport.property("contentY"), "geometry": geometry})
                        if stable >= 3:
                            return current, control

                def capture(label):
                    image = window.grabWindow()
                    require(not image.isNull() and image.width() > 400 and image.height() > 300, "本应用窗口截图为空或尺寸异常")
                    colors = {image.pixelColor(x * (image.width() - 1) // 15, y * (image.height() - 1) // 15).rgba() for x in range(16) for y in range(16)}
                    require(len(colors) >= 5, "本应用窗口截图疑似空白")
                    path = output.with_name(output.stem + "-" + label + ".png")
                    require(not path.exists() and image.save(str(path), "PNG"), "截图保存失败或证据重名")
                    report["screenshots"].append({"path": str(path), "sha256": sha256(path), "width": image.width(), "height": image.height(), "sample_colors": len(colors),
                                                  "capture": "仅QQuickWindow.grabWindow", "language": js("qmlapp.globalConfigs.getValue('ui.i18n')"), "theme": js("qmlapp.globalConfigs.getValue('ui.theme')")})

                def titles():
                    return jjson("qmlapp.globalConfigs.compList.filter(item=>item.title!==undefined).map(item=>({key:item.key,title:item.title}))")

                def layout():
                    return jjson("qmlapp.globalConfigs.buildPanelLayout().map(function visit(item){const source=item.sourceConfigs||qmlapp.globalConfigs;const origin=item.origin||source.originDict[item.sourceKey||item.key]||{};return {key:item.key,title:origin.title,deviceProvider:origin.deviceProvider,items:(item.items||[]).map(visit)}})")

                def rendered_buttons(root):
                    return [str(item.property("text_")) for item in walk(root) if item.metaObject().indexOfProperty("text_") >= 0 and item.metaObject().indexOfProperty("bgPressColor_") >= 0]

                def no_inference():
                    require(not report["safety_blocks"], "产品触发了推理/非授权子进程安全门禁")
                    forbidden = sorted(name for name in sys.modules if name.split(".")[0] in FORBIDDEN_MODULES or name in {PP + ".worker", VL + ".worker"})
                    require(not forbidden, "源GUI进程导入了推理模块：" + str(forbidden))
                    from py_src.plugins_controller.services import PluginServices
                    services = {}
                    for key, entry in PluginServices._entries.items():
                        instance = entry.get("instance")
                        state = instance.get_status() if instance and callable(getattr(instance, "get_status", None)) else {}
                        require(not state.get("pid") and state.get("state") not in {"ready", "busy", "starting", "sleeping"}, "设置切换意外启动共享服务：" + str((key, state)))
                        services["/".join(key)] = state
                    from py_src.mission.mission_ocr import MissionOCR
                    state = MissionOCR._api.get_status() if MissionOCR._api else {}
                    require(state.get("state") not in {"loaded", "warming", "busy"}, "设置切换意外启动 OCR 模型：" + str(state))
                    require(js("qmlapp.globalConfigs.getValue('ocr.lifecycle.warmupMode')") == "lazy" and js("qmlapp.globalConfigs.getValue('ocr.lifecycle.cleanupPolicy')") == "never", "验收期间不得开启预热或自动清理")
                    require(js("qmlapp.globalConfigs.getValue('server.enable')") is False, "本轮必须禁用HTTP")
                    for kind in ("ocr", "document"):
                        require(not jjson("qmlapp.msnConnector.callPy(" + json.dumps(kind) + ",'getMissionListsLength',[])"), "本轮不能运行识别或文档任务")
                    return {"service_states": services, "ocr_state": state, "forbidden_modules": forbidden}

                def provenance():
                    nonlocal active_check
                    active_check = "源码来源"
                    qt_sources = qt_dependency_sources(packages, manifest["dependency_inputs"])
                    modules, origins = {}, set()
                    for name, module in list(sys.modules.items()):
                        origin = getattr(module, "__file__", None)
                        if not origin:
                            continue
                        path = Path(origin).resolve()
                        if name == "py_src" or name.startswith("py_src.") or name in {"umi_log", "umi_about", "plugin_i18n"} or name.split(".")[0] in {PP, VL}:
                            require(path.is_relative_to(data), "应用模块不是当前源沙盒：" + name + " " + origin)
                            modules[name] = str(path)
                    for item in walk(window.contentItem()):
                        context = QQmlEngine.contextForObject(item)
                        if context is None:
                            continue
                        url = context.baseUrl()
                        text = url.toString()
                        if "/qt_res/qml/" in text or "/plugins/" in text:
                            require(url.isLocalFile() and Path(url.toLocalFile()).resolve().is_relative_to(data), "应用QML不是当前磁盘源码：" + text)
                            origins.add(text)
                    require("py_src.run" in modules and any(value.endswith("/Main.qml") for value in origins), "缺少真实入口或主QML的运行来源证据")
                    check("源码来源", modules=modules, qml_origins=sorted(origins), shared_dependencies=str(packages),
                          qt_dependencies=qt_sources, app_zip=False, ui_rcc=False)

                def stable_language(page, code):
                    from py_src.utils.i18n_configs import I18n
                    expected = manifest["translation_expected"][code]["GlobalConfigs"]
                    samples, start = [], time.monotonic()
                    report.setdefault("language_samples", {})[code] = samples
                    while True:
                        left = jjson("groupList", page)
                        panel = jjson("qmlapp.globalConfigs.panelComponent.getGroupList()")
                        left_root = js("leftTop", page)
                        buttons = [{"text": str(item.property("text_")), "visible": item.isVisible(), "width": item.width(), "height": item.height()}
                                   for item in walk(left_root) if item.metaObject().indexOfProperty("text_") >= 0 and item.metaObject().indexOfProperty("bgPressColor_") >= 0]
                        current = {item["key"]: item["title"] for item in titles()}
                        checks = {"plugins.models": "模型设置", "plugins.models.ScreenshotOCR": "截图识别参数", "plugins.models.BatchOCR": "批量图片识别参数", "plugins.models.BatchPDF": "批量文档识别参数"}
                        same = bool(left) and left == panel and [item["text"] for item in buttons] == [item["title"] for item in left]
                        same = same and len({item["key"] for item in layout()}) == len(layout()) and "ocr" not in {item["key"] for item in layout()}
                        translated = js("qmlapp.globalConfigs.originDict['ui'].title") == expected["界面和外观"]
                        translated = translated and all(current.get(key) == expected[source] for key, source in checks.items())
                        advanced = bool(js("qmlapp.globalConfigs.advanced"))
                        visible = [item["visible"] for item in buttons] == [not item["advanced"] or advanced for item in left]
                        sample = {"ms": round((time.monotonic() - start) * 1000, 2), "same_source": same, "translated": translated, "settled": settled() and I18n.langCode == code,
                                  "buttons_match_visibility": visible, "left": left, "panel": panel, "buttons": buttons, "model_titles": {key: current.get(key) for key in checks}}
                        samples.append(sample)
                        if len(samples) >= 3 and all(all(value[field] for field in ("same_source", "translated", "settled", "buttons_match_visibility")) for value in samples[-3:]):
                            return sample
                        require(time.monotonic() - start < 2.5, "活动左栏/面板/新标题在2500ms内未收敛：" + json.dumps(sample, ensure_ascii=False))
                        yield 50

                def refreshed_device(key, code):
                    item, refresh = yield from ready_control(key, "nvidiaDeviceRefresh", code + "-刷新GPU")
                    sequence = js("qmlapp.globalConfigs.cudaDiscoverySequence")
                    click(refresh, code + "-刷新GPU")
                    require(js("qmlapp.globalConfigs.cudaDiscoverySequence") > sequence, "Qt点击没有触发设备刷新")
                    pending = js("discoveryText", item)
                    expected = manifest["translation_expected"][code]["NvidiaDeviceConfig"]
                    require(pending == expected[DEVICE_TEXTS[0]], "真实刷新中状态未采用当前语言：" + str((code, pending)))
                    yield from wait(lambda: not js("qmlapp.globalConfigs.cudaDiscoveryPending"), "真实CUDA设备发现", timeout=12)
                    snapshot = jjson("qmlapp.globalConfigs.cudaDeviceSnapshot")
                    require(snapshot.get("ok") is True and snapshot.get("state") == "ready" and len(snapshot.get("devices", [])) == 1, "没有取得本机唯一真实 NVIDIA 设备：" + str(snapshot))
                    device = snapshot["devices"][0]
                    require(device.get("value") == "gpu:0" and device.get("ordinal") == 0 and re.search(r"NVIDIA\s+GeForce\s+RTX\s*4060\s*Laptop", device.get("name", ""), re.I), "实际显卡与本轮验收机器不符：" + str(device))
                    require(re.fullmatch(r"GPU-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", device.get("uuid", ""), re.I), "设备探测没有返回真实 UUID")
                    require(snapshot.get("message") == manifest["translation_expected"][code]["ready"].format(count=1), "真实设备发现完成状态没有热切运行译文")
                    require(js("discoveryText", item) == "", "设备发现完成后仍残留错误/刷新状态")
                    return snapshot

                def scenario():
                    nonlocal active_check
                    require(window.isVisible() and window.isExposed(), "主窗口没有真实显示")
                    check("首帧", seconds=round(time.monotonic() - started, 3), hwnd=int(window.winId()))
                    yield from wait(settled, "首次轻量配置应用", timeout=12)
                    no_inference()
                    screen = window.screen()
                    report["window"] = {"title": window.title(), "geometry": [window.x(), window.y(), window.width(), window.height()], "device_pixel_ratio": window.devicePixelRatio(),
                                        "logical_dpi": screen.logicalDotsPerInch(), "physical_dpi": screen.physicalDotsPerInch(), "screen": screen.name(), "style": QQuickStyle.name(),
                                        "font": js("theme.fontFamily"), "text_size": js("size_.text"), "system_color_scheme": str(QGuiApplication.styleHints().colorScheme())}
                    active_check = "先开设置的参数来源"
                    before_pages = jjson("qmlapp.tab.openPageList")
                    require(not any(key in before_pages for key, _ in TASKS), "前置条件不满足：任务页已先于设置页打开")
                    global_page = activate("GlobalConfigsPage")
                    yield 100
                    yield from wait(settled, "打开全局设置", timeout=12)
                    sources = {category: js("qmlapp.globalConfigs.ocrManager.taskSource(" + json.dumps(category) + ")") for _, category in TASKS}
                    require(sorted(jjson("Object.keys(qmlapp.globalConfigs.ocrManager.taskSources)")) == sorted(sources), "没有建立三个任务规范来源")
                    identities = {category: identity(source) for category, source in sources.items()}
                    check("先开设置的参数来源", prior_pages=before_pages, source_identity=identities)
                    active_check = "活动布局与插件末尾GPU"
                    current_layout = layout()
                    keys = [item["key"] for item in current_layout]
                    require("ocr" not in keys and "pluginServices" not in keys, "旧顶层文字识别/服务导航仍存在")
                    plugins = next(item for item in current_layout if item["key"] == "plugins")
                    expected_order = ["plugins.btns", "plugins.models", "plugins." + PP, "plugins." + VL]
                    require([item["key"] for item in plugins["items"]] == expected_order, "插件管理没有按操作→模型设置→PP→VL排序")
                    gpu_keys = ("ocr." + PP + ".device", "document." + VL + ".pipeline.cudaDevice")
                    live_children = {}
                    for plugin_id, gpu_key in zip((PP, VL), gpu_keys):
                        group = next(item for item in plugins["items"] if item["key"] == "plugins." + plugin_id)
                        require(group["items"][-1]["key"] == gpu_key and group["items"][-1]["deviceProvider"] == "nvidia-cuda", "GPU不在所属插件布局末尾")
                        plugin_comp = comp("plugins." + plugin_id)
                        # 直接在真实QML视觉容器枚举，避免PySide未公开QQuickColumn*转换器。
                        children = jjson("container.children.filter(item=>item.key!==undefined).map(item=>item.key)", plugin_comp)
                        require(children[-1] == gpu_key, "GPU不在所属插件真实组件树末尾：" + str(children))
                        live_children[plugin_id] = children
                    check("活动布局与插件末尾GPU", layout=current_layout, live_plugin_children=live_children)
                    active_check = "实际安装模型枚举"
                    states = jjson("qmlapp.globalConfigs.pluginStates")
                    require({item["id"] for item in states} == {PP, VL} and all(item["state"] == "ready" for item in states), "轻量源码插件没有完成真实注册：" + str(states))
                    options = jjson("qmlapp.globalConfigs.originDict['ocr.api'].optionsList")
                    require([item[0] for item in options] == [PP, VL], "模型列表虚构、遗漏或排序不正确：" + str(options))
                    require([item[1] for item in options] == ["PP-OCRv6_medium", "PaddleOCR-VL1.6"], "模型名称没有使用真实声明")
                    check("实际安装模型枚举", states=states, options=options, health_or_inference_verified=False)
                    show_item(comp("plugins.models"))
                    yield 100
                    require(visible_text("模型设置"), "中央模型设置标题在真实窗口不可见")
                    capture("中央模型设置")
                    mutations = {}
                    for page_key, category in TASKS:
                        active_check = "任务来源." + page_key
                        page = activate(page_key)
                        yield 100
                        require(page.isVisible(), "真实任务页没有显示：" + page_key)
                        require(identity(js("configsComp.valueSources.ocr", page)) == identities[category], "任务页没有引用同一个规范来源")
                        require(not js("configsComp.compList.some(item=>item.key==='ocr'||item.key.startsWith('ocr.'))", page), "任务页仍有重复模型控件")
                        require(not js("Object.keys(configsComp.originDict).some(key=>key==='ocr'||key.startsWith('ocr.'))", page), "任务页产生了第二份OCR规范参数")
                        source_values = jjson("getValueDict()", sources[category])
                        values = jjson("getValueDict()", page)
                        require(source_values and all(values.get(key) == value for key, value in source_values.items()), "真实任务快照丢失canonical ocr.*参数")
                        require(not any(key == "ocr.api" or key.startswith("ocr.lifecycle.") for key in values), "任务快照混入全局共享模型设置")
                        mutation_key = "ocr.docOrientation"
                        require(type(source_values.get(mutation_key)) is bool, "本轮PP真实任务参数前提不符")
                        mutation = not source_values[mutation_key]
                        js("setValue(" + json.dumps(mutation_key) + "," + json.dumps(mutation) + ",true)", sources[category])
                        require(jjson("getValueDict()", page)[mutation_key] == mutation, "任务快照未同步来源新值")
                        js("closePage()", page)
                        yield 100
                        require(shiboken6.isValid(sources[category]), "关闭任务页销毁了应用级来源")
                        reopened = activate(page_key)
                        yield 100
                        require(identity(js("configsComp.valueSources.ocr", reopened)) == identities[category] and jjson("getValueDict()", reopened)[mutation_key] == mutation, "重新打开任务页丢失同一来源或值")
                        mutations[category] = {"key": mutation_key, "value": mutation}
                        check(active_check, category=category, source_identity=identities[category], snapshot_keys=sorted(values), mutation=mutations[category], closed_and_reopened=True)
                    activate("GlobalConfigsPage")
                    yield 100
                    active_check = "共享模型与生命周期"
                    document_buttons = jjson("(qmlapp.globalConfigs.originDict['document.btns']||{}).btnsList.map(item=>item.text)")
                    for key, value in (("ocr.lifecycle.warmupDelayMinutes", 17), ("ocr.lifecycle.idleCleanupMinutes", 37)):
                        set_global(key, value)
                        require(js("qmlapp.globalConfigs.getValue(" + json.dumps(key) + ")") == value, "中央生命周期控件没有写入同一Global规范值")
                    switch_records = []
                    for selected in (VL, PP):
                        set_global("ocr.api", selected)
                        yield from wait(lambda: settled() and js("qmlapp.globalConfigs.ocrManager.apiKey") == selected, "PP/VL轻量模型切换", timeout=12)
                        require(js("qmlapp.globalConfigs.getValue('ocr.api')") == selected, "实际后端与Global模型选择分离")
                        require(all(identity(js("qmlapp.globalConfigs.ocrManager.taskSource(" + json.dumps(category) + ")")) == identities[category] for category in sources), "模型切换替换了规范来源对象")
                        require(js("qmlapp.globalConfigs.getValue('ocr.lifecycle.warmupDelayMinutes')") == 17 and js("qmlapp.globalConfigs.getValue('ocr.lifecycle.idleCleanupMinutes')") == 37, "模型切换没有共享生命周期值")
                        service_key = "pluginServices." + VL + ".paddlevl.btns"
                        action_text = jjson("qmlapp.globalConfigs.originDict[" + json.dumps(service_key) + "].btnsList.map(item=>item.text)")
                        # 后端应用完成和Qt.callLater面板重建不是同一个信号；按实际活动树限时收敛。
                        panel_samples = []
                        report.setdefault("model_switch_panel_samples", {})[selected] = panel_samples
                        panel_start = time.monotonic()
                        while True:
                            model_group = next(item for item in next(entry for entry in layout() if entry["key"] == "plugins")["items"] if item["key"] == "plugins.models")
                            desired_fallback = any(item["key"] == "ocr.btns" for item in model_group["items"])
                            rendered_fallback = any(item["key"] == "ocr.btns" for item in titles())
                            contract = jjson("(function(){const manager=qmlapp.globalConfigs.ocrManager;const refs=manager.serviceRefs[manager.apiKey];return {apiKey:manager.apiKey,serviceRefs:manager.serviceRefs,currentRefs:refs,serviceRefsType:typeof manager.serviceRefs,currentRefsType:typeof refs,refsIsArray:Array.isArray(refs),refsLength:refs&&refs.length!==undefined?refs.length:null,refsTag:Object.prototype.toString.call(refs),usesSharedService:manager.usesSharedService()}})()")
                            sample = {"ms": round((time.monotonic() - panel_start) * 1000, 2), "layout_has_fallback": desired_fallback, "active_tree_has_fallback": rendered_fallback,
                                      "selected": js("qmlapp.globalConfigs.getValue('ocr.api')"), "backend": js("qmlapp.globalConfigs.ocrManager.apiKey"), "service_contract": contract}
                            panel_samples.append(sample)
                            if desired_fallback == rendered_fallback == (selected == PP):
                                break
                            require(time.monotonic() - panel_start < 2.5, "实际模型面板在2500ms内未跟随共享服务切换：" + json.dumps(panel_samples, ensure_ascii=False))
                            yield 50
                        if selected == VL:
                            require(action_text == ["检查服务", "预启动服务", "终止文字识别任务"], "当前OCR共享服务的终止按钮没有紧随预启动")
                            require(rendered_buttons(comp(service_key)) == action_text, "共享服务真实按钮与当前操作数据不一致")
                            require(not any(item["key"] == "ocr.btns" for item in titles()), "共享服务下仍显示重复中央兜底按钮")
                        else:
                            require(action_text == ["检查服务", "预启动服务"], "非当前OCR服务仍有终止OCR按钮")
                            require(rendered_buttons(comp("ocr.btns")) == ["预热当前模型", "终止文字识别任务"], "PP无共享服务时缺少中央终止兜底按钮")
                        require(jjson("(qmlapp.globalConfigs.originDict['document.btns']||{}).btnsList.map(item=>item.text)") == document_buttons, "OCR模型切换扩大了Document取消按钮范围")
                        switch_records.append({"selected": selected, "shared_service_buttons": action_text, "safety": no_inference()})
                    require(all(js("getValue('ocr.docOrientation')", sources[category]) == mutations[category]["value"] for category in sources), "PP切回后任务参数丢失")
                    check("共享模型与生命周期", switches=switch_records, shared_values={"warmupMode": "lazy", "cleanupPolicy": "never", "warmupDelayMinutes": 17, "idleCleanupMinutes": 37})
                    check("OCR终止范围", switches=switch_records, document_buttons_unchanged=document_buttons, no_action_buttons_invoked=True)
                    active_check = "插件禁用与恢复"
                    pp_before = jjson("qmlapp.globalConfigs.getValueDict()")
                    set_global("plugins.enable_" + VL, False)
                    yield from wait(lambda: settled() and any(item["id"] == VL and item["state"] == "disabled" for item in jjson("qmlapp.globalConfigs.pluginStates")), "禁用VL轻量刷新", timeout=12)
                    disabled = next(item for item in layout() if item["key"] == "plugins")
                    vl_group = next(item for item in disabled["items"] if item["key"] == "plugins." + VL)
                    require([item["key"] for item in vl_group["items"]] == ["plugins.enable_" + VL], "禁用VL后未隐藏参数或启用开关丢失")
                    require([item[0] for item in jjson("qmlapp.globalConfigs.originDict['ocr.api'].optionsList")] == [PP], "禁用插件仍列为可用模型")
                    require(js("qmlapp.globalConfigs.getValue('ocr.api')") == PP, "禁用VL影响PP选择")
                    set_global("plugins.enable_" + VL, True)
                    yield from wait(lambda: settled() and any(item["id"] == VL and item["state"] == "ready" for item in jjson("qmlapp.globalConfigs.pluginStates")), "恢复VL轻量刷新", timeout=12)
                    require(comp(gpu_keys[1]) is not None, "恢复VL后GPU参数未恢复")
                    pp_after = jjson("qmlapp.globalConfigs.getValueDict()")
                    require(all(pp_after.get(key) == value for key, value in pp_before.items() if key.startswith("ocr." + PP + ".")), "禁用/恢复VL修改了PP设置")
                    check("插件禁用与恢复", disabled_layout=disabled, restored_states=jjson("qmlapp.globalConfigs.pluginStates"), pp_unchanged=True)
                    active_check = "GPU真实点击"
                    snapshots, selection_events = {}, []
                    for plugin_id, gpu_key, label in zip((PP, VL), gpu_keys, ("GPU下拉-PP插件末尾", "GPU下拉-VL插件末尾")):
                        snapshot = yield from refreshed_device(gpu_key, "zh_CN")
                        item = comp(gpu_key)
                        combo = item.findChild(QObject, "nvidiaDeviceCombo")
                        require(combo is not None, "GPU字段不是新的真实ComboBox")
                        options = jjson("deviceOptions", item)
                        available = [index for index, value in enumerate(options) if value.get("available")]
                        require(len(available) == 1 and options[available[0]]["value"] == "gpu:0", "GPU下拉没有且仅有真实有效项")
                        observed = []
                        combo.activated.connect(observed.append)
                        click(combo, plugin_id + "-打开GPU下拉")
                        yield from wait(lambda: bool(js("popup.visible", combo)), "打开真实GPU下拉")
                        yield 50
                        capture(label)
                        delegate = js("popup.contentItem.itemAtIndex(" + str(available[0]) + ")", combo)
                        require(delegate is not None, "真实GPU下拉委托未创建")
                        click(delegate, plugin_id + "-选择唯一真实GPU")
                        yield 50
                        require(observed == available and not js("popup.visible", combo), "QQuickWindow事件未激活/关闭真实下拉项")
                        require(js("qmlapp.globalConfigs.getValue(" + json.dumps(gpu_key) + ")") == "gpu:0", "GPU选择没有保留字符串canonical gpu:N")
                        expected_text = "GPU:0 · " + snapshot["devices"][0]["name"]
                        require(str(combo.property("currentText")) == expected_text, "GPU控件没有展示真实名称")
                        snapshots[plugin_id] = snapshot
                        selection_events.append({"plugin": plugin_id, "activated": observed, "saved": "gpu:0", "display": expected_text})
                    check("GPU真实点击", snapshots=snapshots, selections=selection_events, synthetic_probe_results=False)
                    for code in LANGUAGES:
                        active_check = "热切语言." + code
                        if js("qmlapp.globalConfigs.getValue('ui.i18n')") != code:
                            set_global("ui.i18n", code)
                        stable = yield from stable_language(global_page, code)
                        translated = manifest["translation_expected"][code]
                        for context, messages in (("GlobalConfigs", GLOBAL_TITLES), ("NvidiaDeviceConfig", DEVICE_TEXTS)):
                            for source in messages:
                                expected = translated[context][source]
                                require(bool(expected) and QCoreApplication.translate(context, source) == expected, "实际QM不是本轮目标语言译文：" + str((code, context, source)))
                                if code not in {"zh_CN", "en_US"}:
                                    require(expected != manifest["translation_expected"]["en_US"][context][source], "不能把英文回退当目标语言翻译")
                        for key, source in (("plugins.models", "模型设置"), ("plugins.models.ScreenshotOCR", "截图识别参数"), ("plugins.models.BatchOCR", "批量图片识别参数"), ("plugins.models.BatchPDF", "批量文档识别参数")):
                            show_item(comp(key))
                            yield 30
                            require(visible_text(translated["GlobalConfigs"][source]), "当前语言新标题没有在实际面板展示：" + str((code, source)))
                        snapshot = yield from refreshed_device(gpu_keys[0], code)
                        require(comp(gpu_keys[0]).property("title") == translated["pp_device"] and comp(gpu_keys[1]).property("title") == translated["vl_device"], "所属插件GPU标题没有真实热切")
                        check(active_check, stable_sidebar=stable, device_snapshot=snapshot, actual_pending_and_ready=True,
                              error_states_scope="无设备/驱动缺失/超时/失败/已保存不可用仅核对当前真实QM译文；未伪造硬件状态或声称这些错误已现场触发")
                    set_global("ui.i18n", "zh_CN")
                    yield from stable_language(global_page, "zh_CN")
                    active_check = "无推理与进程回收"
                    yield from wait(lambda: not js("qmlapp.globalConfigs.cudaDiscoveryPending") and not cuda_device_probe._INFLIGHT, "设备发现正常回收", timeout=12)
                    safety = no_inference()
                    require(all(process.poll() is not None for process in processes), "本次设备探测子进程尚未回收")
                    remaining = psutil.Process(os.getpid()).children(recursive=True)
                    require(not remaining, "本次GUI仍有子进程存活：" + str(remaining))
                    listeners = [connection._asdict() for connection in psutil.Process(os.getpid()).net_connections(kind="inet") if connection.status == psutil.CONN_LISTEN]
                    require(not listeners, "HTTP禁用情况下GUI仍监听网络端口：" + str(listeners))
                    check("无推理与进程回收", **safety, probes=[{"pid": process.pid, "returncode": process.returncode} for process in processes], remaining_children=[], listeners=[])
                    provenance()
                    active_check = "输入未变化"
                    differences = {field: changed_inputs(manifest[field]) for field in ("source_inputs", "snapshot_inputs", "dependency_inputs", "driver_inputs")}
                    require(not any(differences.values()), "运行期间产品/翻译/驱动输入变化，拒绝冻结PASS：" + json.dumps(differences, ensure_ascii=False))
                    check("输入未变化", differences=differences)
                    report["scenario_completed"] = True

                def begin():
                    if self.begun or self.finished:
                        return
                    self.begun = True
                    self.steps = scenario()
                    scheduler.start_steps(self.steps, QTimer.singleShot, lambda: finish(), finish)

                available = window.screen().availableGeometry()
                window.setWidth(min(1300, max(800, available.width() - 80)))
                window.setHeight(min(960, max(650, available.height() - 100)))
                window.frameSwapped.connect(lambda: QTimer.singleShot(0, begin) if not self.begun else None)
                window.show()
                QTimer.singleShot(15000, lambda: finish(AssertionError("没有收到真实窗口首帧")) if not self.begun else None)
                QTimer.singleShot(180000, lambda: finish(AssertionError("本轮源GUI场景超过有限总预算")) if not self.finished else None)

        QtQml.QQmlApplicationEngine = Engine
        from py_src.run import main as run_application
        sys.argv = [str(sandbox / "Umi-OCR.exe"), "--force"]
        try:
            run_application(str(sandbox / "Umi-OCR.exe"), str(packages / "PySide6/qml"))
        except SystemExit as exc:
            require(exc.code in (None, 0), "真实源程序非正常退出：" + str(exc.code))
        report["normal_exit"] = bool(engines and all(engine.finished for engine in engines))
    except Exception as exc:
        report["errors"].append("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    finally:
        try:
            # 失败路径也等待本次可信发现自然完成；不终止任何既有或其它进程。
            if "cuda_device_probe" in locals():
                with cuda_device_probe._CACHE_LOCK:
                    pending_probes = list(cuda_device_probe._INFLIGHT.values())
                for future in pending_probes:
                    future.result(timeout=12)
            for process in processes:
                process.wait(timeout=12)
            report["probe_cleanup"] = [{"pid": process.pid, "returncode": process.returncode} for process in processes]
            if previous_engine is not None:
                QtQml.QQmlApplicationEngine = previous_engine
            if previous_installer is not None:
                QtCore.qInstallMessageHandler = previous_installer
            if previous_popen is not None:
                subprocess.Popen = previous_popen
            if finder is not None and finder in sys.meta_path:
                sys.meta_path.remove(finder)
            if "QApplication" in locals():
                app = QApplication.instance()
                if app is not None:
                    for engine in engines:
                        engine.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    shiboken6.delete(app)
            if any(process.poll() is None for process in processes):
                report["errors"].append("本次设备发现子进程未正常回收；未操作其它现有进程")
            all_qt_candidates = report.get("qt_messages", []) + report.get("qt_problems_after_debug_budget", [])
            qt_failures = [message for message in all_qt_candidates if "QtCriticalMsg" in message["type"] or "QtFatalMsg" in message["type"] or
                           ("QtWarningMsg" in message["type"] and re.search(r"(?:ReferenceError|TypeError|Error:|Unable to assign|Cannot assign|is not a type|is not defined)", message["text"]))]
            if qt_failures:
                report["errors"].append("真实QML运行警告/错误：" + json.dumps(qt_failures, ensure_ascii=False))
            if report.get("qt_problem_overflow"):
                report["errors"].append("Qt警告/错误超过有限观测预算，不能据不完整记录宣告通过：" + str(report["qt_problem_overflow"]))
        except Exception as exc:
            report["errors"].append("原生场景退出收尾失败：" + repr(exc))
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["acceptance"] = acceptance(report)
        report["retained"] = ["源沙盒及精确输入清单", "沙盒内配置/日志/临时文件", "本轮JSON原始结果与本应用PNG截图"]
        report["cleanup"] = "未删除或替换任何已有目录，未改动 release 或插件源项目；本轮复现输入及原始证据完整保留"
        write_json_new(output, report)
        print(json.dumps({"output": str(output), "acceptance": report["acceptance"], "errors": report["errors"], "screenshots": report["screenshots"]}, ensure_ascii=False))
    return 0 if report["acceptance"]["complete"] else 2


def self_check():
    """只检查驱动门禁的纯逻辑；不能作为原生GUI验收。"""
    python, code, bootstrap = Path("D:/trusted/runtime/python.exe"), Path("D:/trusted/source"), "可信设备发现代码"
    argv = [str(python), "-I", "-B", "-X", "utf8", "-u", "-c", bootstrap, str(code)]
    require(trusted_probe(str(python), argv, str(code), python, code, bootstrap), "可信探测契约被拒绝")
    require(trusted_probe(None, argv, str(code), python, code, bootstrap), "Windows默认executable构造参数被误拒")
    require(not trusted_probe(None, None, str(code), python, code, bootstrap), "无argv不能通过可信门禁")
    if os.name == "nt":
        import subprocess
        command_line = subprocess.list2cmdline(argv)
        require(trusted_probe(None, command_line, str(code), python, code, bootstrap), "Windows真实审计形态被误拒")
        require(not trusted_probe(None, command_line + " --其它动作", str(code), python, code, bootstrap), "Windows审计命令行接受了附加参数")
        require(not trusted_probe(None, command_line.replace(bootstrap, "模型启动代码"), str(code), python, code, bootstrap), "Windows审计命令行接受了替换bootstrap")
        require(not trusted_probe("D:/other/python.exe", command_line, str(code), python, code, bootstrap), "Windows审计接受了替换解释器")
    require(checked_sandbox(REPO / "build/tmp/settings-gpu-20261027-guard") == REPO / "build/tmp/settings-gpu-20261027-guard", "build/tmp路径守卫误拒")
    require(checked_sandbox(REPO / "build/staging/settings-gpu-20261027-guard") == REPO / "build/staging/settings-gpu-20261027-guard", "build/staging路径守卫误拒")
    rejected_top_level = False
    try:
        checked_sandbox(REPO / "staging/settings-gpu-20261027-guard")
    except AssertionError:
        rejected_top_level = True
    require(rejected_top_level, "不得允许项目顶层staging作为本轮沙盒")
    for executable, changed, cwd in ((str(python), argv[:-1] + ["D:/旧代码"], str(code)),
                                     (str(python), argv[:-2] + ["模型启动代码", str(code)], str(code)),
                                     ("D:/other/python.exe", argv, str(code)), (str(python), argv, "D:/其它目录")):
        require(not trusted_probe(executable, changed, cwd, python, code, bootstrap), "安全门禁接受了非授权子进程")
    incomplete = {"checks": {key: {"status": "PASS"} for key in CHECKS}, "normal_exit": True, "scenario_completed": False, "errors": [], "screenshots": [1, 2]}
    require(not acceptance(incomplete)["complete"], "未完成场景不能宣告PASS")
    print(json.dumps({"status": "驱动纯逻辑检查完成", "driver_sha256": sha256(__file__), "windows_audit_shapes_checked": os.name == "nt",
                      "sandbox_guards_checked": ["build/tmp", "build/staging", "拒绝顶层staging"], "qt_imported": "PySide6" in sys.modules,
                      "window_created": False, "native_acceptance": "NOT_RUN"}, ensure_ascii=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prep = subparsers.add_parser("prepare", help="只准备全新源沙盒与输入清单，不导入Qt")
    prep.add_argument("--source-root", type=Path, default=REPO)
    prep.add_argument("--vl-root", type=Path, default=DEFAULT_VL)
    prep.add_argument("--runtime-data", type=Path, default=DEFAULT_RUNTIME)
    prep.add_argument("--sandbox", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    run = subparsers.add_parser("run", help="仅在主线程批准执行后运行真实Qt源窗口")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--execute-authorized", action="store_true", help="声明已经收到本轮主线程“可以执行”，不是自行授权")
    subparsers.add_parser("self-check", help="只运行纯逻辑安全门禁检查，不加载GUI")
    args = parser.parse_args(argv)
    return prepare(args) if args.command == "prepare" else run_native(args) if args.command == "run" else self_check()


if __name__ == "__main__":
    raise SystemExit(main())
