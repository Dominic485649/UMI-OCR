"""复用本轮窗口场景验收实际 Stored 组合包，不从工作区加载业务源码。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def new_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def run(args):
    native = load("packaged_refinement_scenario", ROOT / "tests/test_ui_refinement_native.py")
    stored = load("packaged_refinement_provenance", ROOT / "tests/test_stored_native_ui.py")
    packaging = load("packaged_refinement_payload", ROOT / "build/tools/package_local_review.py")
    work, package, audit = map(packaging.layout.plain_path, (args.work_root, args.root, args.output))
    assert work.parent == ROOT / "build/tmp" and work.is_dir()
    assert package.parent == work and package.is_dir()
    audit.relative_to(ROOT / "build/audit")
    assert not audit.exists()
    assert not packaging.merge.running_processes(package)
    data = package / "UmiOCR-data"
    assert Path(sys.executable).resolve() == data / "runtime/python.exe"
    assert sys.flags.isolated and sys.flags.dont_write_bytecode
    for name in (".settings", ".pre_settings", "themes.json", "plugins/.plugins_state"):
        assert not (data / name).exists(), "只接纳全新归档重装，不读取任何已有配置"
    before = packaging.payload(package)
    before_dirs = {path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_dir()}
    audit.mkdir()
    host_audit, container_refs = stored.audit_containers(package, audit)
    binding = stored.bind_archive(package, host_audit)
    about = json.loads((data / "about.json").read_text("utf-8-sig"))
    assert [about["version"][name] for name in ("major", "minor", "patch")] == [3, 1, 1]
    identities = {}
    for identity, version in ((native.PP, "3.0.5"), (native.VL, "3.1.1")):
        manifest = json.loads((data / "plugins" / identity / "umi-plugin.json").read_text("utf-8-sig"))
        assert manifest["id"] == identity and manifest["version"] == version
        identities[identity] = version
    for name in ("os-temp", "os-cache", "os-roaming", "os-local", "qt-cache", "fixtures", "exports"):
        assert not (package / name).exists()
        (package / name).mkdir()
    # 在当前组合包自己的依赖中生成无敏感预览输入，不读取模型和用户文档。
    sys.path[:0] = [str(data / "site-packages"), str(data / "dependencies.zip")]
    import fitz
    pdf = package / "fixtures/three-pages.pdf"
    with fitz.open() as document:
        for number, color in enumerate(((.96, .89, .80), (.85, .96, .85), (.83, .89, .98)), 1):
            page = document.new_page(width=420, height=600)
            page.draw_rect(page.rect, color=color, fill=color)
            page.insert_text((35, 80), f"PREVIEW FIXTURE - PAGE {number}", fontsize=22)
            page.insert_text((35, 125), "Visible before document parsing starts.", fontsize=13)
        document.save(str(pdf))
    image = package / "fixtures/one-page.png"
    with fitz.open(pdf) as document:
        document[0].get_pixmap().save(str(image))
    critical = [data / name for name in ("main.py", "about.json", "app.zip", "dependencies.zip", "runtime-archives.json", "runtime-archive-inputs.json", "runtime_archive_bootstrap.py")]
    critical += [package / "source-snapshot.json", package / "source-snapshot.zip"]
    critical += list((data / "i18n").glob("*.qm"))
    critical += list((data / "qt_res/qml").rglob("*.qml"))
    for identity in (native.PP, native.VL):
        critical += [data / "plugins" / identity / name for name in ("umi-plugin.json", "vendor.zip", "runtime-archives.json")]
    critical += [data / "plugins" / native.VL / name for name in ("StructuredDocument.qml", "page.py")]
    dependencies = [data / name for name in ("runtime/python.exe", "runtime/python313.dll", "runtime/python313.zip", "site-packages/shiboken6/Shiboken.pyd",
        "site-packages/shiboken6/shiboken6.abi3.dll", "site-packages/PySide6/Qt6Core.dll", "site-packages/PySide6/Qt6Qml.dll",
        "site-packages/PySide6/Qt6Quick.dll", "site-packages/PySide6/plugins/platforms/qwindows.dll")]
    # 复用场景输入结构，显式声明为实际组合包，未创建或混入源运行副本。
    input_manifest = {"format": "ui-refinement-native-source-v1", "inputMode": "actual-reinstalled-stored-package",
        "sandbox": str(package), "runtime": str(data), "source_inputs": {str(path): sha(path) for path in critical},
        "snapshot_inputs": {}, "dependency_inputs": {str(path): sha(path) for path in dependencies},
        "fixtures": {str(path): sha(path) for path in (pdf, image)}, "sourceSnapshotBinding": binding["sourceSnapshotSha256"],
        "scope": "实际归档重装的组合包及其Python/Qt/QML/QM；业务模块必须来自本包app.zip。逐页结果为受控回调，不是模型推理；不读取用户配置。"}
    manifest_path = audit / "input.json"
    new_json(manifest_path, input_manifest)
    native.WORK, native.AUDIT, native.RUNTIME = work, audit, data
    native.HELPER.trusted_probe = lambda executable, argv, cwd, python, source_data, bootstrap: (
        Path(python).resolve() == data / "runtime/python.exe" and Path(source_data).resolve() == data
        and stored.allowed_probe(executable, argv, cwd, package, bootstrap))
    status = native.run_native(manifest_path, audit / "window-report.json")
    window = json.loads((audit / "window-report.json").read_text("utf-8"))
    assert not packaging.merge.running_processes(package)
    origins = {}
    for name, origin in window.get("business_module_sources", {}).items():
        member = stored.member_origin(origin, data)
        assert member in {item["path"] for item in host_audit["members"]}
        import zipfile
        with zipfile.ZipFile(data / "app.zip") as archive:
            digest = hashlib.sha256(archive.read(member)).hexdigest()
        assert digest == binding["snapshot"].get("host/UmiOCR-data/" + member)
        origins[name] = {"origin": origin, "member": member, "sha256": digest}
    after = packaging.payload(package)
    assert all(after.get(name) == checksum for name, checksum in before.items()), "产品原字节发生变化，保留现场"
    added = sorted(set(after) - set(before))
    allowed_files = {"UmiOCR-data/.settings", "UmiOCR-data/.pre_settings", "UmiOCR-data/themes.json", "UmiOCR-data/plugins/.plugins_state"}
    allowed_prefixes = ("os-temp/", "os-cache/", "os-roaming/", "os-local/", "qt-cache/", "fixtures/", "exports/", "UmiOCR-data/logs/")
    assert all(name in allowed_files or name.startswith(allowed_prefixes) for name in added), added
    preserved = work / (audit.name + "-generated-originals")
    assert not preserved.exists()
    preserved.mkdir()
    moves = []
    for name in added:
        source, target = package / name, preserved / name
        target.parent.mkdir(parents=True, exist_ok=True)
        assert sha(source) == after[name] and not target.exists()
        source.rename(target)
        assert sha(target) == after[name]
        moves.append({"from": str(source), "to": str(target), "sha256": after[name]})
    new_dirs = [path for path in package.rglob("*") if path.is_dir() and path.relative_to(package).as_posix() not in before_dirs]
    for path in sorted(new_dirs, key=lambda item: len(item.parts), reverse=True):
        assert not list(path.iterdir())
        path.rmdir()
    assert packaging.payload(package) == before
    result = {"status": "PASS" if status == 0 and origins and window["status"] == "PASS" else "FAIL", "root": str(package),
        "versions": {"base": "3.1.1", **identities}, "containerAudits": container_refs, "loadedBusinessModules": origins,
        "windowReport": str(audit / "window-report.json"), "windowReportSha256": sha(audit / "window-report.json"),
        "productRestored": True, "productFiles": len(before), "preservedGeneratedOriginals": moves,
        "driverSha256": sha(__file__), "reusedScenarioSha256": sha(ROOT / "tests/test_ui_refinement_native.py"),
        "modelInference": "NOT_RUN", "userSettings": "NOT_READ", "boundary": "真实组合包原生Qt+受控逐页回调；不是正常EXE或GPU推理，原件移出不冒称删除。"}
    new_json(audit / "result.json", result)
    print(json.dumps({"status": result["status"], "productFiles": len(before), "loadedPackagedModules": len(origins), "result": str(audit / "result.json")}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))
