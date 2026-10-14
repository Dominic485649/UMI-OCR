import argparse
import os
import runpy
import sys
from pathlib import Path


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
    os.MessageBox = lambda message, *_args: print(message)

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
    print("Qt/QML startup smoke passed.")


if __name__ == "__main__":
    main()
