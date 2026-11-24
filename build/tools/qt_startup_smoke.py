import argparse
import json
import os
import runpy
import sys
from pathlib import Path


EMPTY_ENUMS = '''
(function() {
    const empty = [];
    function visit(group, prefix) {
        for(const key in group) {
            const config = group[key];
            if(!config || typeof config !== "object" || Array.isArray(config)) continue;
            if(config.type === "group") visit(config, prefix + key + ".");
            else if(config.hasOwnProperty("optionsList") && config.optionsList.length === 0)
                empty.push(prefix + key);
        }
    }
    visit(qmlapp.globalConfigs.configDict, "");
    return JSON.stringify(empty);
})()
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--seconds", type=float, default=5)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    executable = args.executable.resolve()
    namespace = runpy.run_path(str(data_root / "main.py"), run_name="umi_runtime")
    namespace["initRuntimeEnvironment"]()
    errors = []
    os.MessageBox = lambda message, *_args: errors.append(str(message))

    from PySide6 import QtQml
    from PySide6.QtQml import QQmlEngine, QQmlExpression

    original_engine = QtQml.QQmlApplicationEngine

    class CheckedEngine(original_engine):
        def load(self, *values):
            super().load(*values)
            roots = self.rootObjects()
            if not roots:
                errors.append("启动后未创建 QML 根窗口。")
                return
            window = roots[0]
            expression = QQmlExpression(QQmlEngine.contextForObject(window), window, EMPTY_ENUMS)
            result = expression.evaluate()
            if expression.hasError():
                errors.append(expression.error().toString())
                return
            if isinstance(result, tuple):
                result = result[0]
            if hasattr(result, "toVariant"):
                result = result.toVariant()
            empty = json.loads(result)
            if empty:
                errors.append("启动配置仍包含空枚举：" + ", ".join(empty))

    # 必须在导入正式入口前替换，确保校验的是真实首屏创建后的配置。
    QtQml.QQmlApplicationEngine = CheckedEngine
    from py_src.run import main as run_app
    from py_src.utils import pre_configs

    pre_configs.readConfigs()
    pre_configs.setValue("last_pid", -1)
    pre_configs.setValue("last_ptime", -1)
    sys.argv = [str(executable), "--force"]
    try:
        run_app(
            app_path=str(executable),
            engineAddImportPath="./site-packages/PySide6/qml",
            quitAfterMs=max(1, round(args.seconds * 1000)),
        )
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
    finally:
        QtQml.QQmlApplicationEngine = original_engine
    assert not errors, "\n".join(errors)
    print("Qt/QML startup smoke passed; no empty capability enums or startup errors.")


if __name__ == "__main__":
    main()
