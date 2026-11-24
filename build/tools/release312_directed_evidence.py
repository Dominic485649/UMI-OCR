"""本次三组件审查的精确有限验收；不继承旧版审批，不制造截图/HDR通过。"""
from __future__ import annotations

import hashlib
from pathlib import Path

SCOPE = "release-3.1.2-directed-no-capture"
VERSIONS = {"base": "3.1.2", "gpu": "3.0.5"}
RUNTIME_BINDINGS = {
    "base": {"files": 1900, "sha256": "3551c1bd2a9c7466daaababe45eeda0ea6035beb5dff43bb673e6a999c514a09"},
    "gpu": {"files": 9595, "sha256": "0bbc17a3e298164fe47d302e03e5acba8520aee1e6786fb3679ecf9c1e41f2ea"},
}
AUTHORIZATION_SHA256 = "c1f2a4148c24c3f096088129082f92be15151754084d58ce751daab19733c920"
HOST_PRODUCT_RECORD_SHA256 = "8ebaf51d81601dc228db8fdf6906b9b299e65277edcfd5c1082788a5782459df"
APPROVED_COMPONENTS = {"base": "3.1.2", "paddlevl": "3.1.2", "cuda": "3.0.5"}
APPROVAL_QUESTION = "是否确认已审查当前程序和修订文案，并同意本次公开发布？"
APPROVAL_ANSWER = "同意三组件发布"
MANUAL = {"full_desktop_capture", "manual_hdr_acceptance", "mixed_monitor_hdr_sdr"}
GPU_RECEIPT = "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/gpu-e2e-evidence.json"
REGRESSIONS = {
    "tests/test_ui_unlock.py", "tests/test_ui_unlock_qml.py", "tests/test_backend_apply_qml.py",
    "tests/test_model_settings_center.py", "tests/test_ui_unlock_source_audit.py",
    "tests/test_base_audit_boundary.py", "tests/test_plugin_contract.py", "tests/test_structured_http.py",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def runtime_records(staging, kind, api):
    records = api["_files"](staging)
    return {name: checksum for name, checksum in records.items()
            if name.split("/", 1)[0] not in {"LICENSES", "source"} and name not in api["METADATA_NAMES"]
            and not (kind == "gpu" and name == GPU_RECEIPT)}


def verified_receipt(current):
    if not isinstance(current, dict):
        return False
    kind = current.get("artifact_kind")
    return (kind in VERSIONS and current.get("validation_scope") == SCOPE
            and current.get("release_version") == VERSIONS[kind]
            and current.get("status") == "ACCEPTED_WITH_LIMITATIONS" and current.get("verified") is True
            and current.get("publication_authorized") is True
            and current.get("runtime_binding") == RUNTIME_BINDINGS[kind]
            and current.get("authorization_sha256") == AUTHORIZATION_SHA256
            and current.get("approved_components") == APPROVED_COMPONENTS
            and current.get("manual_checks") == {name: "NOT_RUN" for name in MANUAL}
            and type(current.get("unverified_scenarios")) is list
            and all(type(name) is str for name in current["unverified_scenarios"])
            and len(current["unverified_scenarios"]) == len(MANUAL)
            and set(current["unverified_scenarios"]) == MANUAL
            and current.get("hdr_capture_success") is False)


def verify(record, kind, binding, staging, authorized, api):
    require(isinstance(record, dict) and record.get("validation_scope") == SCOPE and kind in VERSIONS,
            "本次有限验收范围或组件不匹配")
    require(authorized is True and record.get("status") == "ACCEPTED_WITH_LIMITATIONS"
            and api["_same_binding"](record.get("binding"), binding), "当前审查未绑定到完整source/payload")
    identity = staging / ("UmiOCR-data/about.json" if kind == "base" else "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/umi-plugin.json")
    version = api["read_json"](identity).get("version")
    if isinstance(version, dict):
        version = ".".join(str(version.get(key, "")) for key in ("major", "minor", "patch"))
    require(version == VERSIONS[kind], "其它版本不能继承本次有限验收")
    records = runtime_records(staging, kind, api)
    runtime_binding = api["tree_binding"](records)
    require(api["_same_binding"](runtime_binding, RUNTIME_BINDINGS[kind]), "代码、原生程序、模型或依赖字节偏离已审程序")
    manual, untested = record.get("manual_checks"), record.get("unverified_scenarios")
    require(manual == {name: "NOT_RUN" for name in MANUAL} and type(untested) is list
            and all(type(name) is str for name in untested) and len(untested) == len(MANUAL)
            and set(untested) == MANUAL, "只能保留明确停止的截图/HDR/混屏NOT_RUN，不得伪造PASS")
    acceptance = record.get("user_acceptance")
    require(isinstance(acceptance, dict) and acceptance.get("program_review_approved") is True
            and acceptance.get("release_notes_approved") is True and acceptance.get("capture_tests_cancelled") is True
            and acceptance.get("hdr_capture_success") is False
            and acceptance.get("published_components") == APPROVED_COMPONENTS
            and api["_same_binding"](acceptance.get("binding"), binding), "当次程序/文案/范围/限制批准缺失或不精确")
    auth_path, public_auth = api["evidence_file"](acceptance.get("authorization"))
    require(public_auth["sha256"] == AUTHORIZATION_SHA256, "不是本次原始人类发布问答记录")
    authorization = api["read_json"](auth_path)
    require(authorization.get("confirmationQuestion") == APPROVAL_QUESTION
            and authorization.get("selectedAnswer") == APPROVAL_ANSWER
            and authorization.get("approvedComponents") == APPROVED_COMPONENTS
            and authorization.get("mandatoryFormalGatesMayBeSkipped") is False
            and authorization.get("furtherDesktopCaptureTestsAllowed") is False, "原始发布问答或约束不符")
    notes_path, public_notes = api["evidence_file"](acceptance.get("release_notes"))
    notes = notes_path.read_text("utf-8-sig")
    require(all(word in notes for word in ("3.1.2", "3.0.5", "NOT_RUN"))
            and not any(word in notes.lower() for word in ("uiunlock", "ui unlock", "解锁 dll", "解锁dll")),
            "当次对外文案缺少组件版本/限制或泄露非公开启用说明")
    automated = record.get("automated_evidence")
    required = {"regressions", "gui_cases", "tray", "document_http"} if kind == "base" else {"gpu_workflows", "gpu_workflow_log", "tray"}
    require(isinstance(automated, dict) and set(automated) == required, "本次真实定向自动证据不完整或包含未知项")
    public = {}
    metadata = api["artifact_metadata_root"](staging, kind)
    validated_roots = set()

    def load(reference):
        path, receipt = api["evidence_file"](reference)
        return api["read_json"](path), receipt

    def verify_root(root_value, expected_records=None):
        require(isinstance(root_value, str) and Path(root_value).is_absolute(), "运行证据没有实际包根")
        root = Path(root_value)
        selected = records if expected_records is None else expected_records
        key = (root, api["tree_binding"](selected)["sha256"])
        if key not in validated_roots:
            api["no_links"](root)
            for name, checksum in selected.items():
                path = root / name
                api["no_links"](path)
                require(path.is_file() and api["digest"](path) == checksum, "实际运行证据指向不同的程序或依赖：" + name)
            validated_roots.add(key)

    tray, public["tray"] = load(automated["tray"])
    require(tray.get("status") == "PASS" and type(tray.get("exit_code")) is int and tray["exit_code"] == 0
            and tray.get("http_ready_before_quit") is True and tray.get("cli_forwarded") is True
            and type(tray.get("shell_icons")) is list and bool(tray["shell_icons"]),
            "实际EXE、Shell托盘、退出前HTTP或第二实例CLI未通过")
    require(tray.get("exe_sha256") == api["digest"](Path(tray.get("root", "")) / "Umi-OCR.exe"), "实际EXE摘要不匹配")
    verify_root(tray.get("root"))
    native_sources = {name: api["digest"](metadata / "source" / name)
                      for name in ("tests/test_release312_native.py", "tests/test_windows_tray.py")}
    require(tray.get("test_sources") == native_sources, "真实EXE/托盘驱动不匹配本次对应源码")
    if kind == "base":
        regressions, public["regressions"] = load(automated["regressions"])
        require(regressions.get("status") == "PASS" and isinstance(regressions.get("tests"), dict)
                and set(regressions["tests"]) == REGRESSIONS, "相关定向测试集合不完整")
        checked = {}
        for name, reference in regressions["tests"].items():
            run, checked[name] = load(reference)
            expected = api["digest"](metadata / "source" / name)
            require(run.get("status") == "PASS" and type(run.get("returncode")) is int and run["returncode"] == 0
                    and isinstance(run.get("scriptHashes"), dict)
                    and any(Path(path).name == Path(name).name and checksum == expected for path, checksum in run["scriptHashes"].items()),
                    "定向回归未通过或测试源码与canonical不匹配：" + name)
            api["evidence_file"]({"path": run.get("log"), "sha256": run.get("logSha256")})
        public["regression_cases"] = checked
        gui, public["gui_cases"] = load(automated["gui_cases"])
        require(gui.get("status") == "PASS" and isinstance(gui.get("cases"), dict)
                and set(gui["cases"]) == {"unlocked", "missing", "untrusted-content"}, "真实三态GUI证据缺失")
        cases = {}
        for reason, reference in gui["cases"].items():
            case, cases[reason] = load(reference)
            expected = reason == "unlocked"
            require(case.get("status") == "PASS" and case.get("expect") == reason
                    and case.get("verdict", {}).get("reason") == reason
                    and case.get("verdict", {}).get("enabled") is expected
                    and case.get("pageRegistered") is expected and case.get("pageOpened") is expected
                    and case.get("httpConfigurationRetained") is True and case.get("layoutModelConfigurationVisible") is True
                    and case.get("modelsUnchanged") is True and case.get("startupErrors") == [], "实际GUI门控/配置/模型保持检查失败")
            require(case.get("documentBackend") == "win32_PaddleOCRVL_1_6"
                    and case.get("ocrBackend") == "win32_PaddleOCRv6_CUDA", "UI门控不应删除推理后端")
            verify_root(case.get("root"))
        public["gui_case_records"] = cases
        document, public["document_http"] = load(automated["document_http"])
        require(document.get("status") == "PASS" and document.get("realSocket") is True and document.get("realModels") is True
                and document.get("fakeModelResponses") is False and document.get("passed") is True
                and document.get("plugins", {}).get("uiFeatures", {}).get("documentUi") is False
                and document["plugins"]["uiFeatures"].get("unlockState") == "missing", "不是实际无启用组件状态的真实HTTP/GPU文档验收")
        require(type(document.get("cases")) is list and [case.get("name") for case in document["cases"]] == ["selected-page", "full-document"], "缺少PDF选页/整篇结果")
        for case in document["cases"]:
            require(case.get("sourcePageIdentifiers") == "22/22" and case.get("sameTxtBytes") is True
                    and case.get("allPageCoordinatesBounded") is True
                    and case.get("execution", {}).get("device") in {"GPU", "GPU+CPU"}, "真实文档结果、导出或GPU证据不符")
        verify_root(document.get("root"))
    else:
        host_path, host_receipt = api["evidence_file"](acceptance.get("reviewed_host_record"))
        require(host_receipt["sha256"] == HOST_PRODUCT_RECORD_SHA256, "CUDA的实际宿主不是本次已审宿主记录")
        host_record = api["read_json"](host_path)
        host_runtime = {name: checksum for name, checksum in host_record.get("payload", {}).items()
                        if name.split("/", 1)[0] not in {"LICENSES", "source"} and name not in api["METADATA_NAMES"]}
        require(api["_same_binding"](api["tree_binding"](host_runtime), RUNTIME_BINDINGS["base"]), "CUDA宿主执行绑定不符")
        verify_root(tray.get("root"), host_runtime)
        public["reviewed_host_record"] = host_receipt
        path, public["gpu_workflows"] = api["evidence_file"](automated["gpu_workflows"])
        log, public["gpu_workflow_log"] = api["evidence_file"](automated["gpu_workflow_log"])
        api["_gpu_record"](path, staging, metadata, automated)
        require("OCR workflow tests passed:" in log.read_text("utf-8-sig"), "实际GPU工作流日志缺少成功结果")
    result = {"status": "ACCEPTED_WITH_LIMITATIONS", "verified": True, "publication_authorized": True,
        "validation_scope": SCOPE, "artifact_kind": kind, "release_version": version, "binding": binding,
        "runtime_binding": runtime_binding, "authorization_sha256": public_auth["sha256"],
        "approved_components": APPROVED_COMPONENTS.copy(), "manual_checks": manual,
        "unverified_scenarios": untested, "hdr_capture_success": False,
        "automated_evidence": public, "user_acceptance": {"source": "Current program and revised-notes review",
            "question": APPROVAL_QUESTION, "answer": APPROVAL_ANSWER, "authorization": public_auth,
            "release_notes": public_notes, "binding": binding}, "blockers": []}
    require(verified_receipt(result), "有限验收派生结果不满足自身约束")
    return result
