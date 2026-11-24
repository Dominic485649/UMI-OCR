"""用实际 Windows 启动器验证隔离模式始终启用 UTF-8，不启动产品界面。"""

import argparse
import codecs
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


PROBE = '''\
import json
import locale
from pathlib import Path
import sys

text = "中文、café、🚀"
sample = Path(__file__).with_name("默认编码.txt")
with sample.open("w") as stream:
    default_encoding = stream.encoding
    stream.write(text)
with sample.open() as stream:
    round_trip = stream.read()
result = {
    "utf8_mode": sys.flags.utf8_mode,
    "isolated": sys.flags.isolated,
    "preferred_encoding": locale.getpreferredencoding(False),
    "default_encoding": default_encoding,
    "filesystem_encoding": sys.getfilesystemencoding(),
    "streams": {
        name: getattr(getattr(sys, name), "encoding", None)
        for name in ("stdin", "stdout", "stderr")
    },
    "text": round_trip,
    "bytes_hex": sample.read_bytes().hex(),
    "argument": sys.argv[2],
}
Path(sys.argv[1]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
'''


def check_launcher(data_root, executable):
    with tempfile.TemporaryDirectory(prefix="umi-utf8-") as temporary:
        root = Path(temporary) / "中文启动路径"
        data = root / "UmiOCR-data"
        data.mkdir(parents=True)
        shutil.copytree(data_root / "runtime", data / "runtime")
        launcher = root / "Umi-OCR.exe"
        shutil.copy2(executable, launcher)
        (data / "main.py").write_text(PROBE, encoding="utf-8")
        result_path = root / "编码结果.json"
        environment = os.environ.copy()
        # 故意设置冲突值，确认不是依赖当前系统代码页或环境变量碰巧通过。
        environment.update(PYTHONUTF8="0", PYTHONIOENCODING="gbk", LC_ALL="C")
        process = subprocess.run(
            [str(launcher), str(result_path), "中文参数🚀"],
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
        assert result_path.is_file(), "启动器未生成 UTF-8 探针结果。"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["utf8_mode"] == 1, result
        assert result["isolated"] == 1, result
        for field in ("preferred_encoding", "default_encoding", "filesystem_encoding"):
            assert codecs.lookup(result[field]).name == "utf-8", result
        for encoding in result["streams"].values():
            if encoding is not None:
                assert codecs.lookup(encoding).name == "utf-8", result
        assert result["text"] == "中文、café、🚀", result
        assert bytes.fromhex(result["bytes_hex"]) == "中文、café、🚀".encode("utf-8"), result
        assert result["argument"] == "中文参数🚀", result
        print(json.dumps(result, ensure_ascii=False))


def check_host_streams(data_root):
    import io
    import runpy
    import sys

    namespace = runpy.run_path(str(data_root / "main.py"), run_name="utf8_test")
    originals = {name: getattr(sys, name) for name in ("stdin", "stdout", "stderr")}
    variables = ("PYTHONUTF8", "PYTHONIOENCODING")
    original_environment = {key: os.environ.get(key) for key in variables}
    streams = {
        name: io.TextIOWrapper(
            io.BytesIO("中文输入🚀".encode("utf-8") if name == "stdin" else b""),
            encoding="gbk",
            errors="surrogateescape" if name == "stdin" else "backslashreplace",
        )
        for name in originals
    }
    try:
        for name, stream in streams.items():
            setattr(sys, name, stream)
        os.environ.update(PYTHONUTF8="0", PYTHONIOENCODING="gbk")
        namespace["configureUtf8"]()
        namespace["configureUtf8"]()
        assert os.environ["PYTHONUTF8"] == "1"
        assert os.environ["PYTHONIOENCODING"] == "utf-8"
        assert streams["stdin"].read() == "中文输入🚀"
        assert streams["stdin"].errors == "surrogateescape"
        for name in ("stdout", "stderr"):
            streams[name].write("中文输出🚀")
            streams[name].flush()
            assert streams[name].buffer.getvalue() == "中文输出🚀".encode("utf-8")
            assert streams[name].errors == "backslashreplace"
        for stream in streams.values():
            assert codecs.lookup(stream.encoding).name == "utf-8"
        for name in originals:
            setattr(sys, name, None)
        namespace["configureUtf8"]()
        with io.StringIO() as custom_stream:
            sys.stdout = custom_stream
            namespace["configureUtf8"]()
            assert sys.stdout is custom_stream
    finally:
        for name, stream in originals.items():
            setattr(sys, name, stream)
        for key, value in original_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for stream in streams.values():
            stream.close()


def check_pre_settings(data_root):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "utf8_pre_configs", data_root / "py_src/utils/pre_configs.py"
    )
    configs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(configs)

    def utf8_open(*args, **kwargs):
        # 不使用本机默认编码，读写双方都必须显式声明 UTF-8。
        assert kwargs.get("encoding") == "utf-8", kwargs
        return open(*args, **kwargs)

    with tempfile.TemporaryDirectory(prefix="umi-pre-settings-") as temporary:
        path = Path(temporary) / "中文配置.json"
        expected = dict(configs._Configs, i18n="中文、café、🚀")
        path.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
        configs._FileName = str(path)
        configs.open = utf8_open
        configs.readConfigs()
        assert configs.getErrorStr() == "", configs.getErrorStr()
        assert configs.getValue("i18n") == expected["i18n"]
        configs.writeConfigs()
        assert configs.getErrorStr() == "", configs.getErrorStr()
        assert json.loads(path.read_text(encoding="utf-8")) == expected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    source_root = (args.source_root or data_root).resolve()
    check_launcher(data_root, args.executable.resolve())
    check_host_streams(source_root)
    check_pre_settings(source_root)
    print("原生启动器、宿主标准流和预配置 UTF-8 回归通过。")


if __name__ == "__main__":
    main()
