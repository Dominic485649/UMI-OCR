# ==================================================
# =============== 插件宿主 API 版本与环境 ===============
# ==================================================

"""
宿主向插件承诺的契约版本与运行环境描述。

插件清单 umi-plugin.json 通过 host_api 字段声明自己支持的宿主范围，
宿主在【发现阶段】就能判定兼容性，无需导入插件的 Python 代码。

HOST_API_VERSION 的兼容规则：
- 主版本号变化 = 破坏性变更，旧插件必须更新。
- 次版本号递增 = 只增加能力，旧插件继续可用。
"""

import os
import sys

# 宿主契约版本。修改时必须同步 docs/PLUGIN_API.md 的兼容矩阵。
HOST_API_VERSION = "2.8"

# 清单文件名
MANIFEST_NAME = "umi-plugin.json"

# 宿主支持的清单 schema 版本
SUPPORTED_SCHEMA_VERSIONS = (1,)

_OPERATORS = (">=", "<=", "==", "!=", ">", "<")


def parseVersion(text):
    """将 "2.7" / "2.7.0" / "1.0.0-beta" 解析为可比较的三元组。

    非数字后缀被忽略，缺失的段补 0 。解析失败的段视为 0 ，
    这样一个写坏的版本号不会让整个插件发现流程崩溃。
    """
    if isinstance(text, (tuple, list)):
        parts = [int(n) for n in text[:3]]
    else:
        parts = []
        for chunk in str(text).strip().split("."):
            digits = ""
            for ch in chunk:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _compare(left, operator, right):
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    if operator == "<":
        return left < right
    if operator == "!=":
        return left != right
    return left == right


def matchVersionRange(version, spec):
    """判断 version 是否满足 spec 。

    spec 语法：逗号分隔的比较式，全部满足才算通过。
    - "*" 或空 → 任意版本
    - ">=2.7,<3.0" → 常规范围
    - "2.7" → 等价于 "==2.7"
    语法非法的比较式返回 False ，宁可报不兼容也不要放进来一个坏插件。
    """
    spec = str(spec or "*").strip()
    if spec in ("", "*"):
        return True
    current = parseVersion(version)
    for clause in spec.split(","):
        clause = clause.strip()
        if not clause:
            continue
        for operator in _OPERATORS:
            if clause.startswith(operator):
                target = clause[len(operator) :].strip()
                if not target:
                    return False
                if not _compare(current, operator, parseVersion(target)):
                    return False
                break
        else:
            if current != parseVersion(clause):
                return False
    return True


def hostPlatform():
    """归一化的平台标识，与清单 platform 字段取值一致。"""
    if sys.platform.startswith("win"):
        return "win32"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    return sys.platform


def hostArch():
    """归一化的架构标识，与清单 arch 字段取值一致。"""
    import platform as _platform

    machine = (_platform.machine() or "").lower()
    if machine in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86", "i386", "i686"):
        return "x86"
    return machine or "unknown"


def matchTokenList(value, tokens):
    """清单里的 platform / arch 列表匹配。"* " 或空列表代表不限制。"""
    if not tokens:
        return True
    for token in tokens:
        token = str(token).strip().lower()
        if token in ("*", "any"):
            return True
        if token == str(value).lower():
            return True
    return False


def hostEnvironment():
    """供 UI 与诊断展示的宿主环境摘要。"""
    return {
        "hostApiVersion": HOST_API_VERSION,
        "platform": hostPlatform(),
        "arch": hostArch(),
        "python": "%d.%d.%d" % sys.version_info[:3],
        "cpuCount": os.cpu_count() or 1,
    }
