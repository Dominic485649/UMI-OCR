"""Offline checks for release identity, attribution and About-page targets."""

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST = "https://github.com/Dominic485649/UMI-OCR"
PLUGINS = "https://github.com/Dominic485649/UMI-OCR_plugins"
UPSTREAM = "https://github.com/hiroi-sora/Umi-OCR"
CONTACT = "https://qm.qq.com/q/5XHoXCOU26"


def verify(root: Path, expected_version: str):
    data = root / "UmiOCR-data"
    about = json.loads((data / "about.json").read_text(encoding="utf-8"))
    version = about["version"]
    actual = ".".join(str(version[key]) for key in ("major", "minor", "patch"))
    assert actual == expected_version, (actual, expected_version)
    assert not version["prerelease"], "This release must not be a prerelease"
    assert version["prereleaseNumber"] == 0

    targets = {
        "home": HOST,
        "plugins": PLUGINS,
        "release": HOST + "/releases",
        "pluginsRelease": PLUGINS + "/releases",
        "upstream": UPSTREAM,
        "contact": CONTACT,
        "issue": HOST + "/issues",
        "newIssue": HOST + "/issues/new/choose",
    }
    for key, expected in targets.items():
        assert about["url"][key] == expected, (key, about["url"].get(key))

    authors = {entry["name"]: entry["url"] for entry in about["authors"]}
    assert authors["Dominic485649"] == "https://github.com/Dominic485649"
    assert authors["hiroi-sora"] == "https://github.com/hiroi-sora"
    assert about["license"]["type"] == "AGPL-3.0-or-later"
    assert "Copyright (c) 2023 hiroi-sora" in (root / "LICENSE").read_text(encoding="utf-8")

    qml = (data / "qt_res/qml/TabPages/About/About.qml").read_text(encoding="utf-8")
    referenced = set(re.findall(r"UmiAbout\.url\.(\w+)", qml))
    assert {"release", "pluginsRelease", "contact", "upstream"} <= referenced
    assert referenced <= set(about["url"]), "About page refers to undefined URL metadata"

    cuda = json.loads(
        (data / "plugins/win32_PaddleOCRv6_CUDA/umi-plugin.json").read_text(encoding="utf-8")
    )
    assert cuda["version"] == actual, "Host and CUDA product versions must match"
    assert cuda["homepage"] in {HOST, PLUGINS}, "CUDA homepage must belong to this fork"
    assert cuda["runtime"]["process_boundary"]["type"] == "separate-worker-stdio-ipc"
    assert cuda["runtime"]["vendor_dirs"] == [], "The host must not mount Paddle vendor dependencies"
    assert cuda["runtime"]["dll_dirs"] == [], "The host must not mount NVIDIA DLL directories"
    assert "3.0" not in re.findall(
        r'HOST_API_VERSION\s*=\s*[\"\']([^\"\']+)',
        (data / "py_src/plugins_controller/host_api.py").read_text(encoding="utf-8"),
    ), "Changing the product major must not accidentally change the host contract major"

    print(f"Release metadata checks passed: {actual}; both authors; own project/plugin/contact targets.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--version", default="3.0.1")
    args = parser.parse_args()
    verify(args.repo_root.resolve(), args.version)
