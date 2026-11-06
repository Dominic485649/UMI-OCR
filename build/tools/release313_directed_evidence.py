"""3.1.3 模型下载/最简分发的定向验收；旧版批准和截图豁免不自动延用。"""
from __future__ import annotations

import itertools
from pathlib import Path
import re

SCOPE = "release-3.1.3-model-download-minimal-no-capture"
VERSIONS = {"base": "3.1.3", "gpu": "3.0.5"}
APPROVED_COMPONENTS = {"base": "3.1.3", "cuda": "3.0.5", "paddlevl": "3.1.3"}
APPROVAL_QUESTION = "是否确认已审查本次3.1.3程序和发布文案，并同意公开发布？"
APPROVAL_ANSWER = "同意本次3.1.3程序和文案发布"
MANUAL = {"full_desktop_capture", "manual_hdr_acceptance", "mixed_monitor_hdr_sdr"}
RUNTIME_AUDITS = {"runtime-archive-inputs.json", ".runtime-archive-candidate.json", "gpu-e2e-evidence.json"}
RUNTIME_BINDINGS = {
    "base": {"files": 1897, "sha256": "7211f7828d8e72b23d9fc242d14916aef67fd28eb66c1fa341723533b67a0fb2"},
    "cuda": {"files": 9593, "sha256": "dd617ab2c49523f2a1b422957e424dbb326c05eaa6026ddf898f6245712a2d12"},
    "paddlevl": {"files": 12275, "sha256": "d7a5cc53e530bd002854a657caf79bfe8dcaa34097b2c2866fc34da9fdf538fe"},
}
REVIEWED_DISTRIBUTIONS = {
    "base": "663370aeb7231980c358b461dd9ccde5a37296038232c9e6e016a5c725978d6b",
    "cuda": "f8c4299d39a3d6e61aefe152195569eb14725e32c275df8fb7fa4fbe6d5d2b20",
    "paddlevl": "01b19e62ff607dd89f0adbf0f4fc283a0927d5eb000a4863f27d490f825f300e",
}
RESOURCE_NAMES = ("PaddleOCR-VL-1.6-GGUF.gguf", "PaddleOCR-VL-1.6-GGUF-mmproj.gguf", "PP-DocLayoutV3")
CONFIG_SHA256 = "2b68367c5b312a03de5a6e1642c597c8f95165a7e40cd59c6700cf4a5042f4fd"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def component(kind):
    require(kind in VERSIONS, "定向验收组件未知")
    return "base" if kind == "base" else "cuda"


def runtime_records(staging, kind, api):
    component(kind)
    return {name: checksum for name, checksum in api["_files"](staging).items()
            if (name.startswith("UmiOCR-data/") or name == "Umi-OCR.exe")
            and Path(name).name not in RUNTIME_AUDITS}


def verified_receipt(current):
    if not isinstance(current, dict) or current.get("artifact_kind") not in VERSIONS:
        return False
    key = component(current["artifact_kind"])
    return (current.get("validation_scope") == SCOPE
            and current.get("release_version") == VERSIONS[current["artifact_kind"]]
            and current.get("status") == "ACCEPTED_WITH_LIMITATIONS"
            and current.get("verified") is True and current.get("publication_authorized") is True
            and current.get("runtime_binding") == RUNTIME_BINDINGS[key]
            and current.get("approved_components") == APPROVED_COMPONENTS
            and isinstance(current.get("authorization_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", current["authorization_sha256"]) is not None
            and current.get("manual_checks") == {name: "NOT_RUN" for name in MANUAL}
            and type(current.get("unverified_scenarios")) is list
            and all(type(name) is str for name in current["unverified_scenarios"])
            and len(current["unverified_scenarios"]) == len(MANUAL)
            and set(current["unverified_scenarios"]) == MANUAL
            and current.get("hdr_capture_success") is False
            and current.get("validation_limits") == {
                "new_full_pdf_matrix": "NOT_RUN", "large_model_weight_network_download": "NOT_RUN",
                "non_windows_x64": "NOT_RUN"})


def approval(acceptance, distribution, api):
    require(isinstance(acceptance, dict), "缺少当次程序和文案审查")
    auth_path, auth_ref = api["evidence_file"](acceptance.get("authorization"))
    notes_path, notes_ref = api["evidence_file"](acceptance.get("release_notes"))
    auth = api["read_json"](auth_path)
    require(auth.get("recordType") == "explicit-current-program-and-notes-review"
            and auth.get("confirmationQuestion") == APPROVAL_QUESTION
            and auth.get("selectedAnswer") == APPROVAL_ANSWER
            and auth.get("publicationAuthorized") is True
            and auth.get("programReviewApproved") is True and auth.get("releaseNotesApproved") is True
            and auth.get("approvedComponents") == APPROVED_COMPONENTS
            and auth.get("approvedExecutionBindings") == RUNTIME_BINDINGS
            and auth.get("releaseNotesSha256") == notes_ref["sha256"]
            and auth.get("mandatoryFormalGatesMayBeSkipped") is False
            and auth.get("furtherDesktopCaptureTestsAllowed") is False,
            "发布意图、旧版批准或未绑定文案不能替代本次明确审查同意")
    key = distribution["component"]
    key = "paddlevl" if key == "vl" else key
    approved = auth.get("approvedMinimalRuntimeBindings")
    require(isinstance(approved, dict) and set(approved) == set(APPROVED_COMPONENTS)
            and api["_same_binding"](approved[key], api["tree_binding"](distribution["runtimePayload"])),
            "实际最简载荷（含许可和源码指引）与当次已审程序不匹配")
    notes = notes_path.read_text("utf-8-sig")
    require(all(word in notes for word in ("3.1.3", "3.0.5", "NOT_RUN"))
            and not any(word in notes.lower() for word in ("uiunlock", "ui unlock", "解锁 dll", "解锁dll", "build/private")),
            "对外文案缺少版本/限制或泄露私有启用说明")
    return auth_ref, notes_ref


def verify_evidence(record, api):
    """只核对原始自动证据；调用本函数本身不产生任何公开发布许可。"""
    references = record.get("reviewed_components")
    require(isinstance(references, dict) and set(references) == set(REVIEWED_DISTRIBUTIONS), "缺少三组件已审原件")
    reviewed, public = {}, {}
    for name, expected in REVIEWED_DISTRIBUTIONS.items():
        path, receipt = api["evidence_file"](references[name])
        require(receipt["sha256"] == expected, "不是本次已执行验收的原始分包绑定")
        item = api["read_json"](path)
        require(api["_same_binding"](api["tree_binding"](item["unchangedRuntime"]), RUNTIME_BINDINGS[name]), "已审组件执行绑定不匹配")
        reviewed[name] = item
        public["reviewed_" + name] = receipt
    roots = set()

    def verify_root(value):
        require(isinstance(value, str) and Path(value).is_absolute(), "实际运行证据没有绝对包根")
        root = Path(value)
        if root not in roots:
            api["no_links"](root)
            for item in reviewed.values():
                for name, checksum in item["unchangedRuntime"].items():
                    path = root / name
                    api["no_links"](path)
                    require(path.is_file() and api["digest"](path) == checksum, "实际运行目录与三组件已审字节不同：" + name)
            roots.add(root)
        return root

    evidence = record.get("automated_evidence")
    require(isinstance(evidence, dict) and set(evidence) == {"gui", "gui_driver", "tray", "inference", "inference_supervisor", "real_https", "recorded_runs"},
            "本次模型下载/实际GUI/托盘/代表性推理证据不完整")

    def load(name):
        path, receipt = api["evidence_file"](evidence[name])
        public[name] = receipt
        return api["read_json"](path)

    gui, tray, inference = load("gui"), load("tray"), load("inference")
    root = verify_root(gui.get("root"))
    require(verify_root(tray.get("root")) == root, "真实GUI和托盘不是同一组合")
    state = gui.get("state", {})
    cases = state.get("cases", [])
    matrix = set(itertools.product(("Default Light", "Neutral Dark"), ("zh_CN", "en_US", "ja_JP"), (1, 1.5)))
    require(gui.get("status") == "PASS" and state.get("passed") is True and state.get("settingsRestored") is True
            and state.get("startupErrors") == [] and len(cases) == 12
            and {(case.get("theme"), case.get("language"), case.get("scale")) for case in cases} == matrix,
            "实际Main.qml主题/语言/缩放矩阵没有通过")
    for case in cases:
        buttons = case.get("buttons", [])
        require(len(buttons) == 3 and all(button.get("visible") is True and button.get("text")
                and button["downloadWidth"] > 0 and button["downloadX"] + button["downloadWidth"] <= button["pickerX"]
                for button in buttons), "下载按钮缺失或未位于文件选择左侧")
    dialogs = state.get("dialogs", [])
    require(len(dialogs) == 3 and all(item.get("confirmationCancelled") is True for item in dialogs)
            and [Path(item.get("target", "")) for item in dialogs] == [root / "UmiOCR-data/plugins/win32_PaddleOCRVL_1_6/model" / name for name in RESOURCE_NAMES]
            and gui.get("weightsDownloaded") is False and gui.get("desktopCapture") == "NOT_RUN", "模型目标/取消或下载验收范围不符")
    driver, public["gui_driver"] = api["evidence_file"](evidence["gui_driver"])
    require(gui.get("driverSha256") == api["digest"](driver), "真实GUI驱动已变化")
    require(tray.get("status") == "PASS" and type(tray.get("exit_code")) is int and tray["exit_code"] == 0
            and tray.get("http_ready_before_quit") is True and tray.get("cli_forwarded") is True
            and tray.get("shell_icons") and tray.get("ownedTestSettingsRestored") is True
            and tray.get("exe_sha256") == api["digest"](root / "Umi-OCR.exe"), "实际EXE/托盘/CLI/正常退出未通过")
    host_source = Path(reviewed["base"]["metadataRoot"]) / "source"
    require(tray.get("test_sources") == {name: api["digest"](host_source / name)
            for name in ("tests/test_release312_native.py", "tests/test_windows_tray.py")}, "托盘/原生驱动偏离原始对应源码")
    supervisor = load("inference_supervisor")
    require(type(supervisor.get("exitCode")) is int and supervisor["exitCode"] == 0 and supervisor.get("timedOut") is False,
            "真实推理进程退出或期限失败")
    require(inference.get("accepted") is True and inference.get("realSocket") is True and inference.get("realPackage") is True
            and inference.get("modelInputHashesUnchanged") is True and inference.get("cleanupError") is None
            and inference.get("observations", {}).get("peakHeavyExecutions") == 1, "真实HTTP/GPU或模型只读边界未通过")
    loaded = inference.get("modulesAfterInference", {}).get("py_src", [])
    require(loaded == [str(root / "UmiOCR-data/app.zip/py_src")], "推理没有使用已审包内宿主代码")
    scenarios = inference.get("scenarios", {})
    for name, backend in (("cudaOcr", "win32_PaddleOCRv6_CUDA"), ("paddleVlOcr", "win32_PaddleOCRVL_1_6")):
        case = scenarios.get(name, {})
        require(case.get("code") == 100 and case.get("partial") is False
                and case.get("execution", {}).get("pluginId") == backend
                and str(case.get("execution", {}).get("device", "")).startswith("GPU")
                and case.get("counts", {}).get("expectedRows") == 3 and case["counts"].get("recognizedTokens", 0) >= 3,
                "真实代表性GPU OCR没有通过")
    document = scenarios.get("document", {})
    require(document.get("state") == "succeeded" and document.get("layoutDetection") is True
            and document.get("execution", {}).get("device") == "GPU" and document.get("txtBytes", 0) > 0
            and scenarios.get("limits") == {"newPdfCreated": False, "desktopCapture": "NOT_RUN", "fullFormatMatrix": "NOT_RUN",
                                           "liveModelWeightDownload": "NOT_RUN", "modelPrecisionChanged": False},
            "真实版面文档链/TXT或未执行范围不符，不能冒称本次PDF全矩阵通过")
    https = load("real_https")
    require(https.get("status") == "PASS" and https.get("sha256") == CONFIG_SHA256 and https.get("actualBytes") == 1196890
            and https.get("packagedHostCodeHash") == reviewed["base"]["unchangedRuntime"].get("UmiOCR-data/app.zip")
            and https.get("modelWeightsDownloaded") is False, "真实TLS小配置传输不匹配实际宿主或越过大权重边界")
    runs = evidence["recorded_runs"]
    require(isinstance(runs, dict) and {"downloads", "minimal_layout", "qml_settings", "plugin_contract", "runtime_policy"} <= set(runs), "受影响回归或运行原始日志缺失")
    public["recorded_runs"] = {}
    for name, reference in runs.items():
        path, receipt = api["evidence_file"](reference)
        run = api["read_json"](path)
        require(type(run.get("exitCode")) is int and run["exitCode"] == 0 and run.get("timedOut") is False, "定向运行失败或超时：" + name)
        api["evidence_file"]({"path": run.get("log"), "sha256": run.get("logSha256")})
        public["recorded_runs"][name] = receipt
    return public


def verify(record, kind, binding, staging, authorized, api):
    key = component(kind)
    require(isinstance(record, dict) and record.get("validation_scope") == SCOPE
            and record.get("status") == "ACCEPTED_WITH_LIMITATIONS" and authorized is True
            and api["_same_binding"](record.get("binding"), binding), "定向范围、当次授权或完整source/payload绑定缺失")
    identity = staging / ("UmiOCR-data/about.json" if key == "base" else "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/umi-plugin.json")
    version = api["read_json"](identity).get("version")
    if isinstance(version, dict):
        version = ".".join(str(version.get(name, "")) for name in ("major", "minor", "patch"))
    require(version == VERSIONS[kind], "其它版本不能继承3.1.3定向验收")
    runtime = api["tree_binding"](runtime_records(staging, kind, api))
    require(api["_same_binding"](runtime, RUNTIME_BINDINGS[key]), "执行代码、原生程序、模型或依赖字节已变化")
    require(record.get("manual_checks") == {name: "NOT_RUN" for name in MANUAL}
            and type(record.get("unverified_scenarios")) is list
            and all(type(name) is str for name in record["unverified_scenarios"])
            and len(record["unverified_scenarios"]) == len(MANUAL)
            and set(record["unverified_scenarios"]) == MANUAL, "必须保留真实截图/HDR/混屏NOT_RUN")
    distribution_path, distribution_ref = api["evidence_file"](record.get("minimal_distribution"))
    distribution = api["read_json"](distribution_path)
    require(distribution.get("format") == "umi-minimal-distribution-v1" and distribution.get("status") == "PASS"
            and distribution.get("component") == key and distribution.get("version") == version
            and Path(distribution.get("completeRoot", "")) == staging
            and bool(distribution.get("sourceUrl"))
            and api["_same_binding"](api["tree_binding"](distribution["unchangedRuntime"]), runtime),
            "定向验收未绑定实际最简包及其完整外置来源")
    auth_ref, notes_ref = approval(record.get("user_acceptance"), distribution, api)
    public = verify_evidence(record, api)
    public["minimal_distribution"] = distribution_ref
    result = {"status": "ACCEPTED_WITH_LIMITATIONS", "verified": True, "publication_authorized": True,
              "validation_scope": SCOPE, "artifact_kind": kind, "release_version": version, "binding": binding,
              "runtime_binding": runtime, "authorization_sha256": auth_ref["sha256"], "approved_components": APPROVED_COMPONENTS.copy(),
              "manual_checks": record["manual_checks"], "unverified_scenarios": record["unverified_scenarios"], "hdr_capture_success": False,
              "validation_limits": {"new_full_pdf_matrix": "NOT_RUN", "large_model_weight_network_download": "NOT_RUN", "non_windows_x64": "NOT_RUN"},
              "minimal_distribution": distribution_ref, "automated_evidence": public,
              "user_acceptance": {"authorization": auth_ref, "release_notes": notes_ref, "question": APPROVAL_QUESTION, "answer": APPROVAL_ANSWER},
              "evidence_reuse": "原始3.1.3重装组合的GUI/EXE/PNG代表性HTTP-GPU记录；逐字节核对三组件执行闭包，本轮只变更外置来源/许可与源码指引。",
              "blockers": []}
    require(verified_receipt(result), "3.1.3定向结果未满足自身约束")
    return result
