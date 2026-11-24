"""Generate the release component notice from locked wheel metadata."""

import argparse
import email.parser
import json
import re
from pathlib import Path


LOCK_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_packages(path):
    packages = []
    for line in path.read_text("utf-8").splitlines():
        match = LOCK_RE.match(line.strip())
        if match:
            packages.append((match.group(1), match.group(2)))
    return packages


def metadata_index(site_packages):
    result = {}
    for directory in site_packages.glob("*.dist-info"):
        path = directory / "METADATA"
        if not path.is_file():
            continue
        metadata = email.parser.Parser().parsestr(path.read_text("utf-8", errors="replace"))
        name = metadata.get("Name")
        if name:
            result[normalize(name)] = (directory, metadata)
    return result


def license_text(metadata):
    expression = (metadata.get("License-Expression") or "").strip()
    if expression and expression.upper() != "UNKNOWN":
        return " ".join(expression.split())
    value = (metadata.get("License") or "").strip()
    if value and value.upper() != "UNKNOWN" and len(value) <= 200:
        return " ".join(value.split())
    classifiers = [
        item.removeprefix("License :: ")
        for item in metadata.get_all("Classifier", [])
        if item.startswith("License :: ")
    ]
    if classifiers:
        return "; ".join(classifiers)
    if value and value.upper() != "UNKNOWN":
        return "See bundled license text"
    return "UNKNOWN - release blocker"


def source_url(name, version, metadata):
    preferred = ("source", "repository", "homepage", "home")
    project_urls = []
    for value in metadata.get_all("Project-URL", []):
        label, separator, url = value.partition(",")
        if separator:
            project_urls.append((label.strip().lower(), url.strip()))
    for key in preferred:
        for label, url in project_urls:
            if key in label:
                return url
    return metadata.get("Home-page") or f"https://pypi.org/project/{name}/{version}/"


def notice_files(directory):
    paths = []
    for path in directory.rglob("*"):
        if path.is_file() and any(token in path.name.lower() for token in ("license", "copying", "notice")):
            paths.append(path.relative_to(directory.parent).as_posix())
    return ", ".join(sorted(paths)) or "wheel metadata only"


def escape(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def section(title, lock_path, site_packages):
    index = metadata_index(site_packages)
    rows = []
    missing = []
    for name, version in locked_packages(lock_path):
        item = index.get(normalize(name))
        if not item:
            missing.append(f"{name}=={version}")
            continue
        directory, metadata = item
        installed_version = metadata.get('Version')
        displayed_version = version
        source = source_url(name, version, metadata)
        if installed_version != version:
            markers = [directory / marker for marker in ('UMI_RUNTIME_PROFILE.json', 'UMI_RUNTIME_SUBSET.json') if (directory / marker).is_file()]
            if len(markers) != 1:
                raise RuntimeError(f'{name}: installed version differs from its input lock without an explicit derived profile')
            derived = json.loads(markers[0].read_text('utf-8'))
            if (not installed_version or installed_version.split('+', 1)[0] != version
                    or derived.get('version') != installed_version):
                raise RuntimeError(f'{name}: derived version/profile does not match the upstream input pin')
            displayed_version = f'{installed_version}（派生；原始输入锁：{version}）'
            source = derived.get('sourceUrl') or source
        rows.append(
            "| {name} | {version} | {license} | {source} | {notices} |".format(
                name=escape(name),
                version=escape(displayed_version),
                license=escape(license_text(metadata)),
                source=escape(source),
                notices=escape(notice_files(directory)),
            )
        )
    if missing:
        raise RuntimeError(f"{title}: missing dist-info for {', '.join(missing)}")
    return "\n".join(
        [
            f"## {title}",
            "",
            "| Component | Version | License metadata | Source | Included notice files |",
            "| --- | --- | --- | --- | --- |",
            *rows,
        ]
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-lock", type=Path)
    parser.add_argument("--gpu-lock", type=Path)
    parser.add_argument("--base-site-packages", type=Path)
    parser.add_argument("--gpu-site-packages", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    sections = []
    for title, lock_path, site_packages in (
        ("Base package", args.base_lock, args.base_site_packages),
        ("GPU OCR plugin", args.gpu_lock, args.gpu_site_packages),
    ):
        if bool(lock_path) != bool(site_packages):
            parser.error(f"{title}: lock and site-packages must be provided together")
        if lock_path:
            sections.append(section(title, lock_path, site_packages))
    if not sections:
        parser.error("at least one package closure is required")

    output = "\n\n".join(
        [
            "# Locked Third-Party Components\n\n"
            "Generated from the release locks and the installed wheel metadata. "
            "`UNKNOWN - release blocker` is not permission to redistribute.",
            *sections,
        ]
    )
    args.output.write_text(output + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
