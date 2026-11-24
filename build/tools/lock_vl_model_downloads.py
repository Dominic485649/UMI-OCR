"""锁定官方模型直链；只获取元数据及小型配置文件，不下载模型权重。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

REPOSITORIES = {
    "gguf": ("PaddlePaddle/PaddleOCR-VL-1.6-GGUF", "511b09642bb324401f15f97cc23bc67e8f0a291d"),
    "layout": ("PaddlePaddle/PP-DocLayoutV3", "241f8bdfc77a7c7bee915a5057aaee58c235a8d3"),
}


def fetch(url, limit):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Umi-OCR-model-lock/1"}), timeout=30) as response:
        if response.status != 200 or not response.geturl().startswith("https://"):
            raise ValueError("官方来源未返回完整 HTTPS 响应")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("元数据或配置超过大小限制；不下载权重")
        return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not args.output.parent.is_dir():
        raise ValueError("输出须为已有父目录内的新文件")
    resources = {}
    for group, (repository, revision) in REPOSITORIES.items():
        metadata = json.loads(fetch(f"https://huggingface.co/api/models/{repository}/revision/{revision}?blobs=true", 2 * 1024**2))
        if metadata["sha"] != revision or metadata.get("cardData", {}).get("license") != "apache-2.0":
            raise ValueError("模型来源版本或许可声明偏离预期")
        siblings = {item["rfilename"]: item for item in metadata["siblings"]}
        selected = (["PaddleOCR-VL-1.6-GGUF.gguf", "PaddleOCR-VL-1.6-GGUF-mmproj.gguf"] if group == "gguf"
                    else ["inference.json", "inference.pdiparams", "inference.yml"])
        files = []
        for name in selected:
            item = siblings[name]
            url = f"https://huggingface.co/{repository}/resolve/{revision}/{name}"
            lfs = item.get("lfs", {})
            if lfs.get("sha256"):
                checksum, size = lfs["sha256"], lfs["size"]
            else:
                data = fetch(url, 2 * 1024**2)
                checksum, size = hashlib.sha256(data).hexdigest(), len(data)
                if item["size"] != size:
                    raise ValueError("官方小型配置长度不匹配")
            files.append({"name": name, "url": url, "bytes": size, "sha256": checksum})
        if group == "gguf":
            for resource_id, title, item in zip(("paddlevl-main", "paddlevl-mmproj"), ("PaddleOCR-VL 1.6 主 GGUF", "PaddleOCR-VL 1.6 视觉投影 GGUF"), files):
                resources[resource_id] = {"title": title, "kind": "file", "destination": item["name"], "files": [item]}
        else:
            resources["paddlevl-layout"] = {"title": "PP-DocLayoutV3 版面模型", "kind": "directory", "destination": "PP-DocLayoutV3", "files": files}
    args.output.write_text(json.dumps(resources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "resources": list(resources), "weightsDownloaded": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
