"""显式选择源码或应用包的文件导入回归，并核对实际加载的模块来源。"""

import argparse
import itertools
import sys
import tempfile
import time
from pathlib import Path
from threading import Event
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "build" / "tools"), str(ROOT / "tests")]
from staging_smoke import configure_runtime
from test_doc_probe import assert_source, create_documents


def wait_for(app, event):
    deadline = time.monotonic() + 15
    while not event.is_set() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert event.is_set(), "异步文件导入未发送终态"


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
    print(f"文件导入测试模式：{'packaged' if args.packaged else 'source'}，模块根目录：{module_root}")

    from PySide6.QtCore import QCoreApplication, QUrl
    from py_src.event_bus.pubsub_service import PubSubService
    from py_src.mission import mission_doc
    from py_src.utils import doc_probe, file_finder, utils, utils_connector, thread_pool

    for module in (doc_probe, file_finder, utils_connector):
        assert_source(module, module_root)
    app = QCoreApplication.instance() or QCoreApplication([])
    connector = utils_connector.UtilsConnector()
    requests = itertools.count()

    def run_import(paths, suf_type, recursive=False):
        event_key = f"<<fileImportRegression-{next(requests)}>>"
        completed = Event()
        events = []

        def on_complete(imported, issues):
            events.append((imported, issues))
            completed.set()

        PubSubService.subscribe(event_key, on_complete)
        try:
            started = time.monotonic()
            connector.asynFindFiles(paths, suf_type, recursive, event_key, "", 0)
            assert time.monotonic() - started < 0.5, "启动扫描阻塞了调用线程"
            wait_for(app, completed)
            assert thread_pool.GlobalThreadPool.waitForDone(5000), "扫描 runnable 尚未结束"
            app.processEvents()
            assert len(events) == 1, f"扫描产生了 {len(events)} 次终态"
            imported, issues = events[0]
            assert isinstance(imported, list) and isinstance(issues, list)
            assert all(set(issue) == {"kind", "path", "message"} for issue in issues), issues
            return imported, issues
        finally:
            PubSubService.unsubscribe(event_key, on_complete)

    with tempfile.TemporaryDirectory(prefix="umi-file-import-data-") as temp_dir:
        root = Path(temp_dir) / "图片 空格目录"
        nested = root / "子目录"
        empty = root / "空目录"
        nested.mkdir(parents=True)
        empty.mkdir()
        top_image = root / "顶部 图片.PNG"
        nested_image = nested / "child.webp"
        unsupported = root / "ignored.txt"
        missing = root / "missing.png"
        top_image.write_bytes(b"top")
        nested_image.write_bytes(b"nested")
        unsupported.write_text("not an image", encoding="utf-8")

        dropped = utils.QUrl2String([QUrl.fromLocalFile(str(root)), QUrl.fromLocalFile(str(missing))])
        assert [Path(path).resolve() for path in dropped] == [root.resolve(), missing.resolve()]
        normalized = lambda path: str(path.resolve()).replace("\\", "/")
        assert file_finder.findFiles([str(root)], "image", False) == [normalized(top_image)]
        assert file_finder.findFiles([str(root)], "image", True) == [normalized(top_image), normalized(nested_image)]
        imported, issues = run_import([str(root), str(unsupported), str(missing)], "image", True)
        assert imported == [normalized(top_image), normalized(nested_image)]
        by_kind = {issue["kind"]: issue for issue in issues}
        assert by_kind["unsupported"]["path"] == normalized(unsupported)
        assert by_kind["missing"]["path"] == normalized(missing)
        imported, issues = run_import([str(empty)], "image", True)
        assert not imported and [issue["kind"] for issue in issues] == ["empty"]

        # 无效输入、空输入、扫描异常也必须有且仅有一次双参数终态。
        for paths, suffix in ((None, "doc"), ("not-a-list", "doc"), ([], "unknown"), ([], None)):
            imported, issues = run_import(paths, suffix)
            assert not imported and issues[0]["kind"] == "invalid", issues
        assert run_import([], "doc") == ([], [])
        with patch.object(file_finder, "_scanFiles", side_effect=RuntimeError("受控枚举异常")):
            imported, issues = run_import([str(root)], "doc", True)
        assert not imported and issues[0]["kind"] == "scanerror", issues

        documents = create_documents(data_root, Path(temp_dir) / "文档 空格目录")
        # 父线程旧入口一旦被调用就失败；真正的探测只能发生在新子进程中。
        with patch.object(mission_doc.MissionDOC, "getDocInfo", side_effect=AssertionError("父线程不能读取文档元信息")), patch.object(mission_doc.FitzOpen, "__enter__", side_effect=AssertionError("父线程不能打开 fitz")):
            imported, issues = run_import([str(documents["root"])], "doc", False)
            by_path = {item["path"]: item for item in imported}
            assert set(by_path) == {normalized(documents["plain"]), normalized(documents["encrypted"])}
            assert by_path[normalized(documents["plain"])]["page_count"] == 2
            locked = by_path[normalized(documents["encrypted"])]
            assert locked["page_count"] == 3 and locked["is_encrypted"] and not locked["is_authenticate"]
            assert len(issues) == 2 and all(issue["kind"] == "unreadable" for issue in issues), issues
            assert {issue["path"] for issue in issues} == {normalized(documents["invalid"]), normalized(documents["root"] / "零字节.pdf")}, issues

            imported, issues = run_import(
                [str(documents["root"]), str(documents["unsupported"]), str(documents["missing"]), str(documents["empty"])],
                "doc", True,
            )
            assert {item["path"] for item in imported} == {normalized(documents[key]) for key in ("plain", "encrypted", "nested")}
            assert {issue["kind"] for issue in issues} == {"unreadable", "unsupported", "missing", "empty"}, issues
            imported, issues = run_import([None, str(documents["plain"])], "doc")
            assert len(imported) == 1 and issues[0]["kind"] == "unreadable", issues

            def partial_scan(_paths, _suffixes, _recursive, add_file):
                add_file(str(documents["plain"]))
                raise RuntimeError("枚举到一份文档后失败")

            with patch.object(file_finder, "_scanFiles", partial_scan):
                imported, issues = run_import([str(documents["root"])], "doc", True)
            assert len(imported) == 1 and issues[0]["kind"] == "scanerror", (imported, issues)
            with patch.object(file_finder, "probe_documents", side_effect=RuntimeError("受控 worker 通信异常")):
                imported, issues = run_import([str(documents["plain"])], "doc")
            assert not imported and issues[0]["kind"] == "workererror", issues
            with patch.object(doc_probe, "_WORKER_BOOTSTRAP", "import os; os._exit(25)"):
                imported, issues = run_import([str(documents["plain"])], "doc")
            assert not imported and issues[0]["kind"] == "workererror", issues
            real_probe = doc_probe.probe_documents
            with patch.object(doc_probe, "_WORKER_BOOTSTRAP", "import sys,time; sys.stdin.buffer.read(); time.sleep(60)"), patch.object(
                file_finder, "probe_documents", lambda paths: real_probe(paths, timeout=0.15)
            ):
                imported, issues = run_import([str(documents["plain"])], "doc")
            assert not imported and issues[0]["kind"] == "timeout", issues

        # 线程池拒绝调度和报错后晚到的 runnable 都不能让 UI 票据悬空或重复结算。
        for starts_first in (False, True):
            event_key = f"<<fileImportScheduleFailure-{next(requests)}>>"
            events = []
            pending = []

            def schedule_then_fail(task, *task_args):
                if starts_first:
                    task(*task_args)
                else:
                    pending.append(lambda: task(*task_args))
                raise RuntimeError("受控调度失败")

            def capture(*event_args):
                events.append(event_args)

            PubSubService.subscribe(event_key, capture)
            try:
                with patch.object(utils_connector, "threadRun", schedule_then_fail):
                    connector.asynFindFiles([], "doc", False, event_key, "", 0)
                for task in pending:
                    task()
                app.processEvents()
                assert len(events) == 1 and len(events[0]) == 2, events
                if not starts_first:
                    assert events[0][1][0]["kind"] == "scanerror", events
            finally:
                PubSubService.unsubscribe(event_key, capture)

    assert thread_pool.GlobalThreadPool.waitForDone(5000)
    assert "fitz" not in sys.modules and "pymupdf" not in sys.modules, "文件扫描在父进程导入了解析库"
    del connector, app, handles
    print(f"文件导入{'包' if args.packaged else '源码'}回归通过：图片/文档目录、中文路径、加密件、可见故障及所有分支的唯一终态。")


if __name__ == "__main__":
    main()
