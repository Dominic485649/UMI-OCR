"""分块来源/归档协议的真实临时Git与文件回归，不联网、不运行模型。"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "build/tools" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


chunks = load("chunks_regression", "chunked_files.py")
gates = load("chunks_gate_regression", "release_gate_inputs.py")


class ChunkedFilesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="source-chunks-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "canonical"
        (self.source / "third_party").mkdir(parents=True)
        (self.source / "build.py").write_text("# 合成源码，不执行\n", encoding="utf-8")
        self.payload = bytes(range(256)) * 16
        self.archive = self.source / "third_party/runtime.tar.xz"
        self.archive.write_bytes(self.payload)
        self.expected = {name: chunks.layout.sha256_file(path) for name, path in chunks.layout.tree_files(self.source).items()}
        self.mirror = self.root / "public"
        self.result = chunks.encode_sources(self.source, self.mirror, threshold=1024, part_bytes=512)
        self.index = self.result["index"]

    def git(self, *arguments):
        completed = subprocess.run(["git", "-C", str(self.mirror), *arguments], capture_output=True, check=True)
        return completed.stdout.decode("utf-8").strip()

    def commit(self):
        if not (self.mirror / ".git").exists():
            self.git("init", "-b", "main")
            self.git("config", "user.name", "Source protocol fixture")
            self.git("config", "user.email", "fixture@example.invalid")
            self.git("config", "core.autocrlf", "false")
        self.git("add", "--all")
        self.git("commit", "-m", "合成来源协议回归输入")
        return self.git("rev-parse", "HEAD")

    def overwrite_index(self, index):
        (self.mirror / chunks.SOURCE_INDEX).write_text(json.dumps(index), encoding="utf-8")

    def test_source_roundtrip_and_no_implicit_overwrite(self):
        result = chunks.restore(self.mirror, self.index, "source")
        self.assertEqual(len(result), 1)
        self.assertEqual((self.mirror / "third_party/runtime.tar.xz").read_bytes(), self.payload)
        self.assertEqual(self.archive.read_bytes(), self.payload)
        with self.assertRaises(ValueError):
            chunks.restore(self.mirror, self.index, "source")

    def test_real_git_logical_sources_equal_original_bytes(self):
        commit = self.commit()
        gates.git_source_matches(self.mirror, commit, self.expected)
        self.assertNotIn("third_party/runtime.tar.xz", self.git("ls-tree", "-r", "--name-only", commit).splitlines())

    def test_git_line_ending_conversion_is_not_silently_accepted(self):
        self.commit()
        self.git("config", "core.autocrlf", "true")
        self.git("add", "--renormalize", ".")
        self.git("commit", "-m", "合成换行转换输入")
        with self.assertRaises(ValueError):
            gates.git_source_matches(self.mirror, self.git("rev-parse", "HEAD"), self.expected)

    def test_real_git_extra_member_fails(self):
        (self.mirror / "unexpected.py").write_text("# 多余源码\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            gates.git_source_matches(self.mirror, self.commit(), self.expected)

    def test_real_git_changed_chunk_fails(self):
        part = self.mirror / self.index["files"][0]["parts"][0]["path"]
        content = bytearray(part.read_bytes())
        content[0] ^= 1
        part.write_bytes(content)
        with self.assertRaises(ValueError):
            gates.git_source_matches(self.mirror, self.commit(), self.expected)

    def test_real_git_missing_index_does_not_fall_back(self):
        (self.mirror / chunks.SOURCE_INDEX).unlink()
        with self.assertRaises(ValueError):
            gates.git_source_matches(self.mirror, self.commit(), self.expected)

    def test_real_git_missing_chunk_fails(self):
        (self.mirror / self.index["files"][0]["parts"][0]["path"]).unlink()
        with self.assertRaises(ValueError):
            gates.git_source_matches(self.mirror, self.commit(), self.expected)

    def test_legacy_plain_git_still_verifies_exact_bytes(self):
        self.mirror = self.source
        gates.git_source_matches(self.mirror, self.commit(), self.expected)

    def test_other_commit_or_canonical_hash_fails(self):
        commit = self.commit()
        expected = dict(self.expected)
        expected["third_party/runtime.tar.xz"] = "0" * 64
        with self.assertRaises(ValueError):
            gates.git_source_matches(self.mirror, commit, expected)
        with self.assertRaises(ValueError):
            gates.git_source_matches(self.mirror, "0" * 40, self.expected)

    def test_invalid_order_size_bool_path_and_unknown_fields_fail(self):
        for kind in ("order", "size", "bool", "path", "unknown", "purpose", "digest"):
            with self.subTest(kind=kind):
                value = copy.deepcopy(self.index)
                item = value["files"][0]
                if kind == "order":
                    item["parts"].reverse()
                elif kind == "size":
                    item["bytes"] += 1
                elif kind == "bool":
                    item["parts"][0]["bytes"] = True
                elif kind == "path":
                    item["path"] = "../outside.tar.xz"
                elif kind == "unknown":
                    value["ignore_missing"] = True
                elif kind == "purpose":
                    value["format"] = "umi-archive-chunks-v1"
                else:
                    item["sha256"] = "A" * 64
                with self.assertRaises((ValueError, chunks.layout.LayoutError)):
                    chunks.validate_index(value, "source")

    def test_duplicate_json_keys_fail(self):
        with self.assertRaises(ValueError):
            chunks.parse_index(b'{"schema_version":1,"schema_version":1}', "source")

    def test_corrupt_chunk_leaves_no_restored_or_partial_file(self):
        part = self.mirror / self.index["files"][0]["parts"][0]["path"]
        part.write_bytes(b"x" * part.stat().st_size)
        with self.assertRaises(ValueError):
            chunks.restore(self.mirror, self.index, "source")
        self.assertFalse((self.mirror / "third_party/runtime.tar.xz").exists())
        self.assertEqual(list((self.mirror / "third_party").glob("*.partial")), [])

    def test_ordinary_large_code_cannot_be_hidden_as_source_archive(self):
        (self.source / "huge.py").write_bytes(b"x" * 2048)
        destination = self.root / "invalid-mirror"
        with self.assertRaises(ValueError):
            chunks.encode_sources(self.source, destination, threshold=1024, part_bytes=512)
        self.assertFalse(destination.exists())

    def test_existing_mirror_and_hard_link_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            chunks.encode_sources(self.source, self.mirror)
        linked = self.source / "linked.tar.xz"
        try:
            os.link(self.archive, linked)
        except OSError as error:
            self.skipTest("测试环境不支持硬链接：" + str(error))
        with self.assertRaises(chunks.layout.LayoutError):
            chunks.encode_sources(self.source, self.root / "linked-mirror", threshold=1024, part_bytes=512)

    def test_archive_byte_split_and_restore_to_separate_root(self):
        output, restored = self.root / "volumes", self.root / "restored"
        output.mkdir()
        restored.mkdir()
        record = chunks.split_file(self.archive, output, "product.tar.xz", "archive", 700)
        document = {"schema_version": 1, "format": "umi-archive-chunks-v1", "files": [record]}
        chunks.write_index(output / chunks.ARCHIVE_INDEX, document, "archive")
        result = chunks.restore(output, chunks.read_index(output / chunks.ARCHIVE_INDEX, "archive"), "archive", restored)
        self.assertEqual((restored / "product.tar.xz").read_bytes(), self.payload)
        self.assertEqual(result[0]["sha256"], chunks.layout.sha256_file(self.archive))
        with self.assertRaises(ValueError):
            chunks.validate_index(document, "source")


if __name__ == "__main__":
    unittest.main()
