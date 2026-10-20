"""执行实际 QML 配置函数，区分可选后端缺席与真正的非法空枚举。"""

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build/tools"))
from staging_smoke import configure_runtime


def qml_function(path, name):
    source = path.read_text(encoding="utf-8")
    match = re.search(r"\bfunction\s+" + re.escape(name) + r"\s*\(", source)
    assert match, (path, name)
    index = source.index("{", match.end())
    depth = 0
    quote = None
    line_comment = False
    block_comment = False
    while index < len(source):
        char = source[index]
        pair = source[index:index + 2]
        if line_comment:
            line_comment = char != "\n"
        elif block_comment:
            if pair == "*/":
                block_comment = False
                index += 1
        elif quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = None
        elif pair == "//":
            line_comment = True
            index += 1
        elif pair == "/*":
            block_comment = True
            index += 1
        elif char in ("'", '"', "`"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():index + 1]
        index += 1
    raise AssertionError(f"QML 函数未闭合：{path} {name}")


SETUP = r'''
var messages = [], calls = [], applied = false;
var localOptions = {}, serviceRefs = {}, globalOptions = {}, apiKey = "";
var configDict = {}, originDict = {}, valueDict = {}, cacheDict = {};
var category_ = "Global";
var settings = {readValue: function() { return undefined; }};
var qmlapp = {
    globalConfigs: {configDict: configDict},
    popup: {message: function(title, message) { messages.push(message); }},
    msnConnector: {callPy: function(kind, operation, args) {
        calls.push([kind, operation, args]);
    }}
};
var console = {log: function() {}};
function qsTr(text) { return text; }
String.prototype.arg = function(value) { return this.replace(/%[1-9]/, String(value)); };
function setValue(key, value) { valueDict[key] = value; }
function stopAllMissions() {}
function runHealthCheck() {}
function scheduleWarmup() {}
function resetCleanupSchedule() {}
function applyConfigs() { applied = true; }
'''


def evaluate(engine, source):
    value = engine.evaluate(source)
    assert not value.isError(), value.toString() + "\n" + value.property("stack").toString()
    return value


def check_capability(source_root, kind, engine):
    qml = source_root / "qt_res/qml"
    manager = qml / "ApiManager" / ("DocumentManager.qml" if kind == "document" else "OcrManager.qml")
    configs = qml / "Configs/Configs.qml"
    functions = [qml_function(manager, name) for name in ("makeGlobalOptions", "init1", "init2")]
    functions += [qml_function(configs, name) for name in ("initConfigDict", "str2var", "supplyDefaultParams")]
    evaluate(engine, SETUP + "\n" + "\n".join(functions))

    # 初次启动无后端，以及移除最后一个插件后的刷新，都不注册不可选的枚举。
    for phase in ("首次无后端", "移除最后一个后端"):
        result = json.loads(evaluate(engine, '''
            messages = []; calls = []; apiKey = "旧后端";
            init1({}); initConfigDict(); init2();
            JSON.stringify({messages: messages, calls: calls, apiKey: apiKey,
                            configKeys: Object.keys(configDict), valueKeys: Object.keys(valueDict)});
        ''').toString())
        assert not result["messages"], (kind, phase, result)
        assert kind not in result["configKeys"], (kind, phase, result)
        assert f"{kind}.api" not in result["valueKeys"], (kind, phase, result)
        assert result["apiKey"] == "", (kind, phase, result)
        assert result["calls"] == [[kind, "setApi", ["", {}]]], (kind, phase, result)

        # 插件重新出现时仍恢复真实接口，配置缺少全局项时也使用真实后端标识。
        for options in (
            {"测试后端": {"global_options": {"title": "中文后端", "type": "group"}}},
            {"测试后端": {}},
        ):
            evaluate(engine, "messages = []; applied = false; init1(" + json.dumps(options, ensure_ascii=False) + "); initConfigDict(); init2();")
            result = json.loads(evaluate(engine, '''
                JSON.stringify({messages: messages, applied: applied, values: valueDict,
                                providers: Object.keys(localOptions)});
            ''').toString())
            assert not result["messages"], (kind, phase, result)
            assert result["values"][f"{kind}.api"] == "测试后端", (kind, phase, result)
            assert result["providers"] == ["测试后端"], (kind, phase, result)
            assert result["applied"], (kind, phase, result)

    # 不能通过放宽通用配置校验来掩盖非法插件选项。
    result = json.loads(evaluate(engine, '''
        messages = []; configDict = {broken: {optionsList: []}};
        initConfigDict(); JSON.stringify(messages);
    ''').toString())
    assert len(result) == 1 and "broken枚举列表为空" in result[0], result
    print(f"{kind} 可选后端初始化、移除、恢复及非法枚举校验通过。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    source_root = (args.source_root or data_root).resolve()
    handles = configure_runtime(data_root)
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtQml import QJSEngine

    app = QCoreApplication.instance() or QCoreApplication([])
    for kind in ("document", "ocr"):
        check_capability(source_root, kind, QJSEngine())


if __name__ == "__main__":
    main()
