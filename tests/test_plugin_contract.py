"""插件契约 v2 回归测试。

不依赖 PySide6 、不依赖任何 OCR 后端，可用仓库源码树或发布包的
可移植 Python 直接运行：

    python tests/test_plugin_contract.py

覆盖点：
- 版本范围与平台/架构匹配
- 清单校验的每一类失败原因
- 【发现阶段不导入插件 Python】这条关键性质
- 一般旧版 PluginInfo 插件的零改动兼容
- 应用 3.0 的三个已知旧实现：在 import / mountRuntime 前拒绝，3.x 更新可用
- 能力惰性解析（用到才 import）
- 冲突互斥、禁用、未知能力类型、健康检查
- 插件页控制器可被注册并实例化（契约 v1 做不到）
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "UmiOCR-data"
sys.path.insert(0, str(DATA_ROOT))
sys.path.insert(0, str(DATA_ROOT / "py_src" / "imports"))

from py_src.plugins_controller import host_api, manifest as manifest_mod  # noqa: E402
from py_src.plugins_controller import plugins_controller as controller_mod  # noqa: E402
from py_src.plugins_controller.capabilities import (  # noqa: E402
    getCapabilityRegistry,
    loadBuiltinCapabilityTypes,
)
from py_src.plugins_controller.services import PluginServices  # noqa: E402
from py_src.ocr.score import averageScore  # noqa: E402
from py_src.tag_pages import page_registry  # noqa: E402

FAILURES = []


def check(condition, label):
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        FAILURES.append(label)


# ========================= 版本与平台匹配 =========================


def test_version_range():
    print("test_version_range")
    m = host_api.matchVersionRange
    check(m("2.7", ">=2.7,<3.0"), "2.7 满足 >=2.7,<3.0")
    check(m("2.7.5", ">=2.7,<3.0"), "2.7.5 满足 >=2.7,<3.0")
    check(not m("2.6", ">=2.7,<3.0"), "2.6 不满足 >=2.7")
    check(not m("3.0", ">=2.7,<3.0"), "3.0 不满足 <3.0")
    check(m("2.7", "*"), "* 匹配任意版本")
    check(m("2.7", ""), "空范围匹配任意版本")
    check(m("2.7", "2.7"), "裸版本号等价于 ==")
    check(not m("2.7", "2.8"), "裸版本号不等则不匹配")
    check(not m("2.7", ">="), "语法非法的范围判为不匹配")
    check(host_api.parseVersion("1.2") == (1, 2, 0), "版本号补零")
    check(host_api.parseVersion("2.7.0-beta1") == (2, 7, 0), "忽略预发布后缀")

    t = host_api.matchTokenList
    check(t("win32", []), "空列表 = 不限制")
    check(t("win32", ["win32", "linux"]), "平台命中")
    check(not t("linux", ["win32"]), "平台不命中")
    check(t("arm64", ["*"]), "* 通配")


# ========================= 清单校验 =========================


def _writeManifest(pluginDir, data):
    pluginDir.mkdir(parents=True, exist_ok=True)
    (pluginDir / host_api.MANIFEST_NAME).write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def _validManifest(pluginId):
    return {
        "schema_version": 1,
        "id": pluginId,
        "name": pluginId,
        "version": "1.0.0",
        "host_api": ">=2.7,<3.0",
        "platform": ["*"],
        "arch": ["*"],
        "capabilities": [{"type": "ocr", "entry": ":Api", "config": "config:CONFIG"}],
    }


def test_manifest_validation(tmp):
    print("test_manifest_validation")
    cases = [
        ("schema", {"schema_version": 99}, "schema_version"),
        ("noid", {"id": ""}, "缺少 id"),
        ("mismatch", {"id": "other"}, "不一致"),
        ("nover", {"version": ""}, "缺少 version"),
        ("nocap", {"capabilities": []}, "capabilities"),
        ("badentry", {"capabilities": [{"type": "ocr", "entry": "Api"}]}, "分隔符"),
        ("notype", {"capabilities": [{"entry": ":Api"}]}, "缺少 type"),
        ("badprio", {"runtime": {"priority": "middle"}}, "priority"),
    ]
    for name, patch, expect in cases:
        pluginId = f"case_{name}"
        data = _validManifest(pluginId)
        data.update(patch)
        pluginDir = tmp / pluginId
        _writeManifest(pluginDir, data)
        result, err = manifest_mod.loadManifest(pluginId, str(pluginDir))
        check(result is None and expect in err, f"{name} 被拒绝并说明原因（{err[:40]}）")

    pluginId = "case_good"
    pluginDir = tmp / pluginId
    _writeManifest(pluginDir, _validManifest(pluginId))
    result, err = manifest_mod.loadManifest(pluginId, str(pluginDir))
    check(result is not None and not err, "合法清单通过校验")
    check(result.capabilityTypes() == ["ocr"], "能力类型解析正确")
    check(result.capabilities[0].entry.moduleName(pluginId) == pluginId, "空模块=包根")

    pluginId = "case_page_missing_qml"
    pluginDir = tmp / pluginId
    data = _validManifest(pluginId)
    data["pages"] = [{"key": "P", "qml": "NotThere.qml"}]
    _writeManifest(pluginDir, data)
    result, err = manifest_mod.loadManifest(pluginId, str(pluginDir))
    check(result is None and "qml" in err, "页面 qml 缺失被拒绝")

    pluginId = "case_missing_service_ref"
    pluginDir = tmp / pluginId
    data = _validManifest(pluginId)
    data["capabilities"][0]["meta"] = {"serviceRefs": ["not-declared"]}
    _writeManifest(pluginDir, data)
    result, err = manifest_mod.loadManifest(pluginId, str(pluginDir))
    check(result is None and "未声明的服务" in err, "未声明的 serviceRefs 被拒绝")

    pluginId = "case_duplicate_service"
    pluginDir = tmp / pluginId
    data = _validManifest(pluginId)
    data["services"] = [
        {"id": "shared", "entry": "runtime:getService"},
        {"id": "shared", "entry": "runtime:getService"},
    ]
    _writeManifest(pluginDir, data)
    result, err = manifest_mod.loadManifest(pluginId, str(pluginDir))
    check(result is None and "重复" in err, "重复服务 id 被拒绝")


def test_compatibility():
    print("test_compatibility")
    m = manifest_mod.PluginManifest("x", "/tmp/x")
    m.hostApi = ">=3.0"
    reason = manifest_mod.checkCompatibility(m, "2.7", "win32", "x86_64")
    check("宿主 API" in reason and "3.0" in reason, "宿主 API 不兼容有可读原因")
    m.hostApi = "*"
    m.platforms = ["linux"]
    reason = manifest_mod.checkCompatibility(m, "2.7", "win32", "x86_64")
    check("平台" in reason, "平台不兼容有可读原因")
    m.platforms = ["*"]
    m.arches = ["arm64"]
    reason = manifest_mod.checkCompatibility(m, "2.7", "win32", "x86_64")
    check("架构" in reason, "架构不兼容有可读原因")
    m.arches = ["*"]
    check(manifest_mod.checkCompatibility(m, "2.7", "win32", "x86_64") == "", "全通过")


def test_nullable_scores():
    print("test_nullable_scores")
    check(averageScore([{"score": None}, {"score": None}]) is None, "全空置信度保持 null")
    check(averageScore([{"score": 0.8}, {"score": None}, {"score": 1.0}]) == 0.9, "仅聚合数值置信度")
    check(averageScore([{"score": float("nan")}, {"score": True}]) is None, "NaN 与布尔值不计入置信度")


# ========================= 端到端 =========================

PLUGIN_V2 = '''
IMPORTED = True


class Api:
    def __init__(self, argd):
        self.argd = argd
'''

PLUGIN_INIT_LIGHT = '''
IMPORTED = True
'''

PLUGIN_API_HEAVY = '''
class Api:
    def __init__(self, argd):
        self.argd = argd
'''

PLUGIN_V2_CONFIG = '''
CONFIG = {
    "global_options": {"title": "V2 Plugin", "type": "group"},
    "local_options": {"title": "V2 Local", "type": "group"},
}
'''

PLUGIN_V2_HEALTH = '''
def check():
    return {"ok": True, "message": "healthy", "details": {"probe": 1}}
'''

PLUGIN_LEGACY = '''
class Api:
    def __init__(self, argd):
        self.argd = argd


PluginInfo = {
    "group": "ocr",
    "global_options": {"title": "Legacy", "type": "group"},
    "local_options": {"title": "Legacy Local", "type": "group"},
    "api_class": Api,
}
'''

PLUGIN_DOC = '''
class Api:
    def __init__(self, argd):
        self.argd = argd


class DocPage:
    def __init__(self, ctrlKey, connector):
        self.ctrlKey = ctrlKey
        self.connector = connector
'''

PLUGIN_DOC_CONFIG = '''
CONFIG = {"title": "Doc Local", "type": "group"}
'''

PLUGIN_SHARED_RUNTIME = '''
class SharedService:
    def __init__(self):
        self.values = {}
        self.closed = False
    def configure(self, values):
        self.values = dict(values)
        return {"ok": True, "message": "configured", "details": {}}
    def health(self, values=None):
        return {"ok": True, "message": "healthy", "details": {"values": dict(self.values)}}
    def shutdown_owned(self):
        self.closed = True

def getService():
    return SharedService()
'''

PLUGIN_SHARED_API = '''
class Api:
    def __init__(self, argd):
        self.argd = argd
'''


def _makePlugin(root, pluginId, files, manifestData=None):
    pluginDir = root / pluginId
    pluginDir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (pluginDir / name).write_text(content, encoding="utf-8")
    if manifestData is not None:
        _writeManifest(pluginDir, manifestData)
    return pluginDir


def _checkMigrationCase(root, pluginId, version, expected, capType="ocr", hostApi=">=2.7,<3.0"):
    """Use a disk sentinel: even a failed import leaves evidence of execution."""
    sentinel = (
        "from pathlib import Path\n"
        "Path(__file__).with_name('imported.sentinel').write_text('imported', encoding='utf-8')\n"
    )
    data = None
    if version is None:
        source = PLUGIN_LEGACY.replace('"group": "ocr"', f'"group": "{capType}"')
    else:
        source = PLUGIN_V2
        data = _validManifest(pluginId)
        data.update(name="Migration test metadata", version=version, host_api=hostApi)
        data["capabilities"][0]["type"] = capType
    pluginDir = _makePlugin(
        root, pluginId,
        {"__init__.py": sentinel + source, "config.py": PLUGIN_V2_CONFIG}, data,
    )
    marker = pluginDir / "imported.sentinel"
    if expected == "disabled":
        (root / controller_mod.PLUGINS_STATE_FILE).write_text(
            json.dumps({pluginId: False}), encoding="utf-8"
        )
    label = f"{pluginId} / {version if version is not None else 'legacy'} / {expected}"
    controller = controller_mod._PluginsControllerClass()
    # Repeated cases reuse the known ids but never reuse previously imported code.
    for name in list(sys.modules):
        if name == pluginId or name.startswith(pluginId + "."):
            del sys.modules[name]
    try:
        with patch.object(controller_mod, "PLUGINS_PATH", str(root)), patch.object(
            controller, "_mountRuntime", wraps=controller._mountRuntime
        ) as mount:
            summary = controller.init()
            state = next(item for item in summary["plugins"] if item["id"] == pluginId)
            check(state["state"] == expected, f"{label} 状态正确")
            registry = getCapabilityRegistry(capType)
            if expected == "ready":
                apiClass, err = registry.resolve(pluginId)
                check(apiClass is not None and not err, f"{label} 能力可解析")
                # Legacy discovery mounts its runtime to read PluginInfo;
                # activation repeats the existing idempotent mount operation.
                expected_mounts = 2 if version is None else 1
                check(marker.exists() and mount.call_count == expected_mounts, f"{label} 正常激活并执行导入")
                if apiClass:
                    check(apiClass({"probe": 1}).argd == {"probe": 1}, f"{label} 接入原能力合约")
                check(state["legacy"] == (version is None), f"{label} legacy 标记保持原语义")
            else:
                check(not marker.exists(), f"{label} 导入副作用未发生")
                check(mount.call_count == 0, f"{label} runtime 未挂载")
                check(pluginId not in sys.modules, f"{label} 插件包未导入")
                check(pluginId not in registry.keys(), f"{label} 能力未注册")
                if expected == "incompatible" and hostApi != ">=99.0":
                    message = state["message"]
                    check(
                        pluginId in message and "3.0.0" in message and "技术迁移" in message,
                        f"{label} 有明确技术迁移提示",
                    )
                if version and expected in ("disabled", "incompatible"):
                    check(
                        state["name"] == "Migration test metadata" and state["version"] == version
                        and state["capabilities"] == [capType],
                        f"{label} 清单 metadata 仍可显示",
                    )
            check(summary["host"]["hostApiVersion"] == "2.8", f"{label} Host API 仍是 2.8")
    finally:
        for name in list(sys.modules):
            if name == pluginId or name.startswith(pluginId + "."):
                del sys.modules[name]
        sys.path[:] = [item for item in sys.path if item != str(root)]
        PluginServices.reset()


def test_app3_known_plugin_migration(tmp):
    print("test_app3_known_plugin_migration")
    knownIds = ("win32_PaddleOCRv6_CPU", "win32_PaddleOCRv6_CUDA", "win32_PaddleOCRVL_1_6")
    check(
        manifest_mod.KNOWN_PLUGIN_IDS_REQUIRING_3X == frozenset(knownIds),
        "技术门禁仅含三个精确已知 id",
    )
    for index, pluginId in enumerate(knownIds):
        for case, version, expected in (
            ("old", "2.8.1", "incompatible"),
            ("old-high-minor", "2.99.99", "incompatible"),
            ("legacy", None, "incompatible"),
            ("new", "3.0.0", "ready"),
            ("new-update", "3.2.1", "ready"),
            ("invalidversion", "invalidversion", "incompatible"),
            ("invalid-numeric", "3.not-a-version", "incompatible"),
            ("missing-version", "", "invalid"),
            ("disabled-old", "2.8.1", "disabled"),
        ):
            _checkMigrationCase(tmp / f"{index}-{case}", pluginId, version, expected)
    # Application version is not the host contract: new known plugins must still
    # satisfy their host_api range rather than bypassing the generic checks.
    _checkMigrationCase(
        tmp / "new-host-incompatible", knownIds[1], "3.0.0", "incompatible", hostApi=">=99.0"
    )
    for capType in ("ocr", "document"):
        _checkMigrationCase(
            tmp / f"third-party-{capType}", f"third_party_{capType}", "1.0.0", "ready", capType
        )
        _checkMigrationCase(
            tmp / f"third-party-legacy-{capType}", f"third_party_legacy_{capType}", None, "ready", capType
        )
    _checkMigrationCase(
        tmp / "near-id", "third_party_win32_PaddleOCRv6_CPU", "2.8.1", "ready"
    )
    # loadManifest historically accepts nonempty version metadata.  The narrow
    # migration check must not add universal strict parsing or discovery crashes.
    _checkMigrationCase(
        tmp / "generic-invalidversion", "third_party_version_metadata", "invalidversion", "ready"
    )
    check(
        not manifest_mod.checkKnownPluginMigration("third_party_legacy", legacy=True),
        "一般 legacy 不进入已知实现门禁",
    )


def _buildTree(root):
    # 1. v2 OCR 插件，配置由 Python 模块提供（动态默认值场景）
    data = _validManifest("t_v2_ocr")
    data["health"] = "health:check"
    data["capabilities"] = [
        {"type": "ocr", "entry": "api:Api", "config": "config:CONFIG"}
    ]
    _makePlugin(
        root,
        "t_v2_ocr",
        {
            "__init__.py": PLUGIN_INIT_LIGHT,
            "api.py": PLUGIN_API_HEAVY,
            "config.py": PLUGIN_V2_CONFIG,
            "health.py": PLUGIN_V2_HEALTH,
        },
        data,
    )

    # 3b. Shared-service plugin: OCR and document remain separate capability
    # registrations while resolving the same lazy service instance.
    data = _validManifest("t_shared")
    data["services"] = [{
        "id": "paddlevl", "entry": "runtime:getService",
        "config": {"title": "模型服务", "type": "group"},
    }]
    data["capabilities"] = [
        {"type": "ocr", "entry": "api:Api", "meta": {"serviceRefs": ["paddlevl"]}},
        {"type": "document", "entry": "api:Api", "meta": {"serviceRefs": ["paddlevl"]}},
    ]
    _makePlugin(
        root,
        "t_shared",
        {"__init__.py": "", "api.py": PLUGIN_SHARED_API, "runtime.py": PLUGIN_SHARED_RUNTIME},
        data,
    )

    # 1b. v2 OCR 插件，配置内联在清单里 —— 发现阶段应【零导入】
    data = _validManifest("t_v2_inline")
    data["capabilities"] = [
        {
            "type": "ocr",
            "entry": "api:Api",
            "config": {
                "global_options": {"title": "Inline Global", "type": "group"},
                "local_options": {
                    "title": "Inline Local",
                    "type": "group",
                    "mode": {
                        "title": "模式",
                        "default": "a",
                        "optionsList": [["a", "甲"], ["b", "乙"]],
                        "toolTip": "提示",
                    },
                },
            },
        }
    ]
    _makePlugin(
        root,
        "t_v2_inline",
        {"__init__.py": PLUGIN_INIT_LIGHT, "api.py": PLUGIN_API_HEAVY},
        data,
    )

    # 2. 旧版 PluginInfo 插件（无清单）
    _makePlugin(root, "t_legacy_ocr", {"__init__.py": PLUGIN_LEGACY})

    # 3. document 能力 + 带 Python 控制器的插件页
    data = _validManifest("t_v2_doc")
    data["capabilities"] = [
        {"type": "document", "entry": ":Api", "config": "config:CONFIG"}
    ]
    data["pages"] = [
        {
            "key": "TestDocPage",
            "qml": "Page.qml",
            "controller": ":DocPage",
            "title": "测试文档页",
            "intro": "intro",
        }
    ]
    _makePlugin(
        root,
        "t_v2_doc",
        {
            "__init__.py": PLUGIN_DOC,
            "config.py": PLUGIN_DOC_CONFIG,
            "Page.qml": "import QtQuick 2.15\nItem {}\n",
        },
        data,
    )

    # 4. 宿主 API 不兼容
    data = _validManifest("t_incompatible")
    data["host_api"] = ">=99.0"
    _makePlugin(
        root,
        "t_incompatible",
        {"__init__.py": PLUGIN_V2, "config.py": PLUGIN_V2_CONFIG},
        data,
    )

    # 5. 未知能力类型
    data = _validManifest("t_unknown_cap")
    data["capabilities"] = [{"type": "quantum-ocr", "entry": ":Api"}]
    _makePlugin(root, "t_unknown_cap", {"__init__.py": PLUGIN_V2}, data)

    # 6/7. 互斥的一对
    for name, other in (("t_conflict_a", "t_conflict_b"), ("t_conflict_b", "t_conflict_a")):
        data = _validManifest(name)
        data["conflicts"] = [other]
        _makePlugin(
            root, name, {"__init__.py": PLUGIN_V2, "config.py": PLUGIN_V2_CONFIG}, data
        )

    # 8. 清单损坏
    pluginDir = root / "t_broken"
    pluginDir.mkdir(parents=True, exist_ok=True)
    (pluginDir / "__init__.py").write_text(PLUGIN_V2, encoding="utf-8")
    (pluginDir / host_api.MANIFEST_NAME).write_text("{ not json", encoding="utf-8")

    # 9. 被用户禁用
    data = _validManifest("t_disabled")
    _makePlugin(
        root, "t_disabled", {"__init__.py": PLUGIN_V2, "config.py": PLUGIN_V2_CONFIG}, data
    )
    (root / controller_mod.PLUGINS_STATE_FILE).write_text(
        json.dumps({"t_disabled": False}), encoding="utf-8"
    )


def test_end_to_end(tmp):
    print("test_end_to_end")
    workdir = tmp / "workdir"
    pluginsRoot = workdir / "plugins"
    pluginsRoot.mkdir(parents=True)
    _buildTree(pluginsRoot)

    loadBuiltinCapabilityTypes()
    previousCwd = os.getcwd()
    os.chdir(workdir)
    try:
        summary = controller_mod.PluginsController.init()
    finally:
        os.chdir(previousCwd)

    states = {p["id"]: p for p in summary["plugins"]}

    check(states["t_v2_ocr"]["state"] == "ready", "v2 OCR 插件 ready")
    check(states["t_legacy_ocr"]["state"] == "ready", "旧版插件零改动 ready")
    check(states["t_legacy_ocr"]["legacy"] is True, "旧版插件被标记 legacy")
    check(states["t_v2_doc"]["state"] == "ready", "document 插件 ready（v1 会拒绝）")
    check(states["t_shared"]["state"] == "ready", "双能力共享服务插件 ready")
    check(states["t_incompatible"]["state"] == "incompatible", "宿主 API 不兼容")
    check("99.0" in states["t_incompatible"]["message"], "不兼容原因含所需版本")
    check(states["t_unknown_cap"]["state"] == "incompatible", "未知能力类型不兼容")
    check(states["t_broken"]["state"] == "invalid", "损坏清单 invalid")
    check(states["t_disabled"]["state"] == "disabled", "禁用状态被持久化并生效")

    conflictStates = {
        states["t_conflict_a"]["state"],
        states["t_conflict_b"]["state"],
    }
    check(conflictStates == {"ready", "conflict"}, "互斥插件只保留一个")
    check(states["t_conflict_a"]["state"] == "ready", "冲突裁决按 id 字典序可复现")

    ocr = getCapabilityRegistry("ocr")
    document = getCapabilityRegistry("document")
    check("t_v2_ocr" in ocr.keys(), "v2 OCR 能力已注册")
    check("t_legacy_ocr" in ocr.keys(), "旧版 OCR 能力已注册")
    check("t_v2_doc" in document.keys(), "document 能力注册到独立注册表")
    check("t_v2_doc" not in ocr.keys(), "document 插件没有被塞进 OCR 注册表")
    check("t_disabled" not in ocr.keys(), "禁用插件不注册能力")
    check("t_incompatible" not in ocr.keys(), "不兼容插件不注册能力")
    check(
        summary["options"]["ocr"]["t_shared"]["meta"]["serviceRefs"] == ["paddlevl"]
        and summary["options"]["document"]["t_shared"]["meta"]["serviceRefs"] == ["paddlevl"],
        "两个能力保留同一 serviceRefs 元数据",
    )
    check(
        summary["services"].get("t_shared", [{}])[0].get("id") == "paddlevl",
        "共享服务在全局设置汇总中出现一次",
    )
    shared = PluginServices.get("t_shared", "paddlevl")
    check(PluginServices.get("t_shared", "paddlevl") is shared, "共享服务按插件/id 单例解析")
    health = PluginServices.call("t_shared", "paddlevl", "health", {"context": 8192})
    check(health["ok"] and health["details"]["values"].get("context") == 8192, "共享服务先配置再健康检查")

    class FakeQJSValue:
        def __init__(self, value):
            self.value = value

        def toVariant(self):
            return self.value

    qjsHealth = PluginServices.call(
        "t_shared",
        "paddlevl",
        "health",
        FakeQJSValue({"context": 16384, "nested": FakeQJSValue({"enabled": True})}),
    )
    qjsValues = qjsHealth["details"]["values"]
    check(
        qjsHealth["ok"]
        and qjsValues.get("context") == 16384
        and qjsValues.get("nested") == {"enabled": True},
        "共享服务接受 QJSValue/QVariant 风格参数并递归转换为普通 Python 容器",
    )

    check(
        summary["options"]["ocr"]["t_v2_ocr"]["local_options"]["title"] == "V2 Local",
        "配置在发现阶段可用",
    )
    check(
        summary["options"]["document"]["t_v2_doc"]["local_options"]["title"]
        == "Doc Local",
        "裸配置字典被归一化为 local_options",
    )
    check(
        summary["options"]["ocr"]["t_legacy_ocr"]["global_options"]["title"] == "Legacy",
        "旧版配置经适配层可用",
    )

    check(
        summary["options"]["ocr"]["t_v2_inline"]["local_options"]["title"]
        == "Inline Local",
        "内联清单配置可用",
    )

    # 关键性质 1：内联配置的插件，发现阶段一行 Python 都不导入。
    check(
        "t_v2_inline" not in sys.modules,
        "内联配置插件在发现阶段零导入",
    )
    # 关键性质 2：入口式配置必须导入插件包与配置模块（契约明示的代价），
    # 但重量级的实现模块仍然不导入。
    check(
        "t_v2_ocr" in sys.modules and "t_v2_ocr.config" in sys.modules,
        "入口式配置会导入插件包与配置模块（已知代价）",
    )
    check(
        "t_v2_ocr.api" not in sys.modules,
        "发现阶段不导入实现模块（惰性解析生效）",
    )
    check(
        "t_legacy_ocr" in sys.modules,
        "旧版插件必须导入才能读 PluginInfo（已知代价）",
    )

    apiClass, err = ocr.resolve("t_v2_ocr")
    check(apiClass is not None and not err, "能力可按需解析")
    check("t_v2_ocr.api" in sys.modules, "解析后才导入实现模块")
    check("t_v2_inline" not in sys.modules, "未使用的插件始终不被导入")
    instance = apiClass({"a": 1})
    check(getattr(instance, "argd", None) == {"a": 1}, "能力入口接收配置字典")

    # 页面注册与控制器
    pages = {p["key"]: p for p in summary["pages"]}
    check("TestDocPage" in pages, "插件页已注册")
    check(pages["TestDocPage"]["needController"] is True, "插件页声明需要控制器")
    check(pages["TestDocPage"]["pluginKey"] == "t_v2_doc", "插件页带 pluginKey")
    check(pages["TestDocPage"]["url"].startswith("file:"), "插件页 url 为 file URI")
    pageClass = page_registry.getPluginPageClass("TestDocPage")
    check(pageClass is not None, "插件页控制器可解析（契约 v1 在此失败）")
    if pageClass:
        obj = pageClass("ctrl-1", None)
        check(obj.ctrlKey == "ctrl-1", "插件页控制器构造签名与内置页一致")

    # 健康检查
    healthy = controller_mod.PluginsController.runHealthCheck("t_v2_ocr")
    check(healthy["ok"] is True, "健康检查通过")
    check(healthy["details"].get("probe") == 1, "健康检查返回 details")
    undeclared = controller_mod.PluginsController.runHealthCheck("t_legacy_ocr")
    check(
        undeclared["ok"] is True and undeclared["details"].get("declared") is False,
        "未声明健康检查的插件按加载成功处理并如实标注",
    )
    blocked = controller_mod.PluginsController.runHealthCheck("t_incompatible")
    check(blocked["ok"] is False, "不兼容插件的健康检查直接返回 False")
    missing = controller_mod.PluginsController.runHealthCheck("nope")
    check(missing["ok"] is False, "不存在的插件返回 False 而不是抛异常")

    check(summary["errors"].get("t_broken"), "损坏插件进入 errors 汇总")
    check(
        summary["host"]["hostApiVersion"] == host_api.HOST_API_VERSION,
        "汇总里带宿主环境",
    )
    check(
        set(summary["capabilityTypes"]) >= {"ocr", "document"},
        "宿主上报支持的能力类型",
    )
    check(host_api.HOST_API_VERSION == "2.8", "共享服务契约提升宿主 API 至 2.8")
    PluginServices.reset()


def main():
    tmp = Path(tempfile.mkdtemp(prefix="umi-plugin-contract-"))
    try:
        test_version_range()
        test_manifest_validation(tmp / "manifests")
        test_compatibility()
        test_nullable_scores()
        test_app3_known_plugin_migration(tmp / "app3-migration")
        test_end_to_end(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILURES:
        print(f"\n{len(FAILURES)} 项失败：")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("\n插件契约 v2 全部检查通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
