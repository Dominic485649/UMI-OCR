"""获取锁定 Qt WebEngine 对应源码并只读提取许可，不执行归档中的任何代码。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SELECTION_POLICY = "legal-file-names-v3-locked-legal-wrappers"
LEGAL_WRAPPER_PREFIX = "qtwebengine-everywhere-src-6.11.2/src/3rdparty/chromium/"
# 这些锁定成员实际承载许可正文，不是界面/生成器代码；不得仅按后缀丢弃。
LEGAL_WRAPPERS = {LEGAL_WRAPPER_PREFIX + name: checksum for name, checksum in {
    "third_party/catapult/tracing/third_party/oboe/src/LICENCE.js": "35bee2539adcac2b8b518a651bd7ccd9eeff56a790ac459b70244753fc970f93",
    "third_party/protobuf/src/google/protobuf/compiler/notices.h": "b47ca1ea743623d50c6e02faa136dea4f6574a98e200666f859dbf57fb491721",
    "third_party/sqlite/src/ext/wasm/api/sqlite3-license-version-header.js": "1e2f489cf39222f715e8c92e4bf9b42281b998c65e84631947ea1184da29f512",
    "third_party/ply/license.patch": "d6c873c08a8806f08fdafe1aa00ba38837f6ac29f91d6b26510614b0df2001e0",
    "third_party/rust/chromium_crates_io/patches/symphonia/0101-add-symphonia-license.patch": "e71c26e3a29b44c62a0d8fe5c48cdc4bad35f4ad073c04f88ff957460db132c1",
    "third_party/rust/chromium_crates_io/patches/symphonia-bundle-flac/0101-add-license-to-symphonia-flac.patch": "364d53fdf8aa74f23d0cec02b072f49518c4a180f76ac311a9e2bd2226661dab",
    "third_party/rust/chromium_crates_io/patches/symphonia-core/0101-add-license-to-symphonia-core.patch": "da39b7a41d07a6781d57f4e2355b8b272fe38804bc34b0f4e7cbcd35aee418bb",
    "third_party/rust/chromium_crates_io/patches/symphonia-metadata/0101-add-license-to-symphonia-metadata.patch": "e1701438d3bcae399f4940dfad62581976744d6bda7867b75b6dff1e4e01b526",
    "third_party/rust/chromium_crates_io/patches/symphonia-utils-xiph/0101-add-license-to-symphonia-utils-xiph.patch": "be533010818dcf61af9d2359b15c92e5fa64c208269c72aa899e8c36c6520d32",
}.items()}
LEGAL_NAME = re.compile(
    r"(?:^|[._-])(?:LICEN[CS]ES?|COPYING|COPYRIGHT|UNLICENSE)(?:$|[._-])"
    r"|^LicenseRef-|^CopyrightNotice(?:$|[._-])"
    r"|^(?:THIRD[._-]?PARTY[._-]?)?NOTICES?(?:TEXT)?(?:$|[._-])"
    r"|^(?:PATENTS|AUTHORS)(?:$|[._-])",
    re.IGNORECASE,
)
NON_NOTICE_SUFFIXES = {
    ".bat", ".c", ".cc", ".cmd", ".cpp", ".css", ".diff", ".gni", ".gn", ".go",
    ".h", ".hpp", ".ico", ".java", ".jpeg", ".jpg", ".js", ".jsx", ".m", ".md5",
    ".mm", ".patch", ".pl", ".png", ".py", ".rb", ".rs", ".sh", ".sha1", ".sha256",
    ".svg", ".ts", ".tsx", ".webp", ".xml",
}


def is_notice_file(path):
    """匹配法律文件名，不将 measurement_notice.ts 等界面资源当成许可。"""
    name, suffix = path.name, path.suffix.lower()
    if name == "qt_attribution.json" or path.as_posix() in LEGAL_WRAPPERS:
        return True
    if suffix in NON_NOTICE_SUFFIXES or name.lower() == "readme.rs-third-party-license-review.md":
        return False
    if suffix in {".html", ".htm", ".json"} and not name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "COPYRIGHT")):
        return False
    return bool(LEGAL_NAME.search(name)) or suffix in {".license", ".licence"}


def collect_notices(archive_path, target, *, minimum_files=100):
    records, size = [], 0
    names = set()
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as output:
        with tarfile.open(archive_path, "r|xz") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or "\\" in member.name or ":" in member.name:
                    raise ValueError("非法源码成员")
                if not is_notice_file(path):
                    continue
                if path.as_posix() in names:
                    raise ValueError("重复许可成员")
                names.add(path.as_posix())
                if member.size > 2 * 1024 * 1024:
                    raise ValueError("单项许可超出预算，不静默丢弃")
                with archive.extractfile(member) as incoming:
                    content = incoming.read()
                expected = LEGAL_WRAPPERS.get(path.as_posix())
                if expected and hashlib.sha256(content).hexdigest() != expected:
                    raise ValueError("特殊法律正文与锁定原件不符")
                size += len(content)
                if size > 64 * 1024 * 1024:
                    raise ValueError("许可清单超出预算")
                output.writestr(path.as_posix(), content)
                records.append({"path": path.as_posix(), "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    if len(records) < minimum_files:
        raise ValueError("源码中的许可清单不完整")
    return records, size


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--licenses", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, help="复用本项目已锁定的完整源码缓存，不重复下载")
    args = parser.parse_args()
    work, licenses, report = [path.absolute() for path in (args.work, args.licenses, args.report)]
    for path in (work, licenses, report):
        path.relative_to(ROOT)
        if any(node.is_symlink() or node.is_junction() for node in (path, *path.parents)): raise ValueError("拒绝链接路径")
    if work.exists(): raise FileExistsError(work)
    for output in (report, licenses / "manifest.json", licenses / "README.md", licenses / "third-party-notices.zip"):
        if output.exists():
            raise FileExistsError("拒绝改写既有来源/许可记录：" + str(output))
    work.mkdir(parents=True)
    licenses.mkdir(parents=True, exist_ok=True)
    spec = next(asset for asset in json.loads((ROOT / "build/sources-windows-cu126.lock.json").read_text("utf-8"))["thirdPartySources"] if asset.get("component") == "QtWebEngine")
    if args.source_archive:
        archive_path = args.source_archive.absolute()
        archive_path.relative_to(ROOT / "build")
        if any(node.is_symlink() or node.is_junction() for node in (archive_path, *archive_path.parents)):
            raise ValueError("拒绝链接源码路径")
        if not archive_path.is_file() or archive_path.name != spec["name"]:
            raise ValueError("复用输入必须是锁定的完整源码归档")
        resolved, total = None, archive_path.stat().st_size
    else:
        archive_path = work / spec["name"]
        with urllib.request.urlopen(spec["url"], timeout=120) as response, archive_path.open("xb") as stream:
            resolved = response.geturl()
            total = 0
            while chunk := response.read(4 * 1024 * 1024):
                total += len(chunk)
                if total > spec["size"]: raise ValueError("源码归档超出锁定大小")
                stream.write(chunk)
    with archive_path.open("rb") as stream: checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    if archive_path.stat().st_size != spec["size"] or checksum != spec["sha256"]: raise ValueError("Qt 源码不符合官方输入锁")
    cached = ROOT / "build/cache/sources" / spec["name"]
    if cached.exists():
        with cached.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != checksum: raise ValueError("既有源码缓存不同，拒绝覆盖")
    else: shutil.copy2(archive_path, cached)
    target = licenses / "third-party-notices.zip"
    records, size = collect_notices(archive_path, target)
    payload = {"component": "QtWebEngine", "version": "6.11.2", "source": spec, "resolvedDownload": resolved,
               "sourceInput": str(archive_path), "reusedLockedArchive": bool(args.source_archive),
               "selectionPolicy": SELECTION_POLICY,
               "archiveSha256": checksum, "noticeFiles": records, "noticeBytes": size,
               "noticeZipSha256": hashlib.sha256(target.read_bytes()).hexdigest(),
               "executedDownloadedCode": False, "sourceModified": False,
               "boundary": "官方同版完整源码归档及其许可集合；使用官方未修改 wheel，不声明自行重建 Chromium。"}
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    report.write_text(serialized, encoding="utf-8")
    (licenses / "manifest.json").write_text(serialized, encoding="utf-8")
    (licenses / "README.md").write_text("# Qt WebEngine 6.11.2 / Chromium 许可与源码\n\n使用锁定 PySide6 6.11.2 官方 wheel 的未修改动态库与 QtWebEngineProcess，保留 Chromium 沙箱。Qt/PySide 使用其开放许可选择；完整 LGPL/GPL 文本在上级 LICENSES。Chromium 及第三方材料不能仅凭 Qt 的许可替代。\n\n同版官方完整源码归档位于独立对应源码材料的 third_party/qtwebengine-everywhere-src-6.11.2.tar.xz（完整构建树为 source/third_party/）；SHA-256 与官方 URL 见 manifest.json。third-party-notices.zip 从该锁定归档只读提取法律文件及 qt_attribution.json，保留原始路径与字节，不执行来源脚本。筛选不再按文件名包含 notice 等子串，界面源码、生成器脚本、图片和哈希旁文件不作为法律文本附送。少数以注释、C++ raw string 或许可补丁承载的原始法律正文按精确路径和 SHA-256 保留，不仅凭扩展名删除许可。\n\n此记录不声称自行重建 Qt/Chromium，也不替代各组件实际许可条件。构建和源文件恢复入口、锁定 wheel 与输入摘要随独立对应源码保留。\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "sourceBytes": total, "licenseFiles": len(records), "noticeBytes": size, "sha256": checksum}, ensure_ascii=False))


if __name__ == "__main__": main()
