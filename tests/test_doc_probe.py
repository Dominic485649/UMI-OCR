"""显式选择源码或应用包的文档探测回归，不启动 GUI 或推理后端。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime


PASSWORD = "回归 密码 302!"
_MAKE_DOCUMENTS = """
import json
from pathlib import Path
import sys
runtime_root = Path(sys.argv[1])
sys.path[:0] = [str(runtime_root / 'site-packages'), str(runtime_root / 'dependencies.zip')]
import fitz
payload = json.load(sys.stdin)
root = Path(payload['root'])
for relative, count, encrypted in [
    ('正常 文件.PDF', 2, False),
    ('加密 文件.pdf', 3, True),
    ('子目录/嵌套 文档.pdf', 1, False),
]:
    with fitz.open() as doc:
        for _ in range(count):
            doc.new_page()
        options = {}
        if encrypted:
            options = dict(encryption=fitz.PDF_ENCRYPT_AES_256,
                           user_pw=payload['password'], owner_pw=payload['password'] + ' owner')
        doc.save(str(root / relative), **options)
"""


def create_documents(data_root, root):
    """在新的数据目录生成微型 PDF；只有另一个隔离进程导入 fitz。"""
    root.mkdir()
    (root / "子目录").mkdir()
    (root / "空目录").mkdir()
    completed = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-c", _MAKE_DOCUMENTS, str(data_root)],
        input=json.dumps({"root": str(root), "password": PASSWORD}, ensure_ascii=False),
        encoding="utf-8",
        capture_output=True,
        cwd=ROOT,
        timeout=30,
    )
    assert completed.returncode == 0, f"生成新测试 PDF 失败：{completed.stderr}"
    invalid = root / "无效.pdf"
    invalid.write_bytes(b"this is not a PDF")
    (root / "零字节.pdf").write_bytes(b"")
    unsupported = root / "不支持.txt"
    unsupported.write_text("不支持的文档", encoding="utf-8")
    return {
        "root": root,
        "plain": root / "正常 文件.PDF",
        "encrypted": root / "加密 文件.pdf",
        "nested": root / "子目录" / "嵌套 文档.pdf",
        "invalid": invalid,
        "unsupported": unsupported,
        "empty": root / "空目录",
        "missing": root / "不存在.pdf",
    }


def assert_source(module, source_root):
    # app.zip 内的 __file__ 是虚拟路径，只检查所属根目录，不要求它是磁盘文件。
    module_path = Path(module.__file__).absolute()
    assert module_path.is_relative_to(source_root), f"模块不属于指定根目录 {source_root}：{module_path}"
    print(f"模块来源：{module.__name__} -> {module_path}")


def check_isolated_reads(doc_probe, files):
    marker = files["root"] / "植入模块已执行"
    planted = f"from pathlib import Path\nPath({str(marker)!r}).write_text('unexpected')\nraise RuntimeError('植入模块')\n"
    for name in ("json.py", "fitz.py", "pymupdf.py", "sitecustomize.py"):
        (files["root"] / name).write_text(planted, encoding="utf-8")
    snapshots = {key: hashlib.sha256(files[key].read_bytes()).hexdigest() for key in ("plain", "encrypted", "invalid")}
    original_popen = subprocess.Popen
    processes = []

    def record_process(args, **kwargs):
        assert "-I" in args and "utf8" in args
        assert PASSWORD not in str(args)
        assert str(files["root"]) not in str(args)
        assert Path(kwargs["cwd"]).resolve() != files["root"].resolve()
        process = original_popen(args, **kwargs)
        processes.append(process)
        return process

    previous_cwd = Path.cwd()
    try:
        # 即使调用者当前在文档目录，也只能将它作为读取数据的基准。
        os.chdir(files["root"])
        with patch.object(doc_probe.subprocess, "Popen", record_process), patch.dict(
            os.environ, {"PYTHONPATH": str(files["root"]), "PYTHONHOME": str(files["root"])}
        ):
            plain = doc_probe.probe_document(files["plain"].name)
            assert plain == {"path": files["plain"].name, "page_count": 2, "is_encrypted": False, "is_authenticate": True}, plain
            for password, authenticated in (("", False), ("错误密码", False), (PASSWORD, True)):
                info = doc_probe.probe_document(str(files["encrypted"]), password)
                assert "error" not in info, info
                assert info["page_count"] == 3
                assert info["is_encrypted"] is True and info["is_authenticate"] is authenticated
            for path in (files["missing"], files["invalid"], files["empty"], files["root"] / "零字节.pdf", "", None, "bad\x00path"):
                assert "error" in doc_probe.probe_document(path), path
            for timeout in (0, -1, float("inf"), None):
                assert "error" in doc_probe.probe_document(files["plain"], timeout=timeout)
            assert "error" in doc_probe.probe_document(files["encrypted"], password=None)
            before = len(processes)
            many = list(doc_probe.probe_documents([str(files["plain"])] * (doc_probe.PROBE_BATCH_SIZE * 2 + 1)))
            assert len(many) == doc_probe.PROBE_BATCH_SIZE * 2 + 1
            assert all(item["page_count"] == 2 and "error" not in item for item in many)
            assert len(processes) - before == 3, "批量读取没有复用有界子进程"
    finally:
        os.chdir(previous_cwd)
    assert not marker.exists(), "文档目录中的植入模块被加载"
    assert all(process.poll() is not None for process in processes), "有文档读取子进程残留"
    assert snapshots == {key: hashlib.sha256(files[key].read_bytes()).hexdigest() for key in snapshots}, "探测修改了原始文档"


def check_worker_failures(doc_probe, files):
    original_popen = subprocess.Popen
    processes = []

    def record_process(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    with patch.object(doc_probe.subprocess, "Popen", record_process):
        started = time.monotonic()
        with patch.object(doc_probe, "_WORKER_BOOTSTRAP", "import sys,time; sys.stdin.buffer.read(); time.sleep(60)"):
            result = doc_probe.probe_document(files["plain"], timeout=0.15)
        assert result["error_kind"] == "timeout", result
        assert time.monotonic() - started < 5, "超时未及时回收子进程"
        started = time.monotonic()
        with patch.object(doc_probe, "_WORKER_BOOTSTRAP", "import time; time.sleep(60)"):
            # 大于管道容量的 JSON 输入，子进程故意不读 stdin。
            result = doc_probe.probe_document(files["plain"], password="x" * (1024 * 1024), timeout=0.15)
        assert result["error_kind"] == "timeout" and time.monotonic() - started < 5, result
        with patch.object(doc_probe, "_WORKER_BOOTSTRAP", "import os; os._exit(23)"):
            result = doc_probe.probe_document(files["plain"])
        assert result["error_kind"] == "workererror" and "23" in result["error"], result
        with patch.object(doc_probe, "_WORKER_BOOTSTRAP", "import sys; sys.stdin.buffer.read(); print('invalid-json')"):
            result = doc_probe.probe_document(files["plain"])
        assert result["error_kind"] == "workererror", result
        with patch.object(doc_probe, "_WORKER_BOOTSTRAP", f"import sys; sys.stdin.buffer.read(); sys.stdout.write('x'*{doc_probe._MAX_OUTPUT_BYTES + 1})"):
            result = doc_probe.probe_document(files["plain"])
        assert result["error_kind"] == "workererror" and "过大" in result["error"], result
        partial_worker = """
import json,os,sys
payload = json.loads(sys.stdin.buffer.read())
for index, item in enumerate(payload['documents']):
    if item['path'].endswith('crash.pdf'):
        os._exit(24)
    print(json.dumps({'index': index, 'info': {'page_count': 1, 'is_encrypted': False, 'is_authenticate': True}}), flush=True)
"""
        before = len(processes)
        with patch.object(doc_probe, "_WORKER_BOOTSTRAP", partial_worker):
            results = list(doc_probe.probe_documents([str(files["plain"]), str(files["root"] / "crash.pdf"), str(files["nested"])]))
        assert "error" not in results[0] and results[1]["error_kind"] == "workererror" and "error" not in results[2], results
        assert len(processes) - before == 2, "坏文档之后没有重建独立进程继续"
        with patch.object(doc_probe, "_WORKER_BOOTSTRAP", partial_worker.replace("os._exit(24)", "__import__('time').sleep(60)")):
            results = list(doc_probe.probe_documents([str(files["plain"]), str(files["root"] / "crash.pdf"), str(files["nested"])], timeout=0.5))
        assert "error" not in results[0] and results[1]["error_kind"] == "timeout" and "error" not in results[2], results
        with patch.object(doc_probe, "_WORKER_BOOTSTRAP", partial_worker + "\nos._exit(26)\n"):
            result = doc_probe.probe_document(files["plain"])
        assert result["error_kind"] == "workererror", "完整结果后的崩溃被忽略"
        with patch.object(doc_probe, "_WORKER_BOOTSTRAP", partial_worker + "\n__import__('time').sleep(60)\n"):
            result = doc_probe.probe_document(files["plain"], timeout=0.5)
        assert result["error_kind"] == "timeout", "完整结果后的挂起被忽略"
    assert all(process.poll() is not None for process in processes), "超时/崩溃的子进程没有结束"
    with patch.object(doc_probe.subprocess, "Popen", side_effect=OSError("不可用")):
        assert doc_probe.probe_document(files["plain"])["error_kind"] == "workererror"


def check_runtime_selection(doc_probe, data_root, source_root):
    native_launcher = str(data_root.parent / "Umi-OCR.exe")
    with patch.object(doc_probe, "__file__", str(data_root / "app.zip" / "py_src" / "utils" / "doc_probe.py")), patch.object(sys, "executable", native_launcher):
        _, app_root, runtime_root, python = doc_probe._runtime_paths()
        assert app_root == data_root and runtime_root == data_root
        assert python == data_root / "runtime" / "python.exe", "误选了原生 GUI 启动器"
    with patch.object(sys, "executable", native_launcher), patch.object(doc_probe.subprocess, "Popen") as popen:
        # 当前源码没有 runtime，原生宿主不能退回启动 GUI。
        if not (source_root / "runtime" / "python.exe").exists():
            assert doc_probe.probe_document("unused.pdf")["error_kind"] == "workererror"
            popen.assert_not_called()


def check_zip_worker(source_root, files):
    with tempfile.TemporaryDirectory(prefix="doc-probe-code-", dir=ROOT / "build") as code_dir:
        archive = Path(code_dir) / "app.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("py_src/", b"")
            output.writestr("py_src/utils/", b"")
            for name in ("__init__.py", "doc_probe.py", "_doc_probe_worker.py"):
                relative = "py_src/utils/" + name
                source = source_root / "py_src" / "utils" / name
                if source.is_file():
                    output.write(source, relative)
                else:
                    # 包模式只复制当前包里的可信 helper，不借用仓库源码补文件。
                    with zipfile.ZipFile(source_root / "app.zip") as packaged:
                        output.writestr(relative, packaged.read(relative))
        code = """
import json,sys
sys.path.insert(0, sys.argv[1])
from py_src.utils import doc_probe
payload = json.loads(sys.stdin.buffer.read())
result = doc_probe.probe_document(payload['path'], payload['password'])
print(json.dumps({'module': doc_probe.__file__, 'result': result,
                  'parent_fitz': 'fitz' in sys.modules, 'parent_qt': 'PySide6' in sys.modules}, ensure_ascii=False))
"""
        completed = subprocess.run(
            [sys.executable, "-I", "-X", "utf8", "-c", code, str(archive)],
            input=json.dumps({"path": str(files["encrypted"]), "password": PASSWORD}, ensure_ascii=False),
            encoding="utf-8", capture_output=True, cwd=ROOT, timeout=30,
        )
        assert completed.returncode == 0, completed.stderr
        result = json.loads(completed.stdout)
        assert "app.zip" in result["module"] and result["result"]["is_authenticate"] is True, result
        assert result["result"]["is_encrypted"] is True and result["result"]["page_count"] == 3, result
        assert not result["parent_fitz"] and not result["parent_qt"], result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source-root", type=Path, help="使用现有便携依赖，显式加载本次应用源码")
    mode.add_argument("--packaged", action="store_true", help="只验证给定 data_root 内的应用代码和资源，不覆盖源码")
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    module_root = data_root if args.packaged else args.source_root.resolve()
    handles = configure_runtime(data_root)
    if not args.packaged:
        sys.path[:0] = [str(module_root), str(module_root / "py_src" / "imports")]
    print(f"文档探测测试模式：{'packaged' if args.packaged else 'source'}，模块根目录：{module_root}")
    from py_src.utils import doc_probe

    assert_source(doc_probe, module_root)
    assert "fitz" not in sys.modules and "pymupdf" not in sys.modules
    with tempfile.TemporaryDirectory(prefix="umi-doc-probe-data-") as data_dir:
        files = create_documents(data_root, Path(data_dir) / "文档 空格")
        check_isolated_reads(doc_probe, files)
        check_worker_failures(doc_probe, files)
        check_runtime_selection(doc_probe, data_root, module_root)
        check_zip_worker(module_root, files)
    assert "fitz" not in sys.modules and "pymupdf" not in sys.modules, "父进程导入了文档解析库"
    del handles
    print(f"文档隔离探测{'包' if args.packaged else '源码'}回归通过：app.zip、中文空格路径、密码、超时/崩溃、有界批量、模块植入隔离。")


if __name__ == "__main__":
    main()
