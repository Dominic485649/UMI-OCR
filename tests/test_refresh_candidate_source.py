"""旧源码刷新入口必须无副作用；回归本身也禁止目录访问与真实进程启动。"""

import builtins
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "build/tools/refresh_candidate_source.py"
# 在启用 I/O 围栏前只读取本次要测试的可信脚本，不导入旧模块。
SCRIPT_CODE = compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec")


def execute_guarded(*, name="__main__", argv=(), call_main=False, code=SCRIPT_CODE):
    """用内存 fixture 执行入口，源码回归成旧实现时也不能触达真实产物。"""
    stdout, stderr = io.StringIO(), io.StringIO()
    namespace = {"__name__": name, "__file__": str(SCRIPT), "__package__": None}
    original_import = builtins.__import__

    def forbidden(*args, **kwargs):
        raise AssertionError("已停用入口不能访问文件系统或启动进程")

    def import_sys_only(module_name, *args, **kwargs):
        if module_name != "sys":
            raise AssertionError("已停用入口不能导入执行依赖: " + module_name)
        return original_import(module_name, *args, **kwargs)

    guards = (
        (builtins, ("open",)),
        (Path, ("open", "read_text", "read_bytes", "write_text", "write_bytes", "resolve",
                "exists", "is_file", "is_dir", "stat", "iterdir", "glob", "rglob",
                "mkdir", "unlink", "rmdir", "rename", "replace")),
        (os, ("open", "stat", "lstat", "listdir", "scandir", "walk", "chdir", "mkdir",
              "makedirs", "remove", "unlink", "rmdir", "rename", "replace", "system")),
        (shutil, ("rmtree", "copy", "copy2", "copytree", "move")),
        (subprocess, ("Popen", "run", "call", "check_call", "check_output")),
    )
    exit_code = None
    with ExitStack() as stack:
        stack.enter_context(redirect_stdout(stdout))
        stack.enter_context(redirect_stderr(stderr))
        stack.enter_context(patch.object(sys, "argv", [str(SCRIPT), *argv]))
        for module, attributes in guards:
            for attribute in attributes:
                stack.enter_context(patch.object(module, attribute, side_effect=forbidden))
        # 最后启用导入围栏，最先还原，避免影响测试框架本身的清理。
        stack.enter_context(patch.object(builtins, "__import__", new=import_sys_only))
        try:
            exec(code, namespace)
            if call_main:
                exit_code = namespace["main"](list(argv))
        except SystemExit as exc:
            exit_code = exc.code
    return namespace, exit_code, stdout.getvalue(), stderr.getvalue()


class RefreshCandidateSourceTests(unittest.TestCase):
    def assert_disabled(self, result):
        _, exit_code, stdout, stderr = result
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("REFRESH_DISABLED", stderr)
        self.assertIn("Build-Release.ps1", stderr)
        self.assertIn("Build-GpuPlugin.ps1", stderr)

    def test_import_has_no_io_output_or_argument_parsing(self):
        before_path = list(sys.path)
        namespace, exit_code, stdout, stderr = execute_guarded(
            name="retired_refresh_fixture", argv=("--unknown-option",)
        )
        self.assertIsNone(exit_code)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        self.assertTrue(callable(namespace["main"]))
        self.assertEqual(sys.path, before_path)

    def test_default_entrypoint_refuses_to_refresh(self):
        self.assert_disabled(execute_guarded())

    def test_programmatic_entrypoint_refuses_to_refresh(self):
        self.assert_disabled(execute_guarded(name="retired_refresh_fixture", call_main=True))

    def test_legacy_targets_are_never_inspected(self):
        targets = (
            r"..\Umi-OCR-Plugin",
            r"D:\outside-project\candidate",
            r"build\artifacts\281-merged\complete",
            r"build\artifacts\281-merged-prefix-collision",
            r"\\untrusted-server\share\candidate",
            "../linked-candidate",
        )
        for target in targets:
            with self.subTest(target=target):
                self.assert_disabled(execute_guarded(argv=("--merged-root", target)))

    def test_force_and_apply_cannot_enable_refresh(self):
        for argv in (("--force",), ("--apply",), ("--merged-root", "candidate", "--force")):
            with self.subTest(argv=argv):
                self.assert_disabled(execute_guarded(argv=argv))

    def test_help_is_read_only(self):
        for option in ("-h", "--help"):
            with self.subTest(option=option):
                _, exit_code, stdout, stderr = execute_guarded(argv=(option,))
                self.assertEqual(exit_code, 0)
                self.assertIn("REFRESH_DISABLED", stdout)
                self.assertIn("全新的构建目录", stdout)
                self.assertEqual(stderr, "")

    def test_help_with_other_arguments_does_not_enable_refresh(self):
        self.assert_disabled(execute_guarded(argv=("--help", "--merged-root", "candidate")))

    def test_guard_blocks_file_reads(self):
        code = compile("open('must-not-be-opened')", "<read-guard-fixture>", "exec")
        with self.assertRaisesRegex(AssertionError, "文件系统"):
            execute_guarded(code=code)

    def test_guard_blocks_old_execution_dependencies(self):
        code = compile("from pathlib import Path", "<import-guard-fixture>", "exec")
        with self.assertRaisesRegex(AssertionError, "pathlib"):
            execute_guarded(code=code)

    def test_guard_blocks_deletion_and_process_launch(self):
        operations = (
            "import sys; sys.modules['shutil'].rmtree('must-not-be-deleted')",
            "import sys; sys.modules['subprocess'].run(['must-not-be-launched'])",
        )
        for source in operations:
            with self.subTest(source=source):
                code = compile(source, "<mutation-guard-fixture>", "exec")
                with self.assertRaisesRegex(AssertionError, "文件系统"):
                    execute_guarded(code=code)


if __name__ == "__main__":
    unittest.main()
