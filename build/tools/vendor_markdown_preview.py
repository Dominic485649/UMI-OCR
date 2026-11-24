"""核验并复制锁定的离线预览资源，不执行 npm 生命周期或解包源码。"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def plain(path):
    path = Path(path).absolute()
    for node in (path, *path.parents):
        if node.is_symlink() or node.is_junction():
            raise ValueError("路径不能经过链接：" + str(node))
    path.relative_to(ROOT)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="只复用哈希相同的已有输入，不覆盖冲突文件")
    args = parser.parse_args()
    cache, output, sources = map(plain, (args.cache, args.output, args.sources))
    if not args.resume and any(path.exists() for path in (cache, output, sources)):
        raise FileExistsError("下载、资源和来源目录必须全新")
    lock_path = ROOT / "build/markdown-preview.lock.json"
    lock = json.loads(lock_path.read_text("utf-8"))
    for path in (cache, output, sources): path.mkdir(parents=True, exist_ok=args.resume)
    def write_verified(path, content):
        if path.exists():
            if not args.resume or path.read_bytes() != content:
                raise FileExistsError("拒绝覆盖冲突文件：" + str(path))
        else:
            with path.open("xb") as stream: stream.write(content)
    records = []
    for spec in lock["packages"]:
        name = spec["name"]
        download_dir = cache / name
        download_dir.mkdir(exist_ok=args.resume)
        archive_path = download_dir / (spec["url"].rsplit("/", 1)[-1])
        if not archive_path.exists():
            with urllib.request.urlopen(spec["url"], timeout=90) as response, archive_path.open("xb") as stream:
                if response.geturl() != spec["url"]:
                    raise ValueError("来源发生未审查重定向")
                size = 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 32 * 1024 * 1024: raise ValueError("来源归档超出预算")
                    stream.write(chunk)
        with archive_path.open("rb") as stream:
            digest = base64.b64encode(hashlib.file_digest(stream, "sha512").digest()).decode()
        if "sha512-" + digest != spec["integrity"]:
            raise ValueError("来源哈希不符：" + name)
        material = sources / name
        material.mkdir(exist_ok=args.resume)
        write_verified(material / archive_path.name, archive_path.read_bytes())
        files, licenses = {}, set()
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or "\\" in member.name or ":" in member.name or member.issym() or member.islnk():
                    raise ValueError("不安全来源成员：" + member.name)
                if not member.isfile(): continue
                if path.parts[0] != "package": raise ValueError("未知 npm 归档根")
                relative = PurePosixPath(*path.parts[1:]).as_posix()
                target = spec["files"].get(relative)
                if relative.startswith(spec.get("fontPrefix", "\x00")) and path.suffix == ".woff2":
                    target = "fonts/" + path.name
                license_name = relative if relative in spec["licenses"] else None
                if not target and not license_name: continue
                if member.size > 8 * 1024 * 1024: raise ValueError("来源文件超出预算")
                content = archive.extractfile(member).read()
                if license_name:
                    write_verified(material / Path(license_name).name, content)
                    licenses.add(license_name)
                if target:
                    destination = output / target
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    write_verified(destination, content)
                    files[target] = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
        if set(spec["files"].values()) - files.keys() or set(spec["licenses"]) - licenses:
            raise ValueError("来源缺少约定资源／许可：" + name)
        records.append({**spec, "files": files, "archiveSha256": hashlib.sha256(archive_path.read_bytes()).hexdigest()})
    shutil.copy2(lock_path, sources / lock_path.name)
    (sources / "manifest.json").write_text(json.dumps({"packages": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    (sources / "README.md").write_text("# 离线 Markdown 预览来源\n\n原始 npm 归档及各自许可证保留于本目录；运行时仅加载 qt_res/preview/vendor 中的核验资源，不访问 CDN。\n\n版本、SHA-512 输入锁与运行资源 SHA-256 见 manifest.json。未执行包内脚本；使用 build/tools/vendor_markdown_preview.py 可从锁定输入重建。KaTeX 字体来自同版发行归档，遵守其附带许可。\n", encoding="utf-8")
    print(json.dumps({"sources": str(sources), "output": str(output), "packages": len(records),
                      "runtimeBytes": sum(item["bytes"] for record in records for item in record["files"].values())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
