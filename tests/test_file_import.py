import argparse
import sys
import tempfile
import time
from pathlib import Path
from threading import Event


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime


def wait_for(app, event):
    deadline = time.monotonic() + 10
    while not event.is_set() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert event.is_set(), "asynchronous file import timed out"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    handles = configure_runtime(data_root)

    from PySide6.QtCore import QCoreApplication, QUrl
    from py_src.event_bus.pubsub_service import PubSubService
    from py_src.utils import file_finder, utils
    from py_src.utils.utils_connector import UtilsConnector

    app = QCoreApplication.instance() or QCoreApplication([])
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "dropped-folder"
        nested = root / "nested"
        empty = root / "empty"
        nested.mkdir(parents=True)
        empty.mkdir()
        top_image = root / "top.PNG"
        nested_image = nested / "child.webp"
        unsupported = root / "ignored.txt"
        missing = root / "missing.png"
        top_image.write_bytes(b"top")
        nested_image.write_bytes(b"nested")
        unsupported.write_text("not an image", encoding="utf-8")

        dropped = utils.QUrl2String(
            [QUrl.fromLocalFile(str(root)), QUrl.fromLocalFile(str(missing))]
        )
        assert [Path(path).resolve() for path in dropped] == [root.resolve(), missing.resolve()]
        assert file_finder.findFiles([str(root)], "image", False) == [
            str(top_image.resolve()).replace("\\", "/")
        ]
        assert file_finder.findFiles([str(root)], "image", True) == [
            str(top_image.resolve()).replace("\\", "/"),
            str(nested_image.resolve()).replace("\\", "/"),
        ]

        completed = Event()
        imported = {}
        event_key = "<<fileImportRegression>>"

        def on_complete(paths, issues):
            imported["paths"] = paths
            imported["issues"] = issues
            completed.set()

        PubSubService.subscribe(event_key, on_complete)
        try:
            connector = UtilsConnector()
            started = time.monotonic()
            connector.asynFindFiles(
                [str(root), str(unsupported), str(missing)],
                "image",
                True,
                event_key,
                "",
                0,
            )
            assert time.monotonic() - started < 0.5
            wait_for(app, completed)
        finally:
            PubSubService.unsubscribe(event_key, on_complete)

        assert imported["paths"] == [
            str(top_image.resolve()).replace("\\", "/"),
            str(nested_image.resolve()).replace("\\", "/"),
        ]
        issues = {issue["kind"]: issue for issue in imported["issues"]}
        assert issues["unsupported"]["path"] == str(unsupported.resolve()).replace(
            "\\", "/"
        )
        assert issues["missing"]["path"] == str(missing.resolve()).replace("\\", "/")

        empty_paths = []
        empty_issues = []

        def on_empty(paths, issues):
            empty_paths.extend(paths)
            empty_issues.extend(issues)

        # The synchronous worker helper publishes directly on the main thread.
        PubSubService.subscribe("<<emptyFileImportRegression>>", on_empty)
        try:
            file_finder.asynFindFiles(
                [str(empty)], "image", True, "<<emptyFileImportRegression>>", "", 0
            )
        finally:
            PubSubService.unsubscribe("<<emptyFileImportRegression>>", on_empty)
        assert not empty_paths
        assert [issue["kind"] for issue in empty_issues] == ["empty"]

    del app, handles
    print("File import regression passed: folder URLs, recursive images, unsupported and missing paths.")


if __name__ == "__main__":
    main()
