"""获取锁定 Qt WebEngine 对应源码并只读提取许可，不执行归档中的任何代码。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--licenses", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    work, licenses, report = [path.absolute() for path in (args.work, args.licenses, args.report)]
    for path in (work, licenses, report):
        path.relative_to(ROOT)
        if any(node.is_symlink() or node.is_junction() for node in (path, *path.parents)): raise ValueError("拒绝链接路径")
    if work.exists(): raise FileExistsError(work)
    work.mkdir(parents=True)
    licenses.mkdir(parents=True, exist_ok=True)
    spec = next(asset for asset in json.loads((ROOT / "build/sources-windows-cu126.lock.json").read_text("utf-8"))["thirdPartySources"] if asset.get("component") == "QtWebEngine")
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
    records, size = [], 0
    target = licenses / "third-party-notices.zip"
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as output:
        with tarfile.open(archive_path, "r|xz") as archive:
            for member in archive:
                if not member.isfile(): continue
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or "\\" in member.name or ":" in member.name: raise ValueError("非法源码成员")
                upper = path.name.upper()
                if not (any(word in upper for word in ("LICENSE", "LICENCE", "COPYING", "NOTICE")) or path.name == "qt_attribution.json"): continue
                if member.size > 2 * 1024 * 1024: continue
                content = archive.extractfile(member).read()
                size += len(content)
                if size > 64 * 1024 * 1024: raise ValueError("许可清单超出预算")
                output.writestr(path.as_posix(), content)
                records.append({"path": path.as_posix(), "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    if len(records) < 100: raise ValueError("源码中的许可清单不完整")
    payload = {"component": "QtWebEngine", "version": "6.11.2", "source": spec, "resolvedDownload": resolved,
               "archiveSha256": checksum, "noticeFiles": records, "noticeBytes": size,
               "noticeZipSha256": hashlib.sha256(target.read_bytes()).hexdigest(),
               "executedDownloadedCode": False, "sourceModified": False,
               "boundary": "官方同版完整源码归档及其许可集合；使用官方未修改 wheel，不声明自行重建 Chromium。"}
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    report.write_text(serialized, encoding="utf-8")
    (licenses / "manifest.json").write_text(serialized, encoding="utf-8")
    (licenses / "README.md").write_text("# Qt WebEngine 6.11.2 / Chromium 许可与源码\n\n使用锁定 PySide6 6.11.2 官方 wheel 的未修改动态库与 QtWebEngineProcess，保留 Chromium 沙箱。Qt/PySide 使用其开放许可选择；完整 LGPL/GPL 文本在上级 LICENSES。Chromium 及第三方材料不能仅凭 Qt 的许可替代。\n\n同版官方完整源码归档随产品保留在 source/third_party/qtwebengine-everywhere-src-6.11.2.tar.xz；SHA-256 与下载 URL 见 manifest.json。third-party-notices.zip 从该归档只读提取 LICENSE、COPYING、NOTICE 和 qt_attribution.json，保留原始路径与字节，不执行来源脚本。\n\n此记录不声称自行重建 Qt/Chromium，也不替代各组件实际许可条件。构建和源文件恢复入口、锁定 wheel 与输入摘要随产品对应源码保留。\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "sourceBytes": total, "licenseFiles": len(records), "noticeBytes": size, "sha256": checksum}, ensure_ascii=False))


if __name__ == "__main__": main()
