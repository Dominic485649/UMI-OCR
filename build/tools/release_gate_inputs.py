"""Read-only, fail-closed inputs for artifact publication gates.

The canonical source mirror is compared with public Git objects. Artifact-derived
reports are written separately by verify_release_evidence.py, never into source/.
Only current_source_e2e can accept explicitly authorized manual-test limitations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_ID = "win32_PaddleOCRv6_CUDA"
PUBLIC_REPOSITORIES = {
    "host": "https://github.com/Dominic485649/UMI-OCR",
    "cuda": "https://github.com/Dominic485649/UMI-OCR_plugins",
}
RELEASE_GATES = ("source_delivery", "current_source_e2e")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
METADATA_NAMES = {
    "COPYING", "LICENSE", "NOTICE.md", "SOURCE-CODE.md", "source-snapshot.zip",
    "source-snapshot.json", "source-provenance.json", "source-export.json",
}
MANUAL_CHECKS = {"full_desktop_capture", "manual_hdr_acceptance", "mixed_monitor_hdr_sdr"}
AUTOMATED_CHECKS = {"base_tests", "combined_tests", "gui", "tray", "gpu_workflows", "gpu_workflow_log"}


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def read_json(path: Path):
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("JSON input exceeds the size limit")
    return json.loads(path.read_text("utf-8-sig"), object_pairs_hook=_object)


def no_links(path: Path) -> None:
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError("release inputs must not traverse links or junctions")


def artifact_metadata_root(staging: Path, kind: str | None = None) -> Path:
    """Map an install overlay in place; do not manufacture root-level records."""
    staging = staging.absolute()
    no_links(staging)
    nested = staging / "LICENSES" / "plugins" / PLUGIN_ID
    if kind not in (None, "gpu") or not nested.exists():
        return staging
    if not nested.is_dir():
        raise ValueError("CUDA overlay metadata is not a directory")
    expected = (
        (staging, {"UmiOCR-data", "LICENSES"}),
        (staging / "UmiOCR-data", {"plugins"}),
        (staging / "UmiOCR-data/plugins", {PLUGIN_ID}),
        (staging / "LICENSES", {"plugins"}),
        (staging / "LICENSES/plugins", {PLUGIN_ID}),
    )
    for directory, names in expected:
        no_links(directory)
        if not directory.is_dir() or {item.name for item in directory.iterdir()} != names:
            raise ValueError("CUDA overlay has ambiguous, conflicting, or unexpected root records")
    no_links(nested)
    return nested


def checked_metadata_root(staging: Path, kind: str) -> Path:
    metadata = artifact_metadata_root(staging, kind)
    for item in staging.rglob("*"):
        if item.is_symlink() or item.is_junction():
            raise ValueError("release trees must not contain links or junctions")
    return metadata


def metadata_path(staging: Path, relative: str) -> Path:
    return artifact_metadata_root(staging) / relative


def _files(root: Path) -> dict[str, str]:
    no_links(root)
    if not root.is_dir():
        raise ValueError("required release input tree is missing")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise ValueError("release trees must not contain links or junctions")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if any(part in {".git", "__pycache__"} for part in path.relative_to(root).parts):
            raise ValueError("private/generated files in a release binding")
        if any(ord(character) < 32 for character in relative):
            raise ValueError("control characters in a bound filename")
        result[relative] = digest(path)
    if not result:
        raise ValueError("empty release input tree")
    return result


def tree_binding(records: dict[str, str]) -> dict:
    checksum = hashlib.sha256()
    for name, value in sorted(records.items()):
        checksum.update(name.encode("utf-8") + b"\0" + value.encode("ascii") + b"\n")
    return {"files": len(records), "sha256": checksum.hexdigest()}


def artifact_inputs(staging: Path, kind: str):
    metadata = artifact_metadata_root(staging, kind)
    all_files = _files(staging)
    payload = {
        name: value for name, value in all_files.items()
        if name.split("/", 1)[0] not in {"LICENSES", "source"}
        and name not in METADATA_NAMES
    }
    if not payload:
        raise ValueError("empty execution payload")
    source = _files(metadata / "source")
    identity = (staging / "UmiOCR-data/about.json") if kind == "base" else (
        staging / "UmiOCR-data/plugins" / PLUGIN_ID / "umi-plugin.json"
    )
    document = read_json(identity)
    version = document.get("version")
    if isinstance(version, dict):
        version = ".".join(str(version.get(key, "")) for key in ("major", "minor", "patch"))
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("invalid release version in the actual artifact")
    binding = {
        "algorithm": "sha256-path-nul-file-sha256-lf-v1",
        "payload": tree_binding(payload),
        "source": tree_binding(source),
    }
    return version, binding, source


def _same_binding(value, actual) -> bool:
    # JSON comparison also distinguishes true from 1 and refuses extra fields.
    return json.dumps(value, sort_keys=True) == json.dumps(actual, sort_keys=True)


def _git(arguments, *, cwd: Path, input_data: bytes | None = None, anonymous=False):
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_NO_LAZY_FETCH"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    if anonymous:
        for key in list(environment):
            if key.startswith("GIT_CONFIG_") or key in {
                "GIT_ASKPASS", "SSH_ASKPASS", "GIT_SSL_NO_VERIFY", "GIT_DIR",
                "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_INDEX_FILE",
            }:
                environment.pop(key, None)
        environment.update({
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never",
            "GIT_ASKPASS": "", "SSH_ASKPASS": "",
        })
    result = subprocess.run(
        ["git", *arguments], cwd=cwd, env=environment, input=input_data,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180, check=False,
    )
    if result.returncode:
        # Do not put local checkout paths, credentials, or command stderr in a public report.
        raise ValueError("Git object/public reference verification failed")
    return result.stdout


def public_tag(url: str, tag: str, commit: str, *, cwd: Path) -> dict:
    reference = f"refs/tags/{tag}"
    output = _git([
        "-c", "credential.helper=", "-c", "core.askPass=", "-c", "http.extraHeader=",
        "-c", "http.followRedirects=false", "ls-remote", "--exit-code", url,
        reference, reference + "^{}",
    ], cwd=Path(cwd.anchor), anonymous=True).decode("ascii")
    refs = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or not COMMIT.fullmatch(fields[0]) or fields[1] not in {reference, reference + "^{}"} or fields[1] in refs:
            raise ValueError("invalid or ambiguous public tag response")
        refs[fields[1]] = fields[0]
    if reference not in refs or refs.get(reference + "^{}", refs.get(reference)) != commit:
        raise ValueError("public tag does not resolve to the declared commit")
    return refs


def git_source_matches(checkout: Path, commit: str, source: dict[str, str]) -> None:
    if not checkout.is_absolute() or not checkout.is_dir():
        raise ValueError("source receipt requires an existing absolute checkout path")
    no_links(checkout)
    tree = _git(["ls-tree", "-r", "-z", commit], cwd=checkout)
    objects = {}
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, object_type, oid = header.split(b" ")
        if mode not in {b"100644", b"100755"} or object_type != b"blob" or not COMMIT.fullmatch(oid.decode("ascii")):
            raise ValueError("public source tree contains a link or unsupported Git object")
        filename = name.decode("utf-8")
        if filename in objects:
            raise ValueError("duplicate public source path")
        objects[filename] = oid
    if set(objects) != set(source):
        raise ValueError("packaged source member set differs from the public commit")
    names = sorted(source)
    content = _git(["cat-file", "--batch"], cwd=checkout, input_data=b"".join(objects[name] + b"\n" for name in names))
    offset = 0
    for name in names:
        end = content.find(b"\n", offset)
        if end < 0:
            raise ValueError("truncated Git object response")
        header = content[offset:end].split(b" ")
        if len(header) != 3 or header[0] != objects[name] or header[1] != b"blob":
            raise ValueError("unexpected Git source object")
        length = int(header[2])
        offset = end + 1
        if length < 0 or offset + length >= len(content) or content[offset + length:offset + length + 1] != b"\n":
            raise ValueError("truncated Git source blob")
        if hashlib.sha256(memoryview(content)[offset:offset + length]).hexdigest() != source[name]:
            raise ValueError("packaged source bytes differ from the public commit")
        offset += length + 1
    if offset != len(content):
        raise ValueError("unexpected trailing Git object data")


def verify_source_delivery(record, kind: str, version: str, source: dict[str, str], staging: Path) -> dict:
    if not isinstance(record, dict) or record.get("status") != "PASS":
        raise ValueError("source_delivery must explicitly be PASS")
    repositories = record.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        raise ValueError("public source repository receipts are missing")
    required = "host" if kind == "base" else "cuda"
    seen = set()
    public = []
    for item in repositories:
        if not isinstance(item, dict):
            raise ValueError("malformed public source receipt")
        role = item.get("role")
        if role not in PUBLIC_REPOSITORIES or role in seen:
            raise ValueError("unknown or duplicate public source repository role")
        seen.add(role)
        url, tag, commit = item.get("url"), item.get("tag"), item.get("commit")
        if url not in {PUBLIC_REPOSITORIES[role], PUBLIC_REPOSITORIES[role] + ".git"}:
            raise ValueError("public source URL does not match the product repository")
        if tag != f"v{version}" or not isinstance(commit, str) or not COMMIT.fullmatch(commit):
            raise ValueError("public source tag/commit does not match the release")
        refs = public_tag(url, tag, commit, cwd=staging)
        source_matches = role == required
        if source_matches:
            checkout = item.get("checkout")
            if not isinstance(checkout, str):
                raise ValueError("public source checkout is missing")
            git_source_matches(Path(checkout), commit, source)
        public.append({
            "role": role, "url": url, "tag": tag, "commit": commit,
            "anonymous_tag_verified": True, "public_refs": refs,
            "packaged_source_matches_commit": source_matches,
        })
    if required not in seen:
        raise ValueError("the product's corresponding public source receipt is missing")
    return {"status": "PASS", "verified": True, "repositories": public, "blockers": []}


def evidence_file(record):
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise ValueError("evidence needs exactly path and sha256")
    path, expected = record["path"], record["sha256"]
    if not isinstance(path, str) or not Path(path).is_absolute() or not isinstance(expected, str) or not SHA256.fullmatch(expected):
        raise ValueError("invalid evidence path or SHA256")
    local = Path(path)
    no_links(local)
    if not local.is_file() or digest(local) != expected:
        raise ValueError("real evidence is missing or its SHA256 changed")
    return local, {"name": local.name, "sha256": expected}


def _gpu_record(path: Path, staging: Path, metadata: Path, automated: dict) -> None:
    plugin = staging / "UmiOCR-data/plugins" / PLUGIN_ID
    record = read_json(path)
    if digest(path) != digest(plugin / "gpu-e2e-evidence.json"):
        raise ValueError("GPU input evidence is not the raw record shipped with this payload")
    if record.get("test_type") != "real_gpu_ocr_workflows_e2e" or record.get("status") != "PASS" or not re.fullmatch(r"gpu:[0-9]+", str(record.get("device", ""))):
        raise ValueError("GPU evidence does not prove a real successful CUDA workflow")
    if record.get("plugin_runtime_lock_sha256") != digest(plugin / "runtime.lock.json"):
        raise ValueError("GPU evidence runtime binding is stale")
    actual_sources = {
        item.relative_to(plugin).as_posix(): digest(item)
        for item in sorted(plugin.rglob("*.py"))
        if not {"vendor", "models", "__pycache__"} & set(item.relative_to(plugin).parts)
    }
    if not actual_sources or record.get("plugin_source_sha256") != actual_sources:
        raise ValueError("GPU evidence adapter-source binding is stale")
    workflow = record.get("workflow_test", {})
    if workflow.get("SHA256") != digest(metadata / "source/tests/test_ocr_workflows.py"):
        raise ValueError("GPU workflow test-source binding is stale")
    log = record.get("workflow_log", {})
    filename = log.get("file", log.get("path", ""))
    expected = log.get("SHA256")
    if not isinstance(filename, str) or not filename or not isinstance(expected, str) or not SHA256.fullmatch(expected):
        raise ValueError("GPU workflow log binding is missing")
    candidates = [Path(filename)] if Path(filename).is_absolute() else []
    for name in ("gpu_workflow_log", "combined_tests", "base_tests"):
        reference = automated.get(name, {})
        if isinstance(reference.get("path"), str):
            candidates.append(Path(reference["path"]))
    matched = False
    for candidate in candidates:
        if candidate.name == Path(filename).name and candidate.is_file():
            no_links(candidate)
            if digest(candidate) == expected:
                matched = True
                break
    if not matched:
        raise ValueError("GPU workflow log binding is missing or stale")


def verify_current_source(record, kind: str, binding: dict, staging: Path, authorized: bool) -> dict:
    if not isinstance(record, dict) or record.get("status") not in {"PASS", "ACCEPTED_WITH_LIMITATIONS"}:
        raise ValueError("current_source_e2e is missing, blocked, or has an unsupported status")
    if not authorized or not _same_binding(record.get("binding"), binding):
        raise ValueError("publication authorization or current source/payload binding is missing")
    automated = record.get("automated_evidence")
    required = {"base_tests", "combined_tests", "gui", "tray"}
    if kind == "gpu":
        required.update({"gpu_workflows", "gpu_workflow_log"})
    if not isinstance(automated, dict) or not required <= set(automated) or not set(automated) <= AUTOMATED_CHECKS:
        raise ValueError("required real automated evidence is missing or unknown")
    verified_evidence = {}
    for name, reference in automated.items():
        path, public = evidence_file(reference)
        if name in {"base_tests", "combined_tests"}:
            text = path.read_text("utf-8-sig", errors="strict")
            marker = "Base regression suite passed" if name == "base_tests" else "Combined regression suite passed"
            if marker not in text or re.search(r"(?m)^(?:FAILED(?:\s|:)|FAIL:|ERROR:)", text):
                raise ValueError("automated regression log does not record a successful suite")
        elif name == "gui":
            result = read_json(path)
            if result.get("hot") is not True or result.get("errors") != []:
                raise ValueError("current GUI hot-run evidence did not pass")
        elif name == "tray":
            result = read_json(path)
            if result.get("status") != "PASS" or type(result.get("exit_code")) is not int or result["exit_code"] != 0 or result.get("http_ready_before_quit") is not True:
                raise ValueError("current tray/HTTP-readiness evidence did not pass")
        elif name == "gpu_workflow_log":
            text = path.read_text("utf-8-sig", errors="strict")
            if "OCR workflow tests passed:" not in text or re.search(r"(?m)^(?:FAILED(?:\s|:)|FAIL:|ERROR:)", text):
                raise ValueError("the real GPU workflow log did not pass")
            if "gpu_workflows" not in automated:
                raise ValueError("a GPU workflow log needs its source-bound raw record")
        else:
            _gpu_record(path, staging, artifact_metadata_root(staging, kind), automated)
        verified_evidence[name] = public
    manual = record.get("manual_checks")
    untested = record.get("unverified_scenarios")
    if not isinstance(manual, dict) or set(manual) != MANUAL_CHECKS or any(value not in {"PASS", "NOT_RUN"} for value in manual.values()):
        raise ValueError("manual coverage must preserve explicit PASS/NOT_RUN for each named check")
    if not isinstance(untested, list) or any(not isinstance(item, str) or not item.strip() for item in untested):
        raise ValueError("unverified scenarios must be an explicit list")
    acceptance = None
    if record["status"] == "ACCEPTED_WITH_LIMITATIONS":
        acceptance = record.get("user_acceptance")
        if "NOT_RUN" not in manual.values() or not untested or not isinstance(acceptance, dict):
            raise ValueError("limited acceptance requires disclosed untested manual scenarios")
        for field in ("source", "hdr_capture_success_quote", "limitations_disclosure_quote", "publication_quote"):
            if not isinstance(acceptance.get(field), str) or not acceptance[field].strip():
                raise ValueError("original user confirmation/disclosure text is missing")
        if acceptance.get("hdr_capture_success") is not True or acceptance.get("publish_with_untested_mixed_monitors") is not True or not _same_binding(acceptance.get("binding"), binding):
            raise ValueError("explicit, payload-bound user acceptance is missing")
        hdr = acceptance["hdr_capture_success_quote"]
        if "hdr" not in hdr.lower() or not any(word in hdr.lower() for word in ("成功", "success")):
            raise ValueError("the user's HDR-success statement is missing")
        if not any(word in acceptance["limitations_disclosure_quote"].lower() for word in ("混合", "mixed", "多屏")) or not any(word in acceptance["publication_quote"].lower() for word in ("发布", "release")):
            raise ValueError("mixed-monitor disclosure or original release approval is missing")
        confirmation, public_confirmation = evidence_file(acceptance.get("record"))
        confirmation_text = confirmation.read_text("utf-8-sig")
        for field in ("hdr_capture_success_quote", "limitations_disclosure_quote", "publication_quote"):
            if acceptance[field] not in confirmation_text:
                raise ValueError("the original confirmation record does not contain the quoted decision/disclosure")
        if re.search(r"(?:[A-Za-z]:[\\\\/]|\\\\\\\\|/(?:home|Users)/)", acceptance["source"]):
            raise ValueError("the public confirmation locator must not contain a host filesystem path")
        acceptance = {key: acceptance[key] for key in (
            "source", "hdr_capture_success", "hdr_capture_success_quote",
            "publish_with_untested_mixed_monitors", "limitations_disclosure_quote",
            "publication_quote", "binding",
        )}
        acceptance["record"] = public_confirmation
    else:
        if any(value != "PASS" for value in manual.values()) or untested:
            raise ValueError("a full PASS cannot contain untested manual checks")
        evidence = record.get("manual_evidence")
        if not isinstance(evidence, dict) or set(evidence) != MANUAL_CHECKS:
            raise ValueError("full manual PASS needs actual per-check evidence")
        verified_evidence["manual"] = {}
        for name, reference in evidence.items():
            path, public = evidence_file(reference)
            result = read_json(path)
            if result.get("status") != "PASS" or result.get("check") != name or not _same_binding(result.get("binding"), binding):
                raise ValueError("manual PASS evidence is stale or invalid")
            verified_evidence["manual"][name] = public
    return {
        "status": record["status"], "verified": True, "publication_authorized": True,
        "binding": binding, "automated_evidence": verified_evidence,
        "manual_checks": manual, "unverified_scenarios": untested,
        "user_acceptance": acceptance, "blockers": [],
    }


def validate_release_gates(path: Path | None, staging: Path, kind: str, previous: dict | None = None) -> dict:
    previous = previous or {}
    result = {}
    for name in RELEASE_GATES:
        old = previous.get(name, {})
        recorded = previous.get("gates", {}).get(name, old.get("status") if isinstance(old, dict) else None)
        result[name] = {
            "status": "BLOCK", "verified": False, "previous_recorded_status": recorded,
            "blockers": ["A fresh --release-gates input and successful verification are required."],
        }
    if path is None:
        return result
    try:
        document = read_json(path)
        version, binding, source = artifact_inputs(staging, kind)
        if not isinstance(document, dict) or type(document.get("schema_version")) is not int or document["schema_version"] != 1 or document.get("artifact_kind") != kind or document.get("release_version") != version:
            raise ValueError("release-gates schema, artifact kind, or release version does not match")
        authorized = document.get("publication_authorized") is True
        if not authorized:
            raise ValueError("publication_authorized must explicitly be true")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        for gate in result.values():
            gate["blockers"] = [str(exc) if isinstance(exc, ValueError) else "Cannot read or bind release-gates inputs."]
        return result
    for name, verifier in (
        ("source_delivery", lambda: verify_source_delivery(document.get("source_delivery"), kind, version, source, staging)),
        ("current_source_e2e", lambda: verify_current_source(document.get("current_source_e2e"), kind, binding, staging, authorized)),
    ):
        try:
            result[name] = verifier()
        except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
            result[name]["blockers"] = [str(exc) if isinstance(exc, ValueError) else "Cannot verify real release-gate evidence."]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--kind", choices=("base", "gpu"), required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--print-binding", action="store_true")
    mode.add_argument("--describe-layout", action="store_true")
    mode.add_argument("--release-gates", type=Path)
    args = parser.parse_args()
    try:
        root = args.staging_root.absolute()
        if args.describe_layout:
            metadata = checked_metadata_root(root, args.kind)
            print(json.dumps({"metadata_root": str(metadata)}, ensure_ascii=False))
            return 0
        if args.print_binding:
            version, binding, _ = artifact_inputs(root, args.kind)
            print(json.dumps({"schema_version": 1, "artifact_kind": args.kind, "release_version": version, "binding": binding}, ensure_ascii=False, indent=2))
            return 0
        gates = validate_release_gates(args.release_gates, root, args.kind)
        print(json.dumps(gates, ensure_ascii=False, indent=2))
        return 0 if all(gate.get("verified") is True for gate in gates.values()) else 1
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"release-gates input verification failed ({type(exc).__name__}).", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
