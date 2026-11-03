"""从只读依赖种子和锁定 Qt wheel 生成全新富预览运行时，不修改原安装。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def plain(path):
    path = Path(path).absolute()
    for node in (path, *path.parents):
        if node.is_symlink() or node.is_junction():
            raise ValueError("运行时路径不能经过链接：" + str(node))
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, action="append", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    seed, output, report = map(plain, (args.seed, args.output, args.report))
    output.relative_to(ROOT / "build/staging")
    if output.exists(): raise FileExistsError(output)
    lock = (ROOT / "build/requirements-base-windows.lock").read_text(encoding="utf-8")
    inputs = []
    for raw in args.wheel:
        wheel = plain(raw)
        package = wheel.name.split("-", 1)[0].replace("_", "-")
        match = re.search(re.escape(package) + r"==6\.11\.2\s*\\\s*\n\s*--hash=sha256:([a-f0-9]{64})", lock, re.I)
        checksum = hashlib.file_digest(wheel.open("rb"), "sha256").hexdigest()
        if not match or match[1] != checksum:
            raise ValueError("Qt wheel 不符合本项目锁：" + str(wheel))
        inputs.append({"path": str(wheel), "sha256": checksum})
    data = output / "UmiOCR-data"
    data.mkdir(parents=True)
    for name in ("runtime", "site-packages"):
        shutil.copytree(seed / "UmiOCR-data" / name, data / name)
    shutil.copy2(seed / "UmiOCR-data/qt-runtime-whitelist.json", data / "qt-runtime-whitelist.json")
    for item in inputs:
        with zipfile.ZipFile(item["path"]) as archive:
            for entry in archive.infolist():
                relative = PurePosixPath(entry.filename)
                if relative.is_absolute() or ".." in relative.parts or "\\" in entry.filename or ":" in entry.filename or stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError("不安全的 wheel 成员：" + entry.filename)
                if entry.is_dir(): continue
                target = data / "site-packages" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
    result = {"seed": str(seed), "output": str(output), "qtVersion": "6.11.2", "inputs": inputs,
              "sourceSeedChanged": False, "modelDownloaded": False,
              "boundary": "新目录内恢复锁定 Qt 模块，后续按当前白名单重新裁剪；不是最终包验收。"}
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
