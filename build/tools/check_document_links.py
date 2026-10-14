"""Inventory and check repository HTTP links without crawling external sites.

No dependencies are installed. Local/example/template URLs are recorded, not
requested. Network failures and future release targets never count as PASS.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {".md", ".txt", ".json", ".py", ".qml", ".ps1", ".yaml", ".yml", ".html"}
PREFIXES = ("docs/", "UmiOCR-data/", ".github/", "build/tools/", "build/windows/", "LICENSES/")
EXCLUDED_PARTS = {
    "vendor", "models", "site-packages", "runtime", "cache", "staging", "artifacts",
    "audit", "logs", "evidence", "release", "__pycache__", "$tmp", "temp_doc",
    ".claude", ".codex", ".agents", "claude.md", "codex.md", "agents.md", "gemini.md",
}
URL_RE = re.compile(r'https?://[^\s<>"\'`\x00-\x1f　-￿]+')


def files(root):
    output = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
    ).decode("utf-8")
    for relative in sorted(set(output.split("\0"))):
        path = root / relative
        parts = Path(relative).parts
        if not relative or not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part.casefold() in EXCLUDED_PARTS for part in parts):
            continue
        if len(parts) > 1 and not relative.startswith(PREFIXES):
            continue
        if path.stat().st_size > 2 * 1024 * 1024:
            continue
        yield relative, path


def normalize(raw):
    url = raw.rstrip(".,;:!?")
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    while url.endswith("]") and url.count("]") > url.count("["):
        url = url[:-1]
    return url


def classify(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return "LOCAL_EXAMPLE"
    if not parsed.hostname or parsed.hostname in {"example.com", "example.org", "www.example.com"}:
        return "PLACEHOLDER"
    if any(token in url for token in ("${", "{", "}", "<", ">", "[", "]", "...", "%s", "%d")):
        return "TEMPLATE"
    return "EXTERNAL"


def inspect(url, timeout):
    request_url = urllib.parse.urldefrag(url)[0]
    opener = urllib.request.build_opener()
    request = urllib.request.Request(
        request_url,
        headers={"User-Agent": "Umi-OCR-documentation-check/3.0 (read-only link verification)"},
        method="HEAD",
    )
    status = None
    final_url = request_url
    try:
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in {405, 501}:
                raise
            response = opener.open(
                urllib.request.Request(request_url, headers=request.headers, method="GET"), timeout=timeout
            )
        with response:
            status = response.status
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
        result = "HTTP_OK" if 200 <= status < 400 else "HTTP_ERROR"
        # A successful HEAD says nothing about target content or login gates.
        return {"result": result, "status": status, "final_url": final_url, "content_type": content_type,
                "content_verified": False}
    except urllib.error.HTTPError as exc:
        status = exc.code
        result = "ACCESS_RESTRICTED" if status in {401, 403, 429} else "HTTP_ERROR"
        return {"result": result, "status": status, "final_url": exc.geturl(), "error": str(exc),
                "content_verified": False}
    except Exception as exc:
        return {"result": "NETWORK_UNVERIFIED", "status": status, "final_url": final_url,
                "error": f"{type(exc).__name__}: {exc}", "content_verified": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=12)
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    references = {}
    scanned = 0
    for relative, path in files(root):
        scanned += 1
        for number, line in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
            for match in URL_RE.finditer(line):
                url = normalize(match.group())
                references.setdefault(url, []).append({"file": relative, "line": number})
    external = sorted(url for url in references if classify(url) == "EXTERNAL")
    outcomes = {}
    if not args.inventory_only:
        # Deduplicate fragments to avoid probing one external endpoint repeatedly.
        request_urls = sorted({urllib.parse.urldefrag(url)[0] for url in external})
        with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 4))) as pool:
            outcomes = dict(zip(request_urls, pool.map(lambda url: inspect(url, args.timeout), request_urls)))
    entries = []
    for url in sorted(references):
        kind = classify(url)
        entry = {"url": url, "kind": kind, "references": references[url]}
        if kind == "EXTERNAL":
            entry.update(outcomes.get(urllib.parse.urldefrag(url)[0], {"result": "NOT_REQUESTED"}))
            if "github.com/Dominic485649/UMI-OCR_plugins" in url or "/releases/tag/v3.0.0" in url:
                entry["publication_target"] = True
                if entry.get("status") == 404:
                    entry["result"] = "PENDING_PUBLICATION"
        else:
            entry["result"] = "NOT_REQUESTED"
        entries.append(entry)
    counts = {}
    for entry in entries:
        counts[entry["result"]] = counts.get(entry["result"], 0) + 1
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "First-party current source, maintained docs, metadata and notice text; no vendor/cache/artifacts/raw evidence crawl",
        "scanned_files": scanned,
        "unique_urls": len(entries),
        "counts": counts,
        "all_links_verified": False,
        "limitations": [
            "HTTP_OK records response availability only, not correct content, anchors, image data or an existing release asset.",
            "Local examples and dynamic/template URLs are inventoried without requests.",
            "Raw historical HTML evidence, runtime binaries, models, caches and generated products are excluded.",
            "Expected future publication targets remain pending until publication, even if their parent page responds.",
        ],
        "links": entries,
    }
    output = args.output.resolve()
    if not output.parent.is_dir():
        raise RuntimeError(f"Output parent must already exist: {output.parent}")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"scanned_files": scanned, "unique_urls": len(entries), "counts": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
