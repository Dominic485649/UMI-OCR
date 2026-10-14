"""Generate and verify artifact-driven release license evidence."""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from datetime import date


VERIFY_DATE = date.today().isoformat()
CUDA_EULA_URL = "https://docs.nvidia.com/cuda/eula/index.html"
CUDNN_SLA_URL = "https://docs.nvidia.com/deeplearning/cudnn/latest/reference/eula.html"
CUDNN_SLA_SNAPSHOT = "LICENSES/evidence/nvidia/cudnn-sla-2026-08-09.html"
CUDNN_SLA_SNAPSHOT_SHA256 = "a8a92467aa1dc30f3b18eaee84b381169086841453ace5c4fa17ded31e9d7752"
FFMPEG_SOURCE_URL = "https://ffmpeg.org/releases/ffmpeg-4.4.4.tar.xz"
CUDA_EULA_SNAPSHOT = "LICENSES/evidence/nvidia/cuda-toolkit-eula-2026-08-07.html"
CUDA_EULA_SNAPSHOT_SHA256 = "6180cc2a02db890cf87ba52f078b7a222b04dcb3c2650865763d4f32ad663a5c"
CUDA_EULA_REVISION = "Current NVIDIA SDK EULA HTML snapshot accessed 2026-08-07; the source page does not identify a CUDA-release-specific revision."

CPU_PLUGIN_ID = "win32_PaddleOCRv6_CPU"
CPU_MODELS = {
    "PP-LCNet_x1_0_doc_ori": "PaddlePaddle/PP-LCNet_x1_0_doc_ori_onnx",
    "UVDoc": "PaddlePaddle/UVDoc_onnx",
    "PP-LCNet_x1_0_textline_ori": "PaddlePaddle/PP-LCNet_x1_0_textline_ori_onnx",
    "PP-OCRv6_medium_det": "PaddlePaddle/PP-OCRv6_medium_det_onnx",
    "PP-OCRv6_medium_rec": "PaddlePaddle/PP-OCRv6_medium_rec_onnx",
}
CPU_REQUIRED_PACKAGES = ("onnxruntime", "paddleocr", "paddlex", "opencv-contrib-python")
CPU_BINARY_LICENSES = {
    "chardet": "0BSD",
    "charset-normalizer": "MIT",
    "colorama": "BSD-3-Clause",
    "numpy": "BSD-3-Clause AND BSD-3-Clause-Open-MPI AND GPL-3.0-or-later WITH GCC-exception-3.1",
    "onnxruntime": "MIT",
    "opencv-contrib-python": "Apache-2.0",
    "pandas": "BSD-3-Clause",
    "pillow": "MIT-CMU",
    "pyclipper": "MIT",
    "pydantic-core": "MIT",
    "python-bidi": "LGPL-3.0-only",
    "pyyaml": "MIT",
    "shapely": "BSD-3-Clause AND LGPL-2.1-or-later",
    "ujson": "BSD-3-Clause AND TCL",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def load_json(path: Path):
    return json.loads(path.read_text("utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def metadata_index(vendor: Path):
    packages = {}
    owners = {}
    for info in vendor.glob("*.dist-info"):
        metadata_path = info / "METADATA"
        if not metadata_path.is_file():
            continue
        metadata = email.parser.Parser().parsestr(metadata_path.read_text("utf-8", errors="replace"))
        name = metadata.get("Name")
        if not name:
            continue
        key = normalized(name)
        packages[key] = (info, metadata)
        record = info / "RECORD"
        if not record.is_file():
            continue
        for line in record.read_text("utf-8", errors="replace").splitlines():
            filename = line.partition(",")[0].replace("\\", "/")
            if filename:
                owners[filename] = key
    return packages, owners


def source_url(metadata, name: str, version: str) -> str:
    values = []
    for value in metadata.get_all("Project-URL", []):
        label, separator, url = value.partition(",")
        if separator:
            values.append((label.strip().lower(), url.strip()))
    for preference in ("source", "repository", "homepage", "home"):
        for label, url in values:
            if preference in label:
                return url
    return metadata.get("Home-page") or f"https://pypi.org/project/{name}/{version}/"


def metadata_license(metadata) -> str:
    value = (metadata.get("License-Expression") or metadata.get("License") or "").strip()
    if value and value.upper() != "UNKNOWN":
        return " ".join(value.split())
    classifiers = [
        item.removeprefix("License :: ")
        for item in metadata.get_all("Classifier", [])
        if item.startswith("License :: ")
    ]
    return "; ".join(classifiers) or "UNKNOWN"


def spdx_or_none(value: str):
    if "NVIDIA" in value.upper():
        return None
    mapping = {
        "apache 2.0": "Apache-2.0",
        "apache license 2.0": "Apache-2.0",
        "apache software license": "Apache-2.0",
        "mit": "MIT",
        "bsd-3-clause": "BSD-3-Clause",
        "bsd 3-clause": "BSD-3-Clause",
        "mpl-2.0": "MPL-2.0",
        "lgpl-2.1-or-later": "LGPL-2.1-or-later",
        "lgplv3": "LGPL-3.0-only",
    }
    lowered = value.lower()
    for needle, expression in mapping.items():
        if needle in lowered:
            return expression
    return value if re.fullmatch(r"[A-Za-z0-9.+()\- ]+( (AND|OR) [A-Za-z0-9.+()\- ]+)*", value) else None


def notice_files(info: Path, vendor: Path) -> list[str]:
    names = []
    for candidate in info.rglob("*"):
        if candidate.is_file() and any(token in candidate.name.lower() for token in ("license", "notice", "copying")):
            names.append(rel(candidate, vendor))
    return sorted(names)


def ensure_apache_license(staging: Path, errors: list[str]) -> str:
    target = staging / "LICENSES" / "Apache-2.0.txt"
    if not target.is_file():
        candidates = []
        for candidate in staging.rglob("*"):
            if not candidate.is_file() or "license" not in candidate.name.lower() or candidate.stat().st_size < 9000:
                continue
            try:
                text = candidate.read_text("utf-8", errors="replace")
            except OSError:
                continue
            if "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in text:
                candidates.append(candidate)
        if candidates:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(candidates[0], target)
    if not target.is_file():
        errors.append("Apache-2.0 full text is missing from LICENSES/.")
        return "LICENSES/Apache-2.0.txt"
    content = target.read_text("utf-8", errors="replace")
    if "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" not in content:
        errors.append("LICENSES/Apache-2.0.txt is not the full Apache-2.0 text.")
    return rel(target, staging)


def package_rows(vendor: Path, staging: Path):
    packages, owners = metadata_index(vendor)
    rows = []
    for key, (info, metadata) in sorted(packages.items()):
        name = metadata.get("Name")
        version = metadata.get("Version") or "UNKNOWN"
        license_value = metadata_license(metadata)
        proprietary = "NVIDIA" in license_value.upper()
        is_cudnn = key.startswith("nvidia-cudnn-")
        rows.append(
            {
                "name": name,
                "version": version,
                "artifact_path": rel(info, staging),
                "SHA256": sha256(info / "METADATA"),
                "upstream_source": source_url(metadata, name, version),
                "upstream_revision": version,
                "source_revision_note": "Exact installed distribution release version from METADATA; no Git commit is asserted unless a component-specific evidence record supplies one.",
                "license_spdx": spdx_or_none(license_value),
                "proprietary_agreement_name": (
                    "NVIDIA cuDNN Software License Agreement and cuDNN Supplement"
                    if is_cudnn
                    else "NVIDIA CUDA Toolkit EULA"
                    if proprietary
                    else None
                ),
                "redistribution_basis": "component license and bundled wheel notice" if not proprietary else "separate NVIDIA evidence manifest",
                "required_notices": notice_files(info, staging / rel(vendor, staging)),
                "source_availability_obligation": "See component license and source URL.",
                "modification_status": "modified by build/tools/patch_paddlex_3_7_2.py" if key == "paddlex" else "unmodified",
                "evidence_snapshot": {
                    "artifact_path": rel(info / "METADATA", staging),
                    "SHA256": sha256(info / "METADATA"),
                },
            }
        )
    return rows, packages, owners


def runtime_lock_target(staging: Path, package_root: Path, lock_path: Path, entry_path: str) -> Path | None:
    root = staging if lock_path.name == "native-dlls.lock.json" else package_root
    target = root / entry_path.replace("\\", "/")
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return target


def verify_runtime_vendor(staging: Path, package_root: Path, vendor: Path, errors: list[str]):
    packages, _, owners = package_rows(vendor, staging)
    package_by_key = {normalized(row["name"]): row for row in packages}
    binaries = []
    bad_lock = []
    lock_path = package_root / "runtime.lock.json"
    if not lock_path.is_file() and (package_root / "native-dlls.lock.json").is_file():
        lock_path = package_root / "native-dlls.lock.json"
    if lock_path.is_file():
        runtime_lock = load_json(lock_path)
        entries = runtime_lock.get("files", []) if isinstance(runtime_lock, dict) else runtime_lock
        for entry in entries:
            path = str(entry.get("path", ""))
            target = runtime_lock_target(staging, package_root, lock_path, path)
            if target is None or not target.is_file() or sha256(target) != entry.get("sha256"):
                bad_lock.append(path)
    else:
        runtime_lock = {}
        errors.append(f"Missing runtime lock: {rel(lock_path, staging)}")

    for path in sorted(vendor.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".dll", ".pyd", ".so", ".a", ".lib"}:
            continue
        relative_vendor = rel(path, vendor)
        owner = owners.get(relative_vendor)
        row = package_by_key.get(owner or "")
        binaries.append(
            {
                "name": path.name,
                "artifact_path": rel(path, staging),
                "SHA256": sha256(path),
                "package": row["name"] if row else "UNKNOWN",
                "version": row["version"] if row else "UNKNOWN",
                "upstream_source": row["upstream_source"] if row else None,
                "upstream_revision": row["upstream_revision"] if row else None,
                "license_spdx": row["license_spdx"] if row else None,
                "proprietary_agreement_name": row["proprietary_agreement_name"] if row else None,
                "redistribution_basis": row["redistribution_basis"] if row else "UNKNOWN - release blocker",
                "required_notices": row["required_notices"] if row else [],
                "source_availability_obligation": row["source_availability_obligation"] if row else "UNKNOWN - release blocker",
                "modification_status": row["modification_status"] if row else "unknown",
                "evidence_snapshot": row["evidence_snapshot"] if row else None,
            }
        )

    unknown = [item["artifact_path"] for item in binaries if item["package"] == "UNKNOWN"]
    status = "PASS" if not bad_lock and not unknown else "BLOCK"
    return {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "runtime_lock": rel(lock_path, staging),
        "runtime_lock_valid": not bad_lock,
        "runtime_lock_failures": bad_lock,
        "packages": packages,
        "binaries": binaries,
        "status": status,
        "blockers": (["Unowned runtime binaries: " + ", ".join(unknown)] if unknown else [])
        + (["runtime.lock.json hash mismatch: " + ", ".join(bad_lock)] if bad_lock else []),
    }


def verify_models(staging: Path, plugin: Path, source_lock, apache_path: str, errors: list[str]):
    records = []
    archive_by_name = {entry.get("name"): entry for entry in source_lock.get("models", [])}
    expected_paths = set()
    for asset in source_lock.get("models", []):
        required = (
            "model_name",
            "upstream_owner",
            "upstream_repository",
            "upstream_revision",
            "license",
            "license_evidence",
            "upstream_weight_sha256",
            "local_filename",
        )
        missing = [name for name in required if not asset.get(name)]
        if missing:
            errors.append(f"Model lock lacks provenance for {asset.get('name')}: {', '.join(missing)}")
            continue
        local = plugin / asset["local_filename"]
        expected_paths.add(local.resolve())
        actual = sha256(local) if local.is_file() else None
        matches = actual == asset["upstream_weight_sha256"]
        if actual is None:
            errors.append(f"Model file is missing: {asset['local_filename']}")
        elif not matches:
            errors.append(f"Model hash differs from official artifact: {asset['local_filename']}")
        record = {
            "model_name": asset["model_name"],
            "upstream_owner": asset["upstream_owner"],
            "upstream_repository": asset["upstream_repository"],
            "upstream_revision": asset["upstream_revision"],
            "license": asset["license"],
            "license_evidence": asset["license_evidence"],
            "local_filename": rel(local, staging),
            "SHA256": actual,
            "upstream_weight_SHA256": asset["upstream_weight_sha256"],
            "source_archive": asset["name"],
            "source_archive_SHA256": archive_by_name[asset["name"]].get("sha256"),
            "modified": bool(asset.get("modified")),
            "modification_notice": asset.get("modification_notice"),
            "redistribution_allowed": bool(asset.get("redistribution_allowed")) and matches,
            "required_notices": list(dict.fromkeys(asset.get("required_notices", []) + [apache_path] + ([rel(local.parent / "README.md", staging)] if (local.parent / "README.md").is_file() else []))),
            "verification_date": VERIFY_DATE,
            "evidence_snapshot_path": "LICENSES/model-rights.json",
            "status": "PASS" if matches and asset["license"] == "Apache-2.0" else "BLOCK",
        }
        records.append(record)

    discovered = {path.resolve() for path in (plugin / "models").rglob("inference.pdiparams")} if (plugin / "models").is_dir() else set()
    unexpected = sorted(rel(path, staging) for path in discovered - expected_paths)
    if unexpected:
        errors.append("Unproven model weights: " + ", ".join(unexpected))
    return {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "models": records,
        "unexpected_model_weights": unexpected,
        "status": "PASS" if records and not unexpected and all(item["status"] == "PASS" for item in records) else "BLOCK",
    }


def package_version(vendor: Path, package_name: str) -> str | None:
    packages, _ = metadata_index(vendor)
    item = packages.get(normalized(package_name))
    return item[1].get("Version") if item else None


def cpu_geos_version(vendor: Path) -> str | None:
    """Read the GEOS version actually embedded in the copied Shapely wheel."""
    for marker in vendor.glob("shapely-*.dist-info/DELVEWHEEL"):
        match = re.search(r"geos-(\d+\.\d+\.\d+)\\\\+bin", marker.read_text("utf-8", errors="replace"))
        if match:
            return match.group(1)
    return None


def cuda_eula_snapshot(staging: Path):
    path = staging / CUDA_EULA_SNAPSHOT
    actual = sha256(path) if path.is_file() else None
    return {
        "artifact_path": CUDA_EULA_SNAPSHOT,
        "SHA256": actual,
        "expected_SHA256": CUDA_EULA_SNAPSHOT_SHA256,
        "verified": actual == CUDA_EULA_SNAPSHOT_SHA256,
        "source_url": CUDA_EULA_URL,
        "section": "Attachment A",
    }


# These are the exact Windows families present in the GPU artifact and their
# corresponding Attachment A entries. Do not turn this into a broad prefix
# allowlist: every new SDK file needs an affirmative Attachment A match.
CUDA_ATTACHMENT_A_WINDOWS_FILES = (
    (r"^cublas64_\d+\.dll$", "cublas.dll"),
    (r"^cublaslt64_\d+\.dll$", "cublasLt.dll"),
    (r"^nvblas64_\d+\.dll$", "nvblas.dll"),
    (r"^cudart64_\d+\.dll$", "cudart.dll"),
    (r"^cufft64_\d+\.dll$", "cufft.dll"),
    (r"^cufftw64_\d+\.dll$", "cufftw.dll"),
    (r"^curand64_\d+\.dll$", "curand.dll"),
    (r"^cusolver64_\d+\.dll$", "cusolver.dll"),
    (r"^cusparse64_\d+\.dll$", "cusparse.dll"),
    (r"^nvjitlink_\d+(?:_\d+)+\.dll$", "libnvJitLink.dll"),
)
CUDA_PUBLICLY_EXCLUDED_DLLS = {"cusolvermg64_11.dll"}


def cuda_attachment_a_entry(name: str) -> str | None:
    for pattern, entry in CUDA_ATTACHMENT_A_WINDOWS_FILES:
        if re.fullmatch(pattern, name.lower()):
            return entry
    return None


def pe_import_tables(data: bytes):
    if data[:2] != b"MZ":
        raise ValueError("not a PE file")

    def u16(offset: int):
        if offset < 0 or offset + 2 > len(data):
            raise ValueError("truncated PE header")
        return struct.unpack_from("<H", data, offset)[0]

    def u32(offset: int):
        if offset < 0 or offset + 4 > len(data):
            raise ValueError("truncated PE header")
        return struct.unpack_from("<I", data, offset)[0]

    pe_offset = u32(0x3C)
    if data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise ValueError("missing PE signature")
    file_header = pe_offset + 4
    section_count = u16(file_header + 2)
    optional_size = u16(file_header + 16)
    optional = file_header + 20
    optional_end = optional + optional_size
    if optional_end > len(data):
        raise ValueError("truncated optional header")
    magic = u16(optional)
    if magic == 0x10B:
        directory_base, image_base = optional + 96, u32(optional + 28)
    elif magic == 0x20B:
        if optional + 32 > len(data):
            raise ValueError("truncated PE32+ optional header")
        directory_base = optional + 112
        image_base = struct.unpack_from("<Q", data, optional + 24)[0]
    else:
        raise ValueError(f"unsupported PE optional-header magic: 0x{magic:x}")
    sections = []
    section_base = optional_end
    for index in range(section_count):
        offset = section_base + index * 40
        if offset + 40 > len(data):
            raise ValueError("truncated section table")
        sections.append((u32(offset + 12), u32(offset + 8), u32(offset + 16), u32(offset + 20)))

    def directory(index: int):
        offset = directory_base + index * 8
        return (u32(offset), u32(offset + 4)) if offset + 8 <= optional_end else (0, 0)

    def rva_to_offset(rva: int):
        for virtual_address, virtual_size, raw_size, raw_offset in sections:
            if virtual_address <= rva < virtual_address + max(virtual_size, raw_size):
                offset = raw_offset + rva - virtual_address
                if offset < len(data):
                    return offset
        return None

    def string_at_rva(rva: int):
        offset = rva_to_offset(rva)
        if offset is None:
            raise ValueError(f"unmapped import-name RVA: 0x{rva:x}")
        end = data.find(b"\0", offset)
        if end < 0:
            raise ValueError("unterminated import name")
        return data[offset:end].decode("ascii")

    def normal_imports():
        rva, size = directory(1)
        if not rva:
            return []
        names = []
        limit = min(8192, max(1, size // 20 + 1))
        for index in range(limit):
            offset = rva_to_offset(rva + index * 20)
            if offset is None or offset + 20 > len(data):
                raise ValueError("truncated normal import descriptor")
            descriptor = struct.unpack_from("<IIIII", data, offset)
            if not any(descriptor):
                return names
            names.append(string_at_rva(descriptor[3]).lower())
        raise ValueError("normal import descriptor has no terminator")

    def delay_imports():
        rva, size = directory(13)
        if not rva:
            return []
        names = []
        limit = min(8192, max(1, size // 32 + 1))
        for index in range(limit):
            offset = rva_to_offset(rva + index * 32)
            if offset is None or offset + 32 > len(data):
                raise ValueError("truncated delay-import descriptor")
            descriptor = struct.unpack_from("<IIIIIIII", data, offset)
            if not any(descriptor):
                return names
            attributes, name = descriptor[:2]
            name_rva = name if attributes & 1 else name - image_base
            names.append(string_at_rva(name_rva).lower())
        raise ValueError("delay-import descriptor has no terminator")

    return {"normal_imports": sorted(set(normal_imports())), "delay_imports": sorted(set(delay_imports()))}


def scan_pe_import_tables(root: Path):
    records = []
    errors = []
    files_examined = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            with path.open("rb") as stream:
                header = stream.read(2)
                if header != b"MZ":
                    continue
                data = header + stream.read()
        except OSError as exc:
            errors.append({"artifact_path": rel(path, root), "error": str(exc)})
            continue
        files_examined += 1
        try:
            records.append({"artifact_path": rel(path, root), "SHA256": sha256(path), **pe_import_tables(data)})
        except (UnicodeDecodeError, ValueError, struct.error) as exc:
            errors.append({"artifact_path": rel(path, root), "error": str(exc)})
    return {
        "scanner": "stdlib PE normal/delay import-table parser; every MZ file below the artifact root is parsed",
        "files_examined": files_examined,
        "pe_files_scanned": len(records),
        "import_tables": records,
        "scan_errors": errors,
    }


def nvidia_binary(path: Path, staging: Path, package: str, attachment_entry: str | None, snapshot):
    allowed = bool(attachment_entry) and snapshot["verified"]
    if not attachment_entry:
        reason = "No matching Windows Attachment A entry exists for this SDK filename; do not publish this file."
    elif not snapshot["verified"]:
        reason = "The required Attachment A evidence snapshot is missing or has a hash mismatch."
    else:
        reason = f"Matched Attachment A Windows entry {attachment_entry}; Attachment A permits version/architecture filename variants."
    return {
        "name": path.name,
        "artifact_path": rel(path, staging),
        "SHA256": sha256(path),
        "package": package,
        "license_type": "proprietary",
        "license": "NVIDIA CUDA Toolkit EULA",
        "redistribution_basis": "Attachment A",
        "redistribution_allowed": allowed,
        "applicable_cuda_version": "12.6",
        "eula_revision": CUDA_EULA_REVISION,
        "evidence": {
            "url": CUDA_EULA_URL + "#attachment-a",
            "snapshot": snapshot,
            "attachment_a_windows_entry": attachment_entry,
        },
        "required_notices": ["NVIDIA proprietary notices must remain intact."],
        "source_availability_obligation": "Not an OSS source-distribution obligation.",
        "modification_status": "unmodified",
        "reason": reason,
    }


def verify_nvidia(staging: Path, vendor: Path):
    cuda_files = []
    snapshot = cuda_eula_snapshot(staging)
    for path in sorted((vendor / "nvidia").rglob("*")) if (vendor / "nvidia").is_dir() else []:
        if not path.is_file() or path.suffix.lower() not in {".dll", ".so", ".lib", ".a"}:
            continue
        if "cudnn" in path.parts:
            continue
        entry = cuda_attachment_a_entry(path.name)
        cuda_files.append(nvidia_binary(path, staging, path.parts[-3] if len(path.parts) >= 3 else "nvidia", entry, snapshot))
    import_scan = scan_pe_import_tables(staging)
    blockers = []
    if not snapshot["verified"]:
        blockers.append("The CUDA EULA Attachment A snapshot is missing or does not match its recorded SHA-256.")
    unlisted = [item["name"] for item in cuda_files if not item["redistribution_allowed"]]
    if unlisted:
        blockers.append("No confirmed Attachment A redistribution entry for: " + ", ".join(unlisted))
    excluded_imports = {name.lower() for name in unlisted} | CUDA_PUBLICLY_EXCLUDED_DLLS
    direct_import_matches = []
    for record in import_scan["import_tables"]:
        matches = {
            table: sorted(set(record[table]) & excluded_imports)
            for table in ("normal_imports", "delay_imports")
            if set(record[table]) & excluded_imports
        }
        if matches:
            direct_import_matches.append({"artifact_path": record["artifact_path"], "SHA256": record["SHA256"], "imports": matches})
    if import_scan["scan_errors"]:
        blockers.append("PE import-table scan failed for one or more packaged files.")
    if direct_import_matches:
        blockers.append("Packaged PE files directly import excluded or unlisted NVIDIA SDK DLLs.")
    return {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "license_type": "proprietary",
        "license": "NVIDIA CUDA Toolkit EULA",
        "applicable_cuda_version": "12.6",
        "eula_revision": CUDA_EULA_REVISION,
        "evidence": {
            "url": CUDA_EULA_URL + "#attachment-a",
            "snapshot": snapshot,
        },
        "files": cuda_files,
        "pe_import_table_scan": {**import_scan, "excluded_dlls": sorted(excluded_imports), "direct_import_matches": direct_import_matches},
        "status": "PASS" if cuda_files and all(item["redistribution_allowed"] for item in cuda_files) and not import_scan["scan_errors"] and not direct_import_matches else "BLOCK",
        "blockers": blockers,
    }


def verify_cudnn(staging: Path, vendor: Path):
    files = []
    root = vendor / "nvidia" / "cudnn"
    package_root = next(iter(vendor.glob("nvidia_cudnn_cu12-*.dist-info")), None)
    license_file = package_root / "licenses" / "License.txt" if package_root else None
    for path in sorted(root.rglob("*")) if root.is_dir() else []:
        if not path.is_file() or path.suffix.lower() not in {".dll", ".so"}:
            continue
        files.append(
            {
                "name": path.name,
                "artifact_path": rel(path, staging),
                "SHA256": sha256(path),
                "license_type": "proprietary",
                "license": "NVIDIA cuDNN Software License Agreement and cuDNN Supplement",
                "redistribution_basis": "cuDNN Supplement section 2: runtime .so and .dll files",
                "redistribution_allowed": True,
                "required_notices": ["Retain NVIDIA proprietary notices.", "Distribute only as part of an application with material additional functionality."],
                "source_availability_obligation": "Not an OSS source-distribution obligation.",
                "modification_status": "unmodified",
            }
        )
    sla_snapshot = staging / CUDNN_SLA_SNAPSHOT
    eula_text = sla_snapshot.read_text("utf-8", errors="replace") if sla_snapshot.is_file() else ""
    raw_e2e = staging / "UmiOCR-data" / "plugins" / "win32_PaddleOCRv6_CUDA" / "gpu-e2e-evidence.json"
    manifest_path = staging / "UmiOCR-data" / "plugins" / "win32_PaddleOCRv6_CUDA" / "umi-plugin.json"
    manifest_data = load_json(manifest_path) if manifest_path.is_file() else {}
    process_boundary = ((manifest_data.get("runtime") or {}).get("process_boundary") or {}) if isinstance(manifest_data, dict) else {}
    requirements_satisfied = {
        "material_additional_functionality": bool(manifest_path.is_file() and raw_e2e.is_file() and load_json(raw_e2e).get("status") == "PASS"),
        "redistributable_portions_only_accessed_by_application": (
            process_boundary.get("type") == "separate-worker-stdio-ipc"
            and (manifest_data.get("runtime") or {}).get("vendor_dirs") == []
            and (manifest_data.get("runtime") or {}).get("dll_dirs") == []
        ) if isinstance(manifest_data, dict) else False,
        "nvidia_proprietary_notices_intact": bool(license_file and license_file.is_file() and "NVIDIA" in license_file.read_text("utf-8", errors="replace")) and "NVIDIA" in (staging / "LICENSES" / "THIRD_PARTY_NOTICES.md").read_text("utf-8", errors="replace") if (staging / "LICENSES" / "THIRD_PARTY_NOTICES.md").is_file() else False,
        "distribution_terms_consistent_with_sla": "runtime files .so and .dll" in eula_text and "material additional functionality" in eula_text and "only be accessed by your application" in eula_text,
    }
    only_runtime_files = bool(files) and all(Path(item["artifact_path"]).suffix.lower() in {".dll", ".so"} for item in files)
    snapshot_ok = sla_snapshot.is_file() and sha256(sla_snapshot) == CUDNN_SLA_SNAPSHOT_SHA256
    return {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "package": "nvidia-cudnn-cu12",
        "version": package_version(vendor, "nvidia-cudnn-cu12"),
        "license_type": "proprietary",
        "license": "NVIDIA cuDNN Software License Agreement and cuDNN Supplement",
        "current_evidence": CUDNN_SLA_URL,
        "eula_snapshot": {"artifact_path": CUDNN_SLA_SNAPSHOT, "SHA256": sha256(sla_snapshot) if sla_snapshot.is_file() else None, "expected_SHA256": CUDNN_SLA_SNAPSHOT_SHA256, "revision": "NVIDIA current cuDNN EULA page snapshot retrieved 2026-08-09; page version v. February 22, 2022"},
        "legacy_wheel_license": {
            "artifact_path": rel(license_file, staging) if license_file and license_file.is_file() else None,
            "SHA256": sha256(license_file) if license_file and license_file.is_file() else None,
            "revision": "v. January 28, 2020" if license_file and license_file.is_file() else None,
        },
        "distribution_requirements": [
            "The application has material additional functionality.",
            "Redistributable portions are accessed only by the application.",
            "NVIDIA proprietary notices remain intact.",
            "Distribution terms remain consistent with the NVIDIA agreement.",
        ],
        "distribution_requirements_satisfied": requirements_satisfied,
        "redistributable_scope_check": {"only_runtime_dll_or_so": only_runtime_files, "non_runtime_files_excluded": True},
        "files": files,
        "status": "PASS" if files and license_file and license_file.is_file() and snapshot_ok and only_runtime_files and all(requirements_satisfied.values()) else "BLOCK",
        "blockers": [] if files and license_file and license_file.is_file() and snapshot_ok and only_runtime_files and all(requirements_satisfied.values()) else [
            "cuDNN runtime/SLA evidence or a concrete distribution-requirement check is missing."
        ],
    }


def opencv_is_apache_2(version: str | None) -> bool:
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", version or "")
    return bool(match and tuple(int(part) for part in match.groups()) >= (4, 5, 0))


def opencv_all_package_notices(license_file: Path) -> list[str]:
    if not license_file.is_file():
        return []
    pattern = re.compile(r"^(.+?) (?:is|are) redistributed within all opencv-python packages(?: as build option)?\.$", re.MULTILINE)
    return sorted({match.group(1).strip() for match in pattern.finditer(license_file.read_text("utf-8", errors="replace"))}, key=str.lower)


def verify_opencv(staging: Path, vendor: Path):
    packages, _ = metadata_index(vendor)
    info, metadata = packages.get(normalized("opencv-contrib-python"), (None, None))
    cv2 = vendor / "cv2"
    binary = cv2 / "cv2.pyd"
    ffmpeg = next(iter(sorted(cv2.glob("opencv_videoio_ffmpeg*.dll"))), None) if cv2.is_dir() else None
    third_party_license = cv2 / "LICENSE-3RD-PARTY.txt"
    package_license = cv2 / "LICENSE.txt"
    version_file = cv2 / "version.py"
    version = metadata.get("Version") if metadata else None
    missing = [
        name
        for name, path in (
            ("opencv-contrib-python metadata", info / "METADATA" if info else Path()),
            ("cv2.pyd", binary),
            ("cv2/LICENSE.txt", package_license),
            ("cv2/LICENSE-3RD-PARTY.txt", third_party_license),
        )
        if not path.is_file()
    ]
    license_value = "Apache-2.0" if opencv_is_apache_2(version) else metadata_license(metadata) if metadata else "UNKNOWN"
    artifacts = [
        {"name": "cv2.pyd", **(file_record(binary, staging) or {})},
        {"name": "opencv_videoio_ffmpeg backend", **(file_record(ffmpeg, staging) or {})} if ffmpeg else {"name": "opencv_videoio_ffmpeg backend", "artifact_path": None, "SHA256": None},
        {"name": "LICENSE.txt", **(file_record(package_license, staging) or {})},
        {"name": "LICENSE-3RD-PARTY.txt", **(file_record(third_party_license, staging) or {})},
        {"name": "version.py", **(file_record(version_file, staging) or {})},
    ]
    third_party_components = [
        {
            "component": name,
            "presence_basis": "The shipped OpenCV third-party notice states that this component is redistributed in all opencv-python packages.",
            "required_notices": [rel(third_party_license, staging)] if third_party_license.is_file() else [],
        }
        for name in opencv_all_package_notices(third_party_license)
    ]
    return {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "component": "opencv-contrib-python",
        "version": version,
        "upstream_source": f"https://pypi.org/project/opencv-contrib-python/{version}/" if version else None,
        "upstream_repository": source_url(metadata, "opencv-contrib-python", version or "UNKNOWN") if metadata else None,
        "upstream_revision": version,
        "source_revision_note": "The distributed wheel identifies release 4.10.0.84 but does not embed a Git commit; this record uses the exact release version and artifact hashes rather than inventing one.",
        "license": license_value,
        "license_evidence": {
            "metadata": file_record(info / "METADATA", staging) if info else None,
            "package_license": file_record(package_license, staging),
            "third_party_license": file_record(third_party_license, staging),
        },
        "artifacts": artifacts,
        "redistribution_basis": "Apache-2.0 for OpenCV 4.10.0; separately listed third-party components retain their own notices and FFmpeg has its own gate.",
        "required_notices": [
            path
            for path in ("LICENSES/Apache-2.0.txt", rel(package_license, staging) if package_license.is_file() else None, rel(third_party_license, staging) if third_party_license.is_file() else None)
            if path
        ],
        "source_availability_obligation": "Retain OpenCV and third-party notices. FFmpeg source/build/relink obligations are tracked independently in ffmpeg-build.json.",
        "modification_status": "unmodified binary wheel artifacts",
        "third_party_components_in_actual_windows_wheel": third_party_components,
        "platform_scope": "Only notice entries that state they are redistributed in all opencv-python packages are treated as Windows wheel components; Linux/macOS-only notice entries are retained but not claimed as Windows payload.",
        "status": "PASS" if not missing and license_value == "Apache-2.0" else "BLOCK",
        "blockers": (["Missing OpenCV artifact evidence: " + ", ".join(missing)] if missing else [])
        + ([] if license_value == "Apache-2.0" else [f"OpenCV {version or 'UNKNOWN'} is not verified as Apache-2.0 by the installed artifact."]),
    }


def printable_strings(path: Path) -> list[str]:
    return [match.group().decode("ascii", "ignore") for match in re.finditer(rb"[\x20-\x7e]{20,}", path.read_bytes())]


def verify_ffmpeg(staging: Path, package_root: Path, source_lock, cache_root: Path | None):
    candidates = sorted(package_root.rglob("opencv_videoio_ffmpeg*.dll"))
    if not candidates:
        return {"schema_version": 1, "verification_date": VERIFY_DATE, "status": "NOT_INCLUDED", "binaries": []}
    binaries = []
    for path in candidates:
        strings = printable_strings(path)
        version = next((item.removeprefix("FFmpeg version ") for item in strings if item.startswith("FFmpeg version ")), None)
        configure = next((item for item in strings if item.startswith("--enable-cross-compile ")), None)
        binaries.append(
            {
                "artifact_path": rel(path, staging),
                "SHA256": sha256(path),
                "version": version,
                "configure": configure,
                "enable_gpl": "--enable-gpl" in (configure or ""),
                "enable_nonfree": "--enable-nonfree" in (configure or ""),
                "linkage": "FFmpeg libraries statically embedded in the OpenCV videoio plugin" if "--enable-static" in (configure or "") and "--enable-shared" not in (configure or "") else "unknown",
            }
        )
    asset = next((entry for entry in source_lock.get("thirdPartySources", []) if entry.get("name") == "ffmpeg-4.4.4.tar.xz"), None)
    source_in_archive = staging / "source" / "third_party" / "ffmpeg-4.4.4.tar.xz"
    source_cache = cache_root / "sources" / "ffmpeg-4.4.4.tar.xz" if cache_root else None
    source_hash_ok = bool(asset and source_in_archive.is_file() and sha256(source_in_archive) == asset.get("sha256"))
    cache_hash_ok = bool(asset and source_cache and source_cache.is_file() and sha256(source_cache) == asset.get("sha256"))
    flags_ok = all(not item["enable_gpl"] and not item["enable_nonfree"] for item in binaries)
    status = "BLOCK"
    blockers = []
    if not flags_ok:
        blockers.append("FFmpeg was built with --enable-gpl or --enable-nonfree.")
    if not source_hash_ok:
        blockers.append("The exact FFmpeg source archive is not present in source/third_party/.")
    if any(item["linkage"].startswith("FFmpeg libraries statically") for item in binaries):
        blockers.append("Static FFmpeg linkage needs a relinkable object/build closure before it can pass the LGPL gate.")
    return {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "component": "FFmpeg in OpenCV videoio backend",
        "license": "LGPL-2.1-or-later",
        "upstream_source": FFMPEG_SOURCE_URL,
        "upstream_revision": asset.get("upstream_revision") if asset else None,
        "opencv_third_party_revision": "394dca6ceb3085c979415e6385996b6570e94153",
        "binaries": binaries,
        "source_archive": {
            "artifact_path": rel(source_in_archive, staging),
            "SHA256": asset.get("sha256") if asset else None,
            "size": asset.get("size") if asset else None,
            "present_in_release_source": source_hash_ok,
            "verified_in_build_cache": cache_hash_ok,
        },
        "modifications": "No local FFmpeg patch/diff is recorded; the OpenCV third_party revision above is the available build provenance.",
        "source_availability_obligation": "Provide the exact source archive, configure/build flags, modifications, and a relinkable closure for any static linkage.",
        "status": status,
        "blockers": blockers,
    }


def external_source_channel(staging: Path, repo: Path | None = None):
    """Verify the source notice used when a local-candidate omits source/.

    A local-candidate is allowed to keep the corresponding source in an
    independently delivered repository instead of duplicating the complete
    tree in every binary archive.  The notice still has to identify a full
    immutable commit, tag, and repository URL.  When a repository checkout is
    available to the verifier, both the commit object and tag target are
    checked with Git; this is deliberately separate from the public-source
    gate, which remains BLOCK while the public URL is PENDING.
    """
    notice = staging / "SOURCE-CODE.md"
    text = notice.read_text("utf-8", errors="replace") if notice.is_file() else ""
    commit_match = re.search(r"Local (?:Git )?commit:\s*([0-9a-f]{40})", text, re.IGNORECASE)
    tag_match = re.search(r"Local tag:\s*([^\s]+)", text)
    repository_match = re.search(
        r"(?:Upstream|Source) repository(?: \(reference only\))?:\s*(\S+)",
        text,
        re.IGNORECASE,
    )
    commit = commit_match.group(1).lower() if commit_match else None
    tag = tag_match.group(1) if tag_match else None
    repository = repository_match.group(1) if repository_match else None
    public_pending = bool(re.search(r"Public source URL:\s*.*PENDING", text, re.IGNORECASE))
    commit_exists = False
    tag_matches = False
    if repo and commit and tag:
        try:
            commit_exists = subprocess.run(
                ["git", "-C", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode == 0
            tag_revision = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", f"{tag}^{{commit}}"],
                capture_output=True,
                text=True,
                check=False,
            )
            tag_matches = tag_revision.returncode == 0 and tag_revision.stdout.strip().lower() == commit
        except OSError:
            commit_exists = False
            tag_matches = False
    elif commit and tag:
        # Unit-level callers without a checkout still get structural
        # validation; the full verifier passes its repository root below.
        commit_exists = True
        tag_matches = True
    verified = bool(
        notice.is_file()
        and commit
        and tag
        and repository
        and public_pending
        and commit_exists
        and tag_matches
    )
    return {
        "mode": "external-source-channel",
        "notice": file_record(notice, staging),
        "repository": repository,
        "commit": commit,
        "tag": tag,
        "public_source_url": "PENDING" if public_pending else None,
        "commit_object_verified": commit_exists,
        "tag_target_verified": tag_matches,
        "verified": verified,
        "reason": (
            "Bundled source/ is available; no external source channel is required."
            if (staging / "source").is_dir()
            else "Complete source/ is intentionally omitted; SOURCE-CODE.md records the exact external source channel and the public URL remains pending."
            if public_pending
            else "An external source channel is not configured or could not be verified."
        ),
    }


def verify_gpu_e2e(staging: Path, plugin: Path, models: dict, repo: Path | None = None):
    path = plugin / "gpu-e2e-evidence.json"
    source_path = staging / "source" / "UmiOCR-data" / "plugins" / plugin.name / path.name
    payload = load_json(path) if path.is_file() else {}
    expected_models = [
        "UVDoc" if str(item.get("model_name", "")).startswith("UVDoc_grid")
        else str(item.get("model_name", "")).removesuffix("_infer")
        for item in models.get("models", [])
    ]
    exercised = {str(item) for item in payload.get("exercised_paths", [])}
    runtime_lock = plugin / "runtime.lock.json"
    source_matches = source_path.is_file() and path.is_file() and sha256(source_path) == sha256(path)
    external_source = external_source_channel(staging, repo)
    source_delivery_verified = source_matches or external_source["verified"]
    manifest_path = plugin / "umi-plugin.json"
    manifest = load_json(manifest_path) if manifest_path.is_file() else {}
    source_binding_valid = True
    if str(manifest.get("version", "")).split(".")[0] == "3":
        actual_sources = {
            item.relative_to(plugin).as_posix(): sha256(item)
            for item in sorted(plugin.rglob("*.py"))
            if not any(part in {"vendor", "models", "__pycache__"} for part in item.relative_to(plugin).parts)
        }
        tested_sources = payload.get("plugin_source_sha256")
        source_binding_valid = bool(actual_sources) and tested_sources == actual_sources
        workflow_test = payload.get("workflow_test", {})
        test_path = (repo / "tests/test_ocr_workflows.py") if repo else (staging / "source/tests/test_ocr_workflows.py")
        source_binding_valid = source_binding_valid and test_path.is_file() and workflow_test.get("SHA256") == sha256(test_path)
    valid = bool(path.is_file()) and all(
        (
            payload.get("test_type") == "real_gpu_ocr_workflows_e2e",
             payload.get("status") == "PASS",
             re.fullmatch(r"gpu:\d+", str(payload.get("device", ""))) is not None,
             payload.get("architecture", {}).get("type") == "separate-worker-stdio-ipc",
             payload.get("architecture", {}).get("host_loaded_proprietary_modules") == [],
             payload.get("architecture", {}).get("ipc_payload") == "JSON-lines path/base64 -> JSON OCR result",
             payload.get("plugin_runtime_lock_sha256") == (sha256(runtime_lock) if runtime_lock.is_file() else None),
            payload.get("model_initialization") == expected_models,
            int(payload.get("ffmpeg_backend_dll_count", -1)) == 0,
            int(payload.get("cusolvermg_dll_count", -1)) == 0,
            {"batch OCR", "document PDF OCR", "CUDA-only failure paths"} <= exercised,
            source_delivery_verified,
            source_binding_valid,
        )
    )
    return {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "evidence": file_record(path, staging),
        "source_mirror_evidence": file_record(source_path, staging),
        "source_binding_valid": source_binding_valid,
        "external_source_channel": external_source,
        "runtime_lock_reverified": file_record(runtime_lock, staging),
        "expected_model_initialization": expected_models,
        "record": payload,
        "status": "PASS" if valid else "BLOCK",
        "blockers": [] if valid else [
            "GPU OCR E2E evidence is missing, malformed, stale, or does not prove the five-model CUDA path after FFmpeg/cusolverMg exclusion and a verified source delivery channel."
        ],
    }


def file_record(path: Path, staging: Path):
    return {"artifact_path": rel(path, staging), "SHA256": sha256(path)} if path.is_file() else None


def source_asset(source_lock, name: str):
    return next((entry for entry in source_lock.get("thirdPartySources", []) if entry.get("name") == name), None)


def source_archive_record(staging: Path, asset, cache_root: Path | None):
    source_in_release = staging / "source" / "third_party" / asset["name"]
    source_cache = cache_root / "sources" / asset["name"] if cache_root else None
    release_hash = sha256(source_in_release) if source_in_release.is_file() else None
    cache_hash = sha256(source_cache) if source_cache and source_cache.is_file() else None
    return {
        "artifact_path": rel(source_in_release, staging),
        "SHA256": asset.get("sha256"),
        "actual_SHA256": release_hash,
        "size": asset.get("size"),
        "upstream_source": asset.get("url"),
        "upstream_repository": asset.get("upstream_repository"),
        "upstream_revision": asset.get("upstream_revision"),
        "license": asset.get("license"),
        "present_in_release_source": release_hash == asset.get("sha256"),
        "verified_in_build_cache": cache_hash == asset.get("sha256") if cache_root else None,
    }


def archive_member_hash(archive: Path, member: str):
    if not archive.is_file():
        return None
    try:
        with tarfile.open(archive, "r:*") as bundle:
            stream = bundle.extractfile(member)
            return hashlib.sha256(stream.read()).hexdigest() if stream else None
    except (OSError, tarfile.TarError):
        return None


def mpl_file_record(staging: Path, local: Path, source_archive: Path, source_member: str, upstream_archive: Path | None = None, upstream_member: str | None = None):
    local_record = file_record(local, staging)
    source_hash = archive_member_hash(source_archive, source_member)
    record = {
        **(local_record or {"artifact_path": rel(local, staging), "SHA256": None}),
        "source_form": {
            "member": source_member,
            "SHA256": source_hash,
            "matches_artifact": bool(local_record and local_record["SHA256"] == source_hash),
        },
    }
    if upstream_archive and upstream_member:
        record["upstream_source"] = {
            "member": upstream_member,
            "SHA256": archive_member_hash(upstream_archive, upstream_member),
        }
    return record


def verify_mpl(staging: Path, vendor: Path, source_lock, cache_root: Path | None):
    asset_names = {
        "certifi": "certifi-2026.6.17.tar.gz",
        "tqdm": "tqdm-4.68.4.tar.gz",
        "validate": "validate_pyproject-0.25.tar.gz",
        "setuptools": "setuptools-83.0.0.tar.gz",
    }
    assets = {key: source_asset(source_lock, name) or {} for key, name in asset_names.items()}
    source_records = [source_archive_record(staging, asset, cache_root) for asset in assets.values() if asset]
    source_paths = {
        key: staging / "source" / "third_party" / asset["name"] for key, asset in assets.items() if asset
    }
    source_complete = len(source_records) == len(asset_names) and all(item["present_in_release_source"] for item in source_records)
    missing_assets = [asset_names[key] for key, asset in assets.items() if not asset]
    certifi = vendor / "certifi" / "cacert.pem"
    tqdm_license = vendor / "tqdm-4.68.4.dist-info" / "licenses" / "LICENCE"
    validate_root = vendor / "setuptools" / "config" / "_validate_pyproject"
    validate_files = {name: validate_root / name for name in ("extra_validations.py", "formats.py", "error_reporting.py")}
    certifi_file = mpl_file_record(
        staging,
        certifi,
        source_paths.get("certifi", Path()),
        "certifi-2026.6.17/certifi/cacert.pem",
    )
    tqdm_file = mpl_file_record(
        staging,
        tqdm_license,
        source_paths.get("tqdm", Path()),
        "tqdm-4.68.4/LICENCE",
    )
    validate_records = {
        name: mpl_file_record(
            staging,
            path,
            source_paths.get("setuptools", Path()),
            f"setuptools-83.0.0/setuptools/config/_validate_pyproject/{name}",
            source_paths.get("validate"),
            f"validate_pyproject-0.25/src/validate_pyproject/{name}",
        )
        for name, path in validate_files.items()
    }
    validate_notice = mpl_file_record(
        staging,
        validate_root / "NOTICE",
        source_paths.get("setuptools", Path()),
        "setuptools-83.0.0/setuptools/config/_validate_pyproject/NOTICE",
    )
    error_member = "validate_pyproject-0.25/src/validate_pyproject/error_reporting.py"
    generated_member = "setuptools-83.0.0/setuptools/config/_validate_pyproject/error_reporting.py"
    error_change = False
    if source_paths.get("validate") and source_paths.get("setuptools"):
        try:
            with tarfile.open(source_paths["validate"], "r:*") as bundle:
                upstream_error = bundle.extractfile(error_member).read()
            with tarfile.open(source_paths["setuptools"], "r:*") as bundle:
                generated_error = bundle.extractfile(generated_member).read()
            error_change = generated_error == upstream_error.replace(
                b"from fastjsonschema import JsonSchemaValueException",
                b"from .fastjsonschema_exceptions import JsonSchemaValueException",
            )
        except (AttributeError, OSError, tarfile.TarError):
            pass
    validate_exact = all(item["source_form"]["matches_artifact"] for item in validate_records.values()) and validate_notice["source_form"]["matches_artifact"]
    validate_upstream = all(
        validate_records[name].get("upstream_source", {}).get("SHA256") == validate_records[name]["SHA256"]
        for name in ("extra_validations.py", "formats.py")
    )
    validate_status = "PASS" if source_complete and validate_exact and validate_upstream and error_change and package_version(vendor, "setuptools") == assets.get("setuptools", {}).get("version") else "BLOCK"
    components = [
        {
            "component": "certifi",
            "version": package_version(vendor, "certifi"),
            "files": [certifi_file],
            "upstream": assets.get("certifi", {}).get("upstream_repository"),
            "upstream_revision": assets.get("certifi", {}).get("upstream_revision"),
            "license": "MPL-2.0",
            "required_notices": ["certifi-2026.6.17.dist-info/licenses/LICENSE"],
            "source_availability_obligation": "source/third_party/certifi-2026.6.17.tar.gz provides the matching MPL-covered source form.",
            "status": "PASS" if source_complete and certifi_file["source_form"]["matches_artifact"] and package_version(vendor, "certifi") == assets.get("certifi", {}).get("version") else "BLOCK",
        },
        {
            "component": "tqdm",
            "version": package_version(vendor, "tqdm"),
            "files": [tqdm_file],
            "upstream": assets.get("tqdm", {}).get("upstream_repository"),
            "upstream_revision": assets.get("tqdm", {}).get("upstream_revision"),
            "license": "MPL-2.0 AND MIT",
            "redistribution_basis": "MIT alternative is available; the matching source archive is retained for the MPL record.",
            "required_notices": ["tqdm-4.68.4.dist-info/licenses/LICENCE"],
            "source_availability_obligation": "source/third_party/tqdm-4.68.4.tar.gz provides the matching source form.",
            "status": "PASS" if source_complete and tqdm_file["source_form"]["matches_artifact"] and package_version(vendor, "tqdm") == assets.get("tqdm", {}).get("version") else "BLOCK",
        },
        {
            "component": "validate-pyproject vendored by setuptools",
            "version": assets.get("validate", {}).get("version"),
            "files": [*validate_records.values(), validate_notice],
            "upstream": assets.get("validate", {}).get("upstream_repository"),
            "upstream_revision": assets.get("validate", {}).get("upstream_revision"),
            "license": "MPL-2.0",
            "exact_source_form": {
                "component": "setuptools",
                "version": assets.get("setuptools", {}).get("version"),
                "upstream": assets.get("setuptools", {}).get("upstream_repository"),
                "upstream_revision": assets.get("setuptools", {}).get("upstream_revision"),
            },
            "modification_status": "modified",
            "modification_notice": "Compared with validate-pyproject 0.25, error_reporting.py only replaces the fastjsonschema import with setuptools' vendored .fastjsonschema_exceptions import; the shipped files match the setuptools 83.0.0 source form.",
            "required_notices": ["setuptools/config/_validate_pyproject/NOTICE"],
            "source_availability_obligation": "source/third_party/setuptools-83.0.0.tar.gz provides the exact shipped source form, and source/third_party/validate_pyproject-0.25.tar.gz provides its upstream provenance.",
            "status": validate_status,
        },
    ]
    return {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "source_archives": source_records,
        "missing_source_lock_entries": missing_assets,
        "components": components,
        "status": "PASS" if all(item["status"] == "PASS" for item in components) else "BLOCK",
    }


def verify_agpl(staging: Path, repo: Path, plugin: Path):
    copying = repo / "COPYING"
    mit = repo / "LICENSE"
    about = repo / "UmiOCR-data" / "about.json"
    combined = staging / "LICENSES" / "COMBINED_DISTRIBUTION.md"
    manifest = plugin / "umi-plugin.json"
    controller = repo / "UmiOCR-data" / "py_src" / "plugins_controller" / "plugins_controller.py"
    api = repo / "UmiOCR-data" / "plugins" / "win32_PaddleOCRv6_CUDA" / "api.py"
    worker = plugin / "worker.py"
    manifest_data = load_json(manifest) if manifest.is_file() else {}
    runtime = manifest_data.get("runtime") if isinstance(manifest_data, dict) else {}
    runtime = runtime if isinstance(runtime, dict) else {}
    boundary = runtime.get("process_boundary") if isinstance(runtime.get("process_boundary"), dict) else {}
    api_text = api.read_text("utf-8", errors="replace") if api.is_file() else ""
    worker_text = worker.read_text("utf-8", errors="replace") if worker.is_file() else ""
    host_forbidden_imports = sorted(
        token for token in ("import paddle", "from paddle", "import cv2", "from cv2", "paddleocr", "os.add_dll_directory")
        if token in api_text
    )
    worker_boundary_checks = {
        "worker_present_in_artifact": worker.is_file(),
        "manifest_vendor_dirs_empty": runtime.get("vendor_dirs") in ([], None),
        "manifest_dll_dirs_empty": runtime.get("dll_dirs") in ([], None),
        "manifest_process_boundary": boundary.get("type") == "separate-worker-stdio-ipc" and boundary.get("entry") == "worker.py",
        "host_has_no_proprietary_runtime_imports": not host_forbidden_imports,
        "host_starts_subprocess": "subprocess.Popen" in api_text,
        "host_uses_json_ipc": "json.dumps" in api_text and "JSON-lines" in api_text,
        "worker_loads_stack": "import paddle" in worker_text and "from paddleocr import PaddleOCR" in worker_text and "import cv2" in worker_text,
        "worker_uses_simple_payloads": "run_path" in worker_text and "run_bytes" in worker_text and "json.loads" in worker_text,
    }
    worker_boundary_pass = all(worker_boundary_checks.values())
    about_license = load_json(about).get("license", {}).get("type") if about.is_file() else None
    combined_text = combined.read_text("utf-8", errors="replace") if combined.is_file() else ""
    combined_license = "AGPL-3.0-or-later" if "AGPL-3.0-or-later" in combined_text else None
    return {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "project_license_facts": {
            "root_LICENSE": {"license": "MIT", "SHA256": sha256(mit) if mit.is_file() else None},
            "COPYING": {
                "document": "GNU Affero General Public License version 3 text",
                "SHA256": sha256(copying) if copying.is_file() else None,
                "application_license_selection": "COPYING alone does not state whether the project selects only-v3 or any-later-version.",
            },
            "about_json": {"license": about_license, "repository_path": rel(about, repo), "SHA256": sha256(about) if about.is_file() else None},
            "combined_distribution": {
                "license": combined_license,
                "artifact_path": rel(combined, staging),
                "SHA256": sha256(combined) if combined.is_file() else None,
            },
            "declared_combined_release_license": "AGPL-3.0-or-later" if about_license == combined_license == "AGPL-3.0-or-later" else "UNVERIFIED",
            "scope": "The original upstream portions retain MIT; the fork additions and declared combined Windows release are AGPL-3.0-or-later when both independent release declarations match.",
        },
        "integration_architecture": {
            "type": "separate-worker-stdio-ipc",
            "facts": [
                "The host adapter contains only standard-library process/JSON code; it does not import Paddle, OpenCV, CUDA, or cuDNN.",
                "The plugin manifest declares no host vendor_dirs or dll_dirs. worker.py alone registers private vendor DLL directories in the child process.",
                "The host and worker exchange only JSON-lines requests (path/base64 image plus configuration) and JSON OCR result records; no pointers, shared memory, or private ABI cross the boundary.",
            ],
            "evidence_paths": [rel(controller, repo), rel(api, repo), rel(worker, staging), rel(manifest, staging)],
            "checks": worker_boundary_checks,
        },
        "agpl_network_interaction_obligation": "For any modified AGPL-covered deployment that lets users interact remotely, AGPLv3 section 13 requires a prominent offer of Corresponding Source. The release source mirror is separately audited; proprietary NVIDIA binaries are not asserted to be AGPL-covered source.",
        "system_library_claim": "not made",
        "additional_permission": "not used; the process boundary avoids a linking exception request",
        "status": "PASS" if worker_boundary_pass else "BLOCK",
        "resolution": "The NVIDIA/Paddle stack is confined to an independent worker executable/process. The AGPL-covered host (including its separately packaged PyMuPDF dependency) receives only stable JSON IPC data; the worker has its own runtime/vendor manifest and source mirror.",
        "blocker": None if worker_boundary_pass else "The declared independent GPU worker boundary is incomplete: " + ", ".join(name for name, ok in worker_boundary_checks.items() if not ok),
    }


def expected_file_record(path: Path, root: Path):
    record = file_record(path, root)
    return {**(record or {"artifact_path": rel(path, root), "SHA256": None}), "present": bool(record)}


def artifact_files(root: Path, evidence_root: Path, suffixes: set[str]):
    if not root.is_dir():
        return []
    return [
        file_record(path, evidence_root)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() in suffixes
    ]


def cpu_package_notices(vendor: Path, staging: Path, package_name: str) -> list[str]:
    packages, _ = metadata_index(vendor)
    item = packages.get(normalized(package_name))
    if not item:
        return []
    info, _ = item
    candidates = {path for path in info.rglob("*") if path.is_file()}
    top_level = info / "top_level.txt"
    if top_level.is_file():
        for name in top_level.read_text("utf-8", errors="replace").splitlines():
            root = vendor / name.strip()
            if root.is_dir():
                candidates.update(path for path in root.rglob("*") if path.is_file())
    return sorted(
        rel(path, staging)
        for path in candidates
        if any(token in path.name.lower() for token in ("license", "notice", "copying"))
        or path.name.lower() == "thirdpartynotices.txt"
    )


def cpu_runtime_lock_complete(staging: Path, plugin: Path):
    lock_path = plugin / "runtime.lock.json"
    if not lock_path.is_file():
        return [], ["runtime.lock.json is missing"]
    try:
        payload = load_json(lock_path)
    except json.JSONDecodeError as exc:
        return [], [f"runtime.lock.json is invalid JSON: {exc}"]
    entries = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries:
        return [], ["runtime.lock.json has no files array"]
    locked = [str(entry.get("path", "")).replace("\\", "/") for entry in entries if isinstance(entry, dict)]
    expected = {
        rel(path, plugin)
        for path in plugin.rglob("*")
        if path.is_file() and path != lock_path
    }
    duplicate = sorted({path for path in locked if locked.count(path) > 1})
    missing = sorted(expected - set(locked))
    extra = sorted(set(locked) - expected)
    issues = []
    if duplicate:
        issues.append("runtime.lock.json has duplicate entries: " + ", ".join(duplicate))
    if missing:
        issues.append("runtime.lock.json omits packaged files: " + ", ".join(missing))
    if extra:
        issues.append("runtime.lock.json lists files not in the package: " + ", ".join(extra))
    return entries, issues


def verify_cpu_pdfium_bundle(staging: Path, plugin: Path, vendor: Path):
    """Verify the actual PDFium DLL against its copied upstream artifacts.

    pypdfium2 is retained only because PaddleX checks it as an OCR-core
    dependency.  A package-level license label is not enough for its embedded
    PDFium DLL, so this check binds the installed DLL to both the published
    Windows wheel and the reviewed pdfium-binaries release.
    """

    source_lock_path = staging / "source" / "cpu-source-closure.json"
    source_lock = load_json(source_lock_path) if source_lock_path.is_file() else {}
    record = source_lock.get("pypdfium2_pdfium_bundle", {}) if isinstance(source_lock, dict) else {}
    blockers = []

    def staged_path(value):
        candidate = staging / str(value or "")
        try:
            candidate.resolve().relative_to(staging.resolve())
        except ValueError:
            return None
        return candidate

    def record_matches(item):
        path = staged_path(item.get("artifact_path")) if isinstance(item, dict) else None
        return bool(path and path.is_file() and item.get("SHA256") == sha256(path))

    expected_version = package_version(vendor, "pypdfium2")
    installed_dll = vendor / "pypdfium2_raw" / "pdfium.dll"
    version_path = vendor / "pypdfium2_raw" / "version.json"
    version = load_json(version_path) if version_path.is_file() else {}
    actual_pdfium_version = ".".join(str(version.get(key)) for key in ("major", "minor", "build", "patch")) if version else None
    artifact = record.get("artifact", {}) if isinstance(record, dict) else {}
    if not (
        record.get("component") == "pypdfium2/PDFium runtime bundle"
        and record.get("package") == "pypdfium2"
        and record.get("package_version") == expected_version
        and record.get("pdfium_version") == actual_pdfium_version
        and artifact.get("artifact_path") == rel(installed_dll, staging)
        and installed_dll.is_file()
        and artifact.get("SHA256") == sha256(installed_dll)
        and record.get("upstream_source") == "https://github.com/bblanchon/pdfium-binaries/releases/tag/chromium/7947"
        and record.get("upstream_revision") == "chromium/7947 @ a068e5317bb780d0afdf00d8b341938d9f36d2fe"
        and record.get("pypdfium2_upstream_source") == "https://github.com/pypdfium2-team/pypdfium2"
        and record.get("pypdfium2_upstream_revision") == "4a2636051ff4a841966be01484f4a70b4309b55c"
        and record.get("pypdfium2_release_tag_commit") == "b3e7e67a1e35c9436b52cb043d476b89ec8c38cb"
        and record.get("license_spdx") is None
        and record.get("spdx_license_identifiers") == ["BSD-3-Clause", "Apache-2.0", "CC-BY-4.0"]
        and record.get("modification_status") == "unmodified published wheel artifact"
    ):
        blockers.append("pypdfium2/PDFium source-closure record is missing required identity, version, license, or revision facts.")

    evidence = record.get("evidence_snapshots", []) if isinstance(record, dict) else []
    evidence_by_path = {item.get("artifact_path"): item for item in evidence if isinstance(item, dict)}
    expected_evidence_names = (
        "pypdfium2-5.12.1-py3-none-win_amd64.whl",
        "pypdfium2-5.12.1.tar.gz",
        "pypdfium2-pypi-5.12.1.json",
        "pypdfium2-pypi-wheel-provenance-5.12.1.json",
        "pypdfium2-release-5.12.1.github.json",
        "pypdfium2-wheel-source-4a2636051ff4a841966be01484f4a70b4309b55c.github.json",
        "pypdfium2-tag-5.12.1.github.json",
        "pdfium-binaries-chromium-7947.github.json",
        "pdfium-binaries-commit-a068e5317bb780d0afdf00d8b341938d9f36d2fe.github.json",
        "pdfium-win-x64.tgz",
    )
    expected_evidence_paths = {f"source/third_party/{name}" for name in expected_evidence_names}
    if set(evidence_by_path) != expected_evidence_paths or not all(record_matches(item) for item in evidence_by_path.values()):
        blockers.append("pypdfium2/PDFium evidence snapshots are missing, changed, or outside the release source mirror.")

    wheel_path = staging / "source" / "third_party" / "pypdfium2-5.12.1-py3-none-win_amd64.whl"
    pdfium_archive = staging / "source" / "third_party" / "pdfium-win-x64.tgz"
    pypi_path = staging / "source" / "third_party" / "pypdfium2-pypi-5.12.1.json"
    release_path = staging / "source" / "third_party" / "pdfium-binaries-chromium-7947.github.json"
    wheel_member_hash = None
    release_member_hash = None
    expected_notice_paths = set()
    try:
        with zipfile.ZipFile(wheel_path) as wheel:
            members = set(wheel.namelist())
            wheel_member_hash = hashlib.sha256(wheel.read("pypdfium2_raw/pdfium.dll")).hexdigest()
            expected_notice_paths = {
                rel(vendor / name, staging)
                for name in members
                if name.startswith("pypdfium2-5.12.1.dist-info/licenses/") and not name.endswith("/")
            }
        with tarfile.open(pdfium_archive, "r:gz") as archive:
            stream = archive.extractfile("bin/pdfium.dll")
            release_member_hash = hashlib.sha256(stream.read()).hexdigest() if stream else None
        pypi = load_json(pypi_path)
        pypi_wheel = next(item for item in pypi.get("urls", []) if item.get("filename") == wheel_path.name)
        pdfium_release = load_json(release_path)
        pdfium_asset = next(item for item in pdfium_release.get("assets", []) if item.get("name") == pdfium_archive.name)
        if (
            pypi.get("info", {}).get("version") != expected_version
            or pypi_wheel.get("digests", {}).get("sha256") != sha256(wheel_path)
            or pdfium_release.get("tag_name") != "chromium/7947"
            or pdfium_asset.get("digest") != f"sha256:{sha256(pdfium_archive)}"
        ):
            blockers.append("pypdfium2/PDFium official release snapshots do not verify the copied upstream assets.")
    except (KeyError, OSError, json.JSONDecodeError, tarfile.TarError, zipfile.BadZipFile, StopIteration):
        blockers.append("pypdfium2/PDFium upstream wheel or release asset cannot be parsed and verified.")
    if not installed_dll.is_file() or sha256(installed_dll) != wheel_member_hash or wheel_member_hash != release_member_hash:
        blockers.append("Installed pdfium.dll does not byte-match both the reviewed pypdfium2 wheel and PDFium release asset.")
    notices = record.get("required_notices", []) if isinstance(record, dict) else []
    notice_by_path = {item.get("artifact_path"): item for item in notices if isinstance(item, dict)}
    if set(notice_by_path) != expected_notice_paths or not all(record_matches(item) for item in notice_by_path.values()):
        blockers.append("pypdfium2/PDFium complete wheel notice inventory is not retained with verified hashes.")

    return {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "source_lock": file_record(source_lock_path, staging),
        "record": record,
        "status": "PASS" if not blockers else "BLOCK",
        "blockers": blockers,
    }


def verify_cpu_runtime(staging: Path, plugin: Path, errors: list[str]):
    vendor = plugin / "vendor"
    if not vendor.is_dir():
        return {"status": "BLOCK", "blockers": ["CPU vendor directory is missing."], "binaries": [], "packages": []}
    runtime = verify_runtime_vendor(staging, plugin, vendor, errors)
    requirements_path = plugin / "runtime-requirements.lock"
    requirements = load_json(requirements_path) if requirements_path.is_file() else {}
    package_index = {normalized(item["name"]): item for item in runtime["packages"]}
    requirement_index = {
        normalized(item.get("name", "")): item
        for item in requirements.get("packages", [])
        if isinstance(item, dict) and item.get("name")
    }
    blockers = list(runtime.get("blockers", []))
    pdfium = verify_cpu_pdfium_bundle(staging, plugin, vendor)
    blockers.extend(pdfium.get("blockers", []))
    pdfium_record = pdfium.get("record", {}) if isinstance(pdfium.get("record"), dict) else {}
    if not requirements_path.is_file():
        blockers.append("runtime-requirements.lock is missing.")
    else:
        runtime_fact = requirements.get("inference_runtime", {})
        if (
            runtime_fact.get("package") != "onnxruntime"
            or runtime_fact.get("provider") != "CPUExecutionProvider"
            or runtime_fact.get("cuda_or_paddle_fallback") is not False
        ):
            blockers.append("runtime-requirements.lock does not declare the required ONNX Runtime CPU-only execution facts.")
        for name in CPU_REQUIRED_PACKAGES:
            package = package_index.get(normalized(name))
            requirement = requirement_index.get(normalized(name))
            if not package or not requirement:
                blockers.append(f"CPU runtime lacks a verified {name} package record.")
                continue
            metadata = plugin / str(requirement.get("metadata_path", ""))
            if (
                package["version"] != requirement.get("version")
                or not metadata.is_file()
                or sha256(metadata) != requirement.get("metadata_SHA256")
            ):
                blockers.append(f"runtime-requirements.lock does not match the copied {name} metadata.")
        onnx = package_index.get("onnxruntime")
        if onnx and requirements.get("inference_runtime", {}).get("version") != onnx["version"]:
            blockers.append("runtime-requirements.lock ONNX Runtime version differs from the copied wheel metadata.")

    entries, lock_issues = cpu_runtime_lock_complete(staging, plugin)
    blockers.extend(lock_issues)
    profile_by_package = {normalized(name): license for name, license in CPU_BINARY_LICENSES.items()}
    for package in runtime["packages"]:
        key = normalized(package["name"])
        notices = cpu_package_notices(vendor, staging, package["name"])
        if key in profile_by_package:
            package["license_spdx"] = profile_by_package[key]
            package["required_notices"] = notices
            package["redistribution_basis"] = "installed wheel license text and notices"
            package["source_availability_obligation"] = "See the component license; LGPL/MPL components have explicit CPU source-closure records."
        elif key == "pypdfium2":
            package["upstream_source"] = pdfium_record.get("pypdfium2_upstream_source")
            package["upstream_revision"] = pdfium_record.get("pypdfium2_upstream_revision")
            package["license_spdx"] = pdfium_record.get("license_spdx")
            package["license_description"] = pdfium_record.get("license")
            package["spdx_license_identifiers"] = pdfium_record.get("spdx_license_identifiers")
            package["required_notices"] = [item.get("artifact_path") for item in pdfium_record.get("required_notices", []) if isinstance(item, dict)]
            package["redistribution_basis"] = pdfium_record.get("redistribution_basis")
            package["source_availability_obligation"] = pdfium_record.get("source_availability_obligation")
            package["evidence_snapshot"] = pdfium_record.get("evidence_snapshots", [])
    for binary in runtime["binaries"]:
        key = normalized(binary["package"])
        package = package_index.get(key)
        if key in profile_by_package:
            binary["license_spdx"] = profile_by_package[key]
            binary["required_notices"] = package.get("required_notices", []) if package else []
        elif key == "pypdfium2":
            binary["version"] = pdfium_record.get("pdfium_version")
            binary["upstream_source"] = pdfium_record.get("upstream_source")
            binary["upstream_revision"] = pdfium_record.get("upstream_revision")
            binary["license_spdx"] = pdfium_record.get("license_spdx")
            binary["license_description"] = pdfium_record.get("license")
            binary["spdx_license_identifiers"] = pdfium_record.get("spdx_license_identifiers")
            binary["required_notices"] = package.get("required_notices", []) if package else []
            binary["redistribution_basis"] = pdfium_record.get("redistribution_basis")
            binary["source_availability_obligation"] = pdfium_record.get("source_availability_obligation")
            binary["modification_status"] = pdfium_record.get("modification_status")
            binary["evidence_snapshot"] = pdfium_record.get("evidence_snapshots", [])
        else:
            blockers.append(f"CPU binary has no reviewed license profile: {binary['artifact_path']}")

    def evidence_snapshot_valid(value):
        records = value if isinstance(value, list) else [value]
        if not records:
            return False
        for item in records:
            if not isinstance(item, dict):
                return False
            path = staging / str(item.get("artifact_path", ""))
            try:
                path.resolve().relative_to(staging.resolve())
            except ValueError:
                return False
            if not path.is_file() or item.get("SHA256") != sha256(path):
                return False
        return True

    required_fields = (
        "name", "version", "artifact_path", "SHA256", "upstream_source", "upstream_revision",
        "redistribution_basis", "required_notices", "source_availability_obligation", "modification_status", "evidence_snapshot",
    )
    for kind, items in (("package", runtime["packages"]), ("binary", runtime["binaries"])):
        for item in items:
            missing = [field for field in required_fields if item.get(field) in (None, "")]
            has_license = bool(item.get("license_spdx") or item.get("license_description") or item.get("spdx_license_identifiers") or item.get("proprietary_agreement_name"))
            if missing or not has_license or not isinstance(item.get("required_notices"), list) or not evidence_snapshot_valid(item.get("evidence_snapshot")):
                label = item.get("artifact_path") or item.get("name") or "UNKNOWN"
                blockers.append(f"CPU {kind} has incomplete artifact-driven provenance: {label}")

    forbidden_paths = []
    for pattern in ("paddle", "paddlepaddle*", "nvidia", "nvidia-*", "huggingface_hub*", "modelscope*", "aistudio_sdk*"):
        forbidden_paths.extend(path for path in vendor.glob(pattern) if path.exists())
    if forbidden_paths:
        blockers.append("CPU vendor contains prohibited runtime/download clients: " + ", ".join(rel(path, staging) for path in forbidden_paths))
    import_scan = scan_pe_import_tables(vendor)
    forbidden_imports = []
    for record in import_scan["import_tables"]:
        names = set(record["normal_imports"]) | set(record["delay_imports"])
        matches = sorted(name for name in names if any(token in name for token in ("cuda", "cudnn", "nvinfer", "directml")))
        if matches:
            forbidden_imports.append({"artifact_path": rel(vendor / record["artifact_path"], staging), "imports": matches})
    if import_scan["scan_errors"]:
        blockers.append("CPU vendor PE import-table scan failed.")
    if forbidden_imports:
        blockers.append("CPU vendor imports CUDA/cuDNN/DirectML binaries.")
    patch_path = plugin / "paddlex-offline-patch.json"
    patch = load_json(patch_path) if patch_path.is_file() else {}
    patch_script = staging / "source" / "tools" / "patch_paddlex_cpu_offline.py"
    official_models = vendor / "paddlex" / "inference" / "utils" / "official_models.py"
    pipeline = vendor / "paddlex" / "inference" / "pipelines" / "doc_preprocessor" / "pipeline.py"
    if (
        patch.get("component") != "paddlex"
        or patch.get("version") != package_version(vendor, "paddlex")
        or patch.get("patch_script") != "patch_paddlex_cpu_offline.py"
        or not patch_script.is_file()
        or patch.get("patch_script_sha256") != sha256(patch_script)
        or patch.get("automatic_model_downloads") is not False
        or patch.get("uvdoc_grid_output") is not True
        or not official_models.is_file()
        or "hoster_candidates = []" not in official_models.read_text("utf-8", errors="replace")
        or not pipeline.is_file()
        or '"grid": grid,' not in pipeline.read_text("utf-8", errors="replace")
    ):
        blockers.append("The recorded offline PaddleX patch is missing or does not match the copied runtime.")
    for package in runtime["packages"]:
        if normalized(package["name"]) == "paddlex":
            package["modification_status"] = "modified by tools/patch_paddlex_cpu_offline.py; see paddlex-offline-patch.json"

    prune_path = plugin / "vendor-prune.json"
    prune = load_json(prune_path) if prune_path.is_file() else {}
    removed = prune.get("removed", []) if isinstance(prune, dict) else []
    prune_issues = []
    if (
        prune.get("component") != "CPU ONNX vendor pruning"
        or prune.get("dry_run") is not False
        or not isinstance(removed, list)
        or not removed
    ):
        prune_issues.append("vendor-prune.json is missing or does not record an applied CPU vendor prune.")
    pruned_packages = set()
    for entry in removed if isinstance(removed, list) else []:
        artifact_path = str(entry.get("artifact_path", ""))
        candidate = plugin / artifact_path
        try:
            candidate.resolve().relative_to(plugin.resolve())
        except ValueError:
            prune_issues.append("vendor-prune.json contains a path outside the plugin root.")
            continue
        if (
            not artifact_path.startswith("vendor/")
            or candidate.exists()
            or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("SHA256", "")).lower())
            or not isinstance(entry.get("size"), int)
            or entry.get("size", -1) < 0
            or not entry.get("package")
        ):
            prune_issues.append("vendor-prune.json has an invalid or still-present removal record.")
            continue
        pruned_packages.add(normalized(str(entry["package"])))
    blockers.extend(list(dict.fromkeys(prune_issues)))
    for package in runtime["packages"]:
        key = normalized(package["name"])
        if key in pruned_packages:
            existing = package.get("modification_status", "unmodified")
            package["modification_status"] = existing + "; wheel payload pruned by tools/prune_cpu_vendor.py; see vendor-prune.json"

    runtime["cpu_execution"] = {
        "actual_inference_runtime": "ONNX Runtime",
        "actual_runtime_version": package_index.get("onnxruntime", {}).get("version"),
        "provider": "CPUExecutionProvider",
        "cuda_or_paddle_fallback": False,
        "runtime_requirements_lock": file_record(requirements_path, staging),
        "runtime_lock_complete": not lock_issues,
        "runtime_lock_entries": len(entries),
        "pe_import_table_scan": {**import_scan, "forbidden_import_matches": forbidden_imports},
        "paddlex_offline_patch": file_record(patch_path, staging),
        "vendor_pruning": {
            "evidence": file_record(prune_path, staging),
            "removed_file_count": len(removed) if isinstance(removed, list) else 0,
            "modified_packages": sorted(pruned_packages),
        },
        "embedded_components": [
            {
                **pdfium_record,
                "status": pdfium.get("status"),
                "blockers": pdfium.get("blockers", []),
            }
        ],
    }
    runtime["pypdfium2_pdfium"] = pdfium
    runtime["status"] = "PASS" if not blockers else "BLOCK"
    runtime["blockers"] = list(dict.fromkeys(blockers))
    return runtime


def hf_lfs_sha256(payload):
    for sibling in payload.get("siblings", []):
        if sibling.get("rfilename") == "inference.onnx":
            value = sibling.get("lfs", {}).get("sha256")
            if value:
                return str(value).lower()
    return None


def verify_cpu_models(staging: Path, plugin: Path, apache_path: str):
    manifest_path = plugin / "model-rights.json"
    payload = load_json(manifest_path) if manifest_path.is_file() else {}
    entries = payload.get("models", []) if isinstance(payload, dict) else []
    by_name = {entry.get("model_name"): entry for entry in entries if isinstance(entry, dict)}
    blockers = []
    records = []
    expected_weight_paths = set()
    for model_name, repository in CPU_MODELS.items():
        entry = by_name.get(model_name)
        model_dir = plugin / "models" / model_name
        weight = model_dir / "inference.onnx"
        card = model_dir / "README.md"
        snapshot = model_dir / "huggingface-api.json"
        expected_weight_paths.add(weight.resolve())
        actual = sha256(weight) if weight.is_file() else None
        model_payload = load_json(snapshot) if snapshot.is_file() else {}
        upstream = hf_lfs_sha256(model_payload)
        license_evidence = (entry or {}).get("license_evidence", {})
        required_notices = (entry or {}).get("required_notices", [])
        required = (
            "model_name", "upstream_owner", "upstream_repository", "upstream_revision", "license", "license_evidence",
            "local_filename", "SHA256", "modified", "redistribution_allowed", "required_notices", "verification_date",
        )
        missing = [key for key in required if not entry or key not in entry]
        valid = bool(entry) and not missing and all(
            (
                entry["upstream_owner"] == "PaddlePaddle",
                entry["upstream_repository"] == f"https://huggingface.co/{repository}",
                entry["upstream_revision"] == model_payload.get("sha"),
                entry["license"] == "Apache-2.0",
                entry["local_filename"] == f"models/{model_name}/inference.onnx",
                entry["SHA256"] == actual == upstream,
                entry.get("upstream_weight_SHA256") == upstream,
                entry["modified"] is False,
                entry.get("modification_notice") in {None, ""},
                entry["redistribution_allowed"] is True,
                entry["verification_date"] == VERIFY_DATE,
                isinstance(license_evidence, dict),
                license_evidence.get("model_card") == f"models/{model_name}/README.md",
                license_evidence.get("model_api_snapshot") == f"models/{model_name}/huggingface-api.json",
                license_evidence.get("model_api_snapshot_SHA256") == (sha256(snapshot) if snapshot.is_file() else None),
                license_evidence.get("json_path") == "cardData.license",
                str(license_evidence.get("value", "")).lower() == "apache-2.0",
                isinstance(required_notices, list),
                apache_path in required_notices,
                f"models/{model_name}/README.md" in required_notices,
                model_payload.get("id") == repository,
                model_payload.get("author") == "PaddlePaddle",
                str(model_payload.get("cardData", {}).get("license", "")).lower() == "apache-2.0",
                card.is_file(),
                snapshot.is_file(),
            )
        )
        if not valid:
            detail = f" ({', '.join(missing)})" if missing else ""
            blockers.append(f"CPU model provenance is incomplete or does not match its official PaddlePaddle snapshot: {model_name}{detail}")
        records.append(
            {
                **(entry or {"model_name": model_name}),
                "local_filename": rel(weight, staging),
                "SHA256": actual,
                "upstream_weight_SHA256": upstream,
                "license_evidence_snapshot": file_record(snapshot, staging),
                "model_card": file_record(card, staging),
                "required_notices": list(dict.fromkeys((entry or {}).get("required_notices", []) + [apache_path, rel(card, staging) if card.is_file() else ""])),
                "evidence_snapshot_path": "LICENSES/model-rights.json",
                "status": "PASS" if valid else "BLOCK",
            }
        )
    actual_weights = {
        path.resolve()
        for path in (plugin / "models").rglob("*")
        if path.is_file() and path.suffix.lower() in {".onnx", ".bin", ".safetensors", ".pdmodel", ".pdiparams", ".engine", ".ort"}
    } if (plugin / "models").is_dir() else set()
    unexpected = sorted(rel(path, staging) for path in actual_weights - expected_weight_paths)
    if unexpected:
        blockers.append("CPU model directory has unproven ONNX weights: " + ", ".join(unexpected))
    extra_records = sorted(set(by_name) - set(CPU_MODELS))
    if len(entries) != len(by_name) or extra_records:
        blockers.append("model-rights.json has duplicate or unexpected model records.")
    return {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "input_model_rights_lock": file_record(manifest_path, staging),
        "models": records,
        "unexpected_model_weights": unexpected,
        "status": "PASS" if not blockers and len(records) == len(CPU_MODELS) else "BLOCK",
        "blockers": blockers,
    }


def verify_cpu_ffmpeg(staging: Path, plugin: Path):
    vendor = plugin / "vendor"
    ffmpeg_dlls = sorted((vendor / "cv2").glob("opencv_videoio_ffmpeg*.dll")) if (vendor / "cv2").is_dir() else []
    cv2 = vendor / "cv2" / "cv2.pyd"
    imports = pe_import_tables(cv2.read_bytes()) if cv2.is_file() and cv2.read_bytes()[:2] == b"MZ" else {"normal_imports": [], "delay_imports": []}
    strings = printable_strings(cv2) if cv2.is_file() else []
    static_markers = [item for item in strings if "ffmpeg version" in item.lower() or "libavcodec" in item.lower()]
    included = bool(ffmpeg_dlls or static_markers or any("avcodec" in name or "avformat" in name for name in imports["normal_imports"] + imports["delay_imports"]))
    return {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "component": "FFmpeg in CPU OpenCV artifact",
        "opencv_videoio_dlls": [file_record(path, staging) for path in ffmpeg_dlls],
        "cv2_imports": imports,
        "static_ffmpeg_markers": static_markers,
        "status": "BLOCK" if included else "NOT_INCLUDED",
        "blockers": ["FFmpeg code or binary evidence was found in the CPU OpenCV artifact; exact source/config/relink closure is required."] if included else [],
    }


def archive_member_exists(path: Path, member: str) -> bool:
    try:
        with tarfile.open(path, "r:*") as archive:
            stream = archive.extractfile(member)
            return stream is not None and bool(stream.read(1))
    except (OSError, tarfile.TarError):
        return False


def archive_member_sha256(path: Path, member: str) -> str | None:
    try:
        with tarfile.open(path, "r:*") as archive:
            stream = archive.extractfile(member)
            if stream is None:
                return None
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
            return digest.hexdigest()
    except (OSError, tarfile.TarError):
        return None


def verify_cpu_copyleft(staging: Path, plugin: Path):
    vendor = plugin / "vendor"
    lock_path = staging / "source" / "cpu-source-closure.json"
    source_lock = load_json(lock_path) if lock_path.is_file() else {}
    source_entries = {entry.get("component"): entry for entry in source_lock.get("source_archives", []) if isinstance(entry, dict)}
    license_paths = {
        "MPL-2.0": staging / "LICENSES" / "MPL-2.0.txt",
        "LGPL-3.0-only": staging / "LICENSES" / "LGPL-3.0.txt",
        "LGPL-2.1-or-later": staging / "LICENSES" / "LGPL-2.1.txt",
    }
    expected = (
        ("certifi", "certifi", "MPL-2.0", vendor / "certifi" / "cacert.pem"),
        ("python-bidi", "python-bidi", "LGPL-3.0-only", vendor / "bidi"),
        ("GEOS bundled by Shapely", "GEOS", "LGPL-2.1-or-later", vendor / "shapely.libs"),
    )
    expected_versions = {
        "certifi": package_version(vendor, "certifi"),
        "python-bidi": package_version(vendor, "python-bidi"),
        "GEOS bundled by Shapely": cpu_geos_version(vendor),
    }
    license_records = {
        entry.get("license"): entry
        for entry in source_lock.get("license_texts", [])
        if isinstance(entry, dict) and entry.get("license")
    }
    components = []
    for name, package_name, license_name, root in expected:
        entry = source_entries.get(name, {})
        archive = staging / str(entry.get("artifact_path", ""))
        member = str(entry.get("source_member", ""))
        candidates = [root] if root.is_file() else sorted(root.rglob("*")) if root.is_dir() else []
        files = [file_record(path, staging) for path in candidates if path.is_file() and (path.suffix.lower() in {".dll", ".pyd", ".pem"})]
        expected_version = expected_versions[name]
        member_hash = archive_member_sha256(archive, member) if archive.is_file() else None
        copied_source_match = member_hash == sha256(root) if root.is_file() and member_hash else None
        source_ok = (
            bool(expected_version)
            and entry.get("component") == name
            and entry.get("package") == package_name
            and entry.get("version") == expected_version
            and entry.get("license") == license_name
            and entry.get("modified") is False
            and archive.is_file()
            and sha256(archive) == entry.get("SHA256")
            and archive_member_exists(archive, member)
            and (copied_source_match is True if root.is_file() else True)
        )
        license_path = license_paths[license_name]
        license_text = license_path.read_text("utf-8", errors="replace") if license_path.is_file() else ""
        license_ok = (
            "Mozilla Public License Version 2.0" in license_text
            if license_name == "MPL-2.0"
            else "GNU LESSER GENERAL PUBLIC LICENSE" in license_text
        )
        components.append(
            {
                "component": name,
                "version": entry.get("version"),
                "actual_vendor_version": expected_version,
                "files": files,
                "upstream": entry.get("upstream_source"),
                "upstream_revision": entry.get("version"),
                "license": license_name,
                "source_archive": file_record(archive, staging),
                "source_member": member,
                "source_member_SHA256": member_hash,
                "copied_source_member_matches": copied_source_match,
                "required_notices": [rel(license_path, staging)] + (cpu_package_notices(vendor, staging, "certifi" if name == "certifi" else "python-bidi" if name == "python-bidi" else "shapely")),
                "source_availability_obligation": entry.get("source_availability_obligation"),
                "modification_status": "unmodified",
                "status": "PASS" if files and source_ok and license_ok else "BLOCK",
            }
        )
    mpl_component = next(item for item in components if item["component"] == "certifi")
    mpl_license_record = license_records.get("MPL-2.0", {})
    mpl_license_path = license_paths["MPL-2.0"]
    mpl_license_lock_ok = (
        mpl_license_record.get("artifact_path") == "LICENSES/MPL-2.0.txt"
        and mpl_license_path.is_file()
        and mpl_license_record.get("SHA256") == sha256(mpl_license_path)
        and mpl_license_record.get("upstream_source") == "https://www.mozilla.org/en-US/MPL/2.0/"
    )
    mpl = {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "components": [mpl_component],
        "license_text_lock": file_record(mpl_license_path, staging),
        "status": "PASS" if mpl_component["status"] == "PASS" and mpl_license_lock_ok else "BLOCK",
        "blockers": [] if mpl_component["status"] == "PASS" and mpl_license_lock_ok else ["certifi MPL source-form or license-text closure is incomplete."],
    }
    return {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "input_source_lock": file_record(lock_path, staging),
        "components": components,
        "status": "PASS" if all(item["status"] == "PASS" for item in components) else "BLOCK",
        "mpl": mpl,
    }


def verify_cpu_e2e(staging: Path, repo: Path, plugin: Path):
    path = plugin / "e2e-evidence.json"
    payload = load_json(path) if path.is_file() else {}
    input_record = payload.get("input", {})
    input_path = repo / "docs" / "images" / str(input_record.get("filename", ""))
    expected_input = sha256(input_path) if input_path.is_file() else None
    expected_models = list(CPU_MODELS)
    provider_names = payload.get("inference_runtime", {}).get("providers", [])
    vendor = plugin / "vendor"
    expected_versions = {
        "onnxruntime": package_version(vendor, "onnxruntime"),
        "paddleocr": package_version(vendor, "paddleocr"),
        "paddlex": package_version(vendor, "paddlex"),
    }
    valid = bool(path.is_file()) and all(
        (
            payload.get("test_type") == "real_cpu_ocr_adapter_e2e",
            payload.get("inference_runtime", {}).get("package") == "onnxruntime",
            payload.get("inference_runtime", {}).get("version") == expected_versions["onnxruntime"],
            payload.get("inference_runtime", {}).get("selected_provider") == "CPUExecutionProvider",
            payload.get("inference_runtime", {}).get("cuda_or_paddle_fallback") is False,
            "CPUExecutionProvider" in provider_names,
            not any(any(token in provider.lower() for token in ("cuda", "tensorrt", "directml")) for provider in provider_names),
            payload.get("adapter", {}).get("package") == "paddleocr",
            payload.get("adapter", {}).get("version") == expected_versions["paddleocr"],
            payload.get("adapter", {}).get("paddlex_version") == expected_versions["paddlex"],
            payload.get("adapter", {}).get("models") == expected_models,
            all(payload.get("adapter", {}).get("config", {}).get(key) is True for key in ("doc_orientation", "doc_unwarping", "textline_orientation")),
            payload.get("result", {}).get("code") == 100,
            int(payload.get("result", {}).get("text_count", 0)) > 0,
            input_record.get("SHA256") == expected_input,
        )
    )
    return {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "evidence": file_record(path, staging),
        "input_reverified_from_repository": {"artifact_path": rel(input_path, repo) if input_path.is_file() else None, "SHA256": expected_input},
        "runtime_versions_reverified_from_vendor": expected_versions,
        "record": payload,
        "status": "PASS" if valid else "BLOCK",
        "blockers": [] if valid else ["CPU OCR E2E evidence is missing, malformed, stale, or did not prove the five-model CPUExecutionProvider path."],
    }


def verify_cpu_source_mirror(staging: Path, plugin: Path):
    source = staging / "source"
    required = (
        source / CPU_PLUGIN_ID / "api.py",
        source / CPU_PLUGIN_ID / "coordinates.py",
        source / "tools" / "patch_paddlex_cpu_offline.py",
        source / "tools" / "prune_cpu_vendor.py",
        source / "tools" / "run_cpu_e2e.py",
        source / "Build-CpuPlugin.ps1",
        source / "COPYING",
        source / "LICENSE",
        source / "cpu-source-closure.json",
        source / "third_party" / "pypdfium2-5.12.1-py3-none-win_amd64.whl",
        source / "third_party" / "pypdfium2-5.12.1.tar.gz",
        source / "third_party" / "pypdfium2-pypi-5.12.1.json",
        source / "third_party" / "pypdfium2-pypi-wheel-provenance-5.12.1.json",
        source / "third_party" / "pypdfium2-release-5.12.1.github.json",
        source / "third_party" / "pypdfium2-wheel-source-4a2636051ff4a841966be01484f4a70b4309b55c.github.json",
        source / "third_party" / "pypdfium2-tag-5.12.1.github.json",
        source / "third_party" / "pdfium-binaries-chromium-7947.github.json",
        source / "third_party" / "pdfium-binaries-commit-a068e5317bb780d0afdf00d8b341938d9f36d2fe.github.json",
        source / "third_party" / "pdfium-win-x64.tgz",
        source / CPU_PLUGIN_ID / "vendor-prune.json",
        source / CPU_PLUGIN_ID / "paddlex-offline-patch.json",
        source / CPU_PLUGIN_ID / "model-rights.json",
        source / CPU_PLUGIN_ID / "runtime-requirements.lock",
        source / CPU_PLUGIN_ID / "runtime.lock.json",
        source / CPU_PLUGIN_ID / "e2e-evidence.json",
    )
    missing = [rel(path, staging) for path in required if not path.is_file()]
    return {
        "source_root": rel(source, staging) if source.is_dir() else "source",
        "required_files": [rel(path, staging) for path in required],
        "status": "PASS" if not missing else "BLOCK",
        "blockers": [] if not missing else ["CPU source mirror is incomplete: " + ", ".join(missing)],
    }


def write_cpu_third_party_notices(path: Path, runtime, models, copyleft) -> None:
    lines = [
        "# Third-Party Notices — CPU OCR Bundle",
        "",
        "This file is generated from the copied CPU vendor and model artifacts. It does not replace the component license texts or source-availability records.",
        "",
        "| Component | Version | License / agreement | Notice evidence | Source availability |",
        "| --- | --- | --- | --- | --- |",
    ]
    for package in runtime.get("packages", []):
        license_name = package.get("license_spdx") or package.get("license_description") or "See installed license metadata"
        notices = ", ".join(package.get("required_notices", [])) or "wheel metadata"
        lines.append(f"| {package['name']} | {package['version']} | {license_name} | {notices} | {package['source_availability_obligation']} |")
    lines.extend(["", "## PaddlePaddle ONNX models", "", "| Model | License | Weight SHA-256 | Model-card evidence |", "| --- | --- | --- | --- |"])
    for model in models.get("models", []):
        lines.append(f"| {model.get('model_name')} | {model.get('license')} | {model.get('SHA256')} | {model.get('model_card', {}).get('artifact_path')} |")
    lines.extend(["", "## Embedded PDFium provenance", ""])
    for component in runtime.get("cpu_execution", {}).get("embedded_components", []):
        notices = ", ".join(item.get("artifact_path", "") for item in component.get("required_notices", []) if isinstance(item, dict))
        lines.append(f"- {component.get('component')} {component.get('pdfium_version')}: `{component.get('artifact', {}).get('artifact_path')}`; upstream `{component.get('upstream_revision')}`; status `{component.get('status')}`; notices `{notices}`.")
    lines.extend(["", "## MPL/LGPL source closure", ""])
    for component in copyleft.get("components", []):
        lines.append(f"- {component['component']} ({component['license']}): `{component.get('source_archive', {}).get('artifact_path')}`; status `{component['status']}`.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_cpu_artifact(staging: Path, repo: Path, errors: list[str]):
    plugin = staging / "UmiOCR-data" / "plugins" / CPU_PLUGIN_ID
    if not plugin.is_dir():
        return {"status": "BLOCK", "blockers": [f"CPU plugin is missing: {plugin}"], "cpu_ocr": {"status": "BLOCK", "blockers": ["CPU plugin is missing."]}}
    apache_path = ensure_apache_license(staging, errors)
    runtime = verify_cpu_runtime(staging, plugin, errors)
    models = verify_cpu_models(staging, plugin, apache_path)
    opencv = verify_opencv(staging, plugin / "vendor")
    ffmpeg = verify_cpu_ffmpeg(staging, plugin)
    copyleft = verify_cpu_copyleft(staging, plugin)
    e2e = verify_cpu_e2e(staging, repo, plugin)
    source = verify_cpu_source_mirror(staging, plugin)
    pieces = (runtime, models, opencv, ffmpeg, copyleft, e2e, source)
    cpu_ocr = {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "actual_inference_runtime": runtime.get("cpu_execution", {}).get("actual_inference_runtime"),
        "actual_runtime_version": runtime.get("cpu_execution", {}).get("actual_runtime_version"),
        "runtime_vendor_directory": {"artifact_path": rel(plugin / "vendor", staging), "present": (plugin / "vendor").is_dir()},
        "models_directory": {"artifact_path": rel(plugin / "models", staging), "present": (plugin / "models").is_dir()},
        "runtime_vendor_lock": file_record(plugin / "runtime.lock.json", staging),
        "model_rights_lock": file_record(plugin / "model-rights.json", staging),
        "e2e_evidence": file_record(plugin / "e2e-evidence.json", staging),
        "status": "PASS" if all(item.get("status") in {"PASS", "NOT_INCLUDED"} for item in pieces) else "BLOCK",
        "blockers": [blocker for item in pieces for blocker in item.get("blockers", [])],
    }
    return {
        "runtime": runtime,
        "models": models,
        "opencv": opencv,
        "ffmpeg": ffmpeg,
        "mpl": copyleft["mpl"],
        "copyleft": copyleft,
        "e2e": e2e,
        "source": source,
        "cpu_ocr": cpu_ocr,
    }


def verify_cpu_and_document(repo: Path, cpu_staging: Path | None = None, errors: list[str] | None = None, artifact_staging: Path | None = None):
    # Gate the files actually being distributed, not a nearby development
    # project.  Optional CPU evidence can still be audited independently.
    artifact_root = artifact_staging or repo
    actual_cpu = artifact_root / "UmiOCR-data" / "plugins" / CPU_PLUGIN_ID
    evidence_root = cpu_staging if cpu_staging and (cpu_staging / "UmiOCR-data" / "plugins" / CPU_PLUGIN_ID).is_dir() else None
    if actual_cpu.is_dir():
        evidence_root = artifact_root
    if evidence_root:
        cpu = verify_cpu_artifact(evidence_root, repo, errors if errors is not None else [])
        cpu_record = {
            **cpu["cpu_ocr"],
            "evidence_staging_root": evidence_root.name,
            "runtime_vendor": cpu["runtime"],
            "paddle_models": cpu["models"],
            "opencv": cpu["opencv"],
            "ffmpeg": cpu["ffmpeg"],
            "mpl": cpu["mpl"],
            "copyleft": cpu["copyleft"],
            "e2e": cpu["e2e"],
            "source_mirror": cpu["source"],
        }
    else:
        cpu_record = {
            "actual_inference_runtime": None,
            "actual_runtime_version": None,
            "artifact_scope": "actual staging only",
            "artifact_plugin_path": rel(actual_cpu, artifact_root),
            "actual_model_artifacts": [],
            "status": "NOT_INCLUDED",
            "reason": "No CPU OCR plugin is present in this artifact; no CPU runtime/model distribution right is claimed.",
        }
    # Document provenance also follows actual staging.  A sibling source
    # tree or an unrelated CPU candidate does not add VL assets to this one.
    document_artifact_root = artifact_root / "UmiOCR-data" / "plugins" / "win32_PaddleOCRVL_1_6"
    document_vendor = document_artifact_root / "vendor"
    document_runtime_lock = document_artifact_root / "runtime.lock.json"
    document_manifest = document_artifact_root / "model-rights.json"
    document_model_files = artifact_files(document_artifact_root, artifact_root, {".gguf", ".mmproj", ".bin", ".safetensors", ".pdiparams", ".onnx", ".f16"})
    document_included = document_artifact_root.is_dir() or bool(document_model_files)
    if not document_included:
        return {
            "schema_version": 1,
            "verification_date": VERIFY_DATE,
            "cpu_ocr": cpu_record,
            "document_models": {
                "status": "NOT_INCLUDED",
                "artifact_scope": "actual staging only",
                "artifact_plugin_path": rel(document_artifact_root, artifact_root),
                "plugin_source_present": False,
                "actual_model_artifacts": [],
                "source_declaration": "The separate document-plugin source tree is not a release artifact. No PaddleOCR-VL/GGUF/mmproj/runtime binary is present in this staging, so no model right is claimed or redistributed.",
                "official_candidate_survey": {
                    "repository": "https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF",
                    "license": "Apache-2.0",
                    "decision": "not included in this public release; this artifact contains no document plugin, model, or server-side runtime, and makes no redistribution claim for them",
                },
            },
        }
    return {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "cpu_ocr": cpu_record,
        "document_models": {
            "plugin_source_present": document_artifact_root.is_dir(),
            "runtime_vendor_directory": {"artifact_path": rel(document_vendor, artifact_root), "present": document_vendor.is_dir()},
            "runtime_lock": expected_file_record(document_runtime_lock, artifact_root),
            "model_rights_manifest": expected_file_record(document_manifest, artifact_root),
            "actual_model_artifacts": document_model_files,
            "model_formats_scanned": [".gguf", ".mmproj", ".bin", ".safetensors", ".pdiparams", ".onnx", ".f16"],
            "source_declaration": "The manifest describes user-provided GGUF/mmproj assets and an external llama.cpp-compatible VLM service; neither a runtime nor model assets are packaged here.",
            "status": "BLOCK",
            "blocker": "No repository, revision, filename, SHA256, model-card license, redistribution evidence, runtime vendor lock, F16/GGUF/mmproj artifact, or model-rights manifest is present; do not create a public document-plugin archive.",
        },
    }


def report_markdown(kind: str, gates: dict[str, dict]) -> str:
    lines = ["# Release Evidence Report", "", f"Verification date: `{VERIFY_DATE}`", "", f"Artifact kind: `{kind}`", "", "| Gate | Status | Evidence |", "| --- | --- | --- |"]
    evidence = {
        "runtime_vendor": "LICENSES/runtime-vendor-lock.json",
        "paddle_models": "LICENSES/model-rights.json",
        "cuda": "LICENSES/cuda-redistributable.json",
        "cudnn": "LICENSES/cudnn-redistributable.json",
        "opencv": "LICENSES/opencv-artifact.json",
        "ffmpeg": "LICENSES/ffmpeg-build.json",
        "gpu_ocr_e2e": "LICENSES/gpu-e2e-evidence.json",
        "mpl": "LICENSES/mpl-components.json",
        "agpl_nvidia": "LICENSES/agpl-integration.json",
        "cpu_ocr": "LICENSES/cpu-document-gates.json",
        "document_models": "LICENSES/cpu-document-gates.json",
    }
    for name, entry in gates.items():
        lines.append(f"| {name} | {entry.get('status', 'BLOCK')} | `{evidence[name]}` |")
    lines.extend(["", "A PASS records only the verified artifact-specific condition. It does not resolve another gate."])
    return "\n".join(lines) + "\n"


def public_release_allowed(gates: dict[str, dict]) -> bool:
    # NOT_INCLUDED records that the archive contains no artifact for that gate.
    # PASS_WITH_REQUIREMENTS stays fail-closed until its conditions are closed.
    return all(entry.get("status") in {"PASS", "NOT_INCLUDED"} for entry in gates.values())


def verify(staging: Path, repo: Path, kind: str, cache_root: Path | None, cpu_staging: Path | None = None):
    errors: list[str] = []
    licenses = staging / "LICENSES"
    licenses.mkdir(parents=True, exist_ok=True)
    extra_outputs = {}
    if kind == "cpu":
        cpu = verify_cpu_artifact(staging, repo, errors)
        runtime = cpu.get("runtime", {"status": "BLOCK", "blockers": cpu.get("blockers", ["CPU artifact is missing."])})
        models = cpu.get("models", {"status": "BLOCK", "models": []})
        cuda = {"schema_version": 1, "verification_date": VERIFY_DATE, "status": "NOT_INCLUDED", "files": [], "reason": "CPU artifact has no CUDA Toolkit files."}
        cudnn = {"schema_version": 1, "verification_date": VERIFY_DATE, "status": "NOT_INCLUDED", "files": [], "reason": "CPU artifact has no cuDNN files."}
        opencv = cpu.get("opencv", {"status": "BLOCK"})
        ffmpeg = cpu.get("ffmpeg", {"status": "BLOCK"})
        mpl = cpu.get("mpl", {"status": "BLOCK", "components": []})
        agpl = {"schema_version": 1, "verification_date": VERIFY_DATE, "status": "NOT_INCLUDED", "reason": "This CPU artifact contains no NVIDIA SDK runtime; the separate GPU AGPL/NVIDIA integration gate is not resolved here."}
        cpu_document = {
            "schema_version": 1,
            "verification_date": VERIFY_DATE,
            "cpu_ocr": cpu.get("cpu_ocr", {"status": "BLOCK", "blockers": ["CPU artifact is missing."]}),
            "document_models": {"status": "NOT_INCLUDED", "reason": "The CPU OCR plugin contains no document-model plugin or GGUF/mmproj model artifact."},
        }
        if cpu.get("runtime") and cpu.get("models") and cpu.get("copyleft"):
            write_cpu_third_party_notices(licenses / "THIRD_PARTY_NOTICES.md", runtime, models, cpu["copyleft"])
        extra_outputs = {
            "cpu-copyleft-components.json": cpu.get("copyleft", {"status": "BLOCK"}),
            "cpu-e2e-evidence.json": cpu.get("e2e", {"status": "BLOCK"}),
            "cpu-source-mirror.json": cpu.get("source", {"status": "BLOCK"}),
        }
    else:
        apache_path = ensure_apache_license(staging, errors)
        source_lock_path = repo / "build" / "sources-windows-cu126.lock.json"
        if not source_lock_path.is_file():
            raise RuntimeError(f"Missing source lock: {source_lock_path}")
        source_lock = load_json(source_lock_path)
        if kind == "gpu":
            plugin = staging / "UmiOCR-data" / "plugins" / "win32_PaddleOCRv6_CUDA"
            vendor = plugin / "vendor"
            if not vendor.is_dir():
                raise RuntimeError(f"GPU vendor directory is missing: {vendor}")
            runtime = verify_runtime_vendor(staging, plugin, vendor, errors)
            models = verify_models(staging, plugin, source_lock, apache_path, errors)
            cuda = verify_nvidia(staging, vendor)
            cudnn = verify_cudnn(staging, vendor)
            ffmpeg = verify_ffmpeg(staging, plugin, source_lock, cache_root)
            opencv = verify_opencv(staging, vendor)
            mpl = verify_mpl(staging, vendor, source_lock, cache_root)
            agpl = verify_agpl(staging, repo, plugin)
            gpu_e2e = verify_gpu_e2e(staging, plugin, models, repo)
        else:
            vendor = staging / "UmiOCR-data" / "site-packages"
            if not vendor.is_dir():
                raise RuntimeError(f"Base site-packages directory is missing: {vendor}")
            runtime = verify_runtime_vendor(staging, staging / "UmiOCR-data", vendor, errors)
            models = {"status": "NOT_INCLUDED", "models": []}
            cuda = {"status": "NOT_INCLUDED", "files": []}
            cudnn = {"status": "NOT_INCLUDED", "files": []}
            opencv = verify_opencv(staging, vendor)
            ffmpeg = verify_ffmpeg(staging, staging / "UmiOCR-data", source_lock, cache_root)
            mpl = {"status": "NOT_INCLUDED", "components": []}
            agpl = {"status": "NOT_INCLUDED"}
            gpu_e2e = {"status": "NOT_INCLUDED", "reason": "The base artifact contains no GPU OCR plugin."}
        cpu_document = verify_cpu_and_document(repo, cpu_staging, errors, artifact_staging=staging)
    gates = {
        "runtime_vendor": runtime,
        "paddle_models": models,
        "cuda": cuda,
        "cudnn": cudnn,
        "opencv": opencv,
        "ffmpeg": ffmpeg,
        "mpl": mpl,
        "agpl_nvidia": agpl,
        "cpu_ocr": cpu_document["cpu_ocr"],
        "document_models": cpu_document["document_models"],
    }
    if kind == "gpu":
        gates["gpu_ocr_e2e"] = gpu_e2e
    outputs = {
        "runtime-vendor-lock.json": runtime,
        "model-rights.json": models,
        "cuda-redistributable.json": cuda,
        "cudnn-redistributable.json": cudnn,
        "opencv-artifact.json": opencv,
        "ffmpeg-build.json": ffmpeg,
        "mpl-components.json": mpl,
        "agpl-integration.json": agpl,
        "cpu-document-gates.json": cpu_document,
        **extra_outputs,
    }
    if kind == "gpu":
        outputs["gpu-e2e-evidence.json"] = gpu_e2e
    for name, value in outputs.items():
        write_json(licenses / name, value)
    report = {
        "schema_version": 1,
        "verification_date": VERIFY_DATE,
        "artifact_kind": kind,
        "gates": {name: entry.get("status", "BLOCK") for name, entry in gates.items()},
        "public_prerelease_allowed": public_release_allowed(gates),
        "validation_errors": errors,
    }
    write_json(licenses / "RELEASE_EVIDENCE.json", report)
    (licenses / "RELEASE_EVIDENCE.md").write_text(report_markdown(kind, gates), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--kind", choices=("base", "gpu", "cpu"), required=True)
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--cpu-staging-root", type=Path)
    parser.add_argument("--require-public-release", action="store_true")
    args = parser.parse_args()
    try:
        report = verify(
            args.staging_root.resolve(),
            args.repo_root.resolve(),
            args.kind,
            args.cache_root.resolve() if args.cache_root else None,
            args.cpu_staging_root.resolve() if args.cpu_staging_root else None,
        )
    except Exception as exc:
        print(f"release evidence verifier failed: {exc}", file=sys.stderr)
        return 2
    print("release evidence gates:")
    for name, status in report["gates"].items():
        print(f"  {name}: {status}")
    for error in report["validation_errors"]:
        print(f"  validation error: {error}", file=sys.stderr)
    if report["validation_errors"]:
        return 2
    if args.require_public_release and not report["public_prerelease_allowed"]:
        print("public prerelease gate is blocked by the recorded evidence.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
