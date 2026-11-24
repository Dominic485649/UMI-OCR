from ..utils.runtime_i18n import tr
import json

from bottle import request
from ..mission.mission_ocr import MissionOCR
from ..utils.utils import initConfigDict
from ..ocr.output.tools import getDataText
from .http_utils import is_valid_base64
from .backend_router import backend_options, select_backend, available_backends
from .request_validation import validate_options, validate_visual_budget


# 仅为旧 HTTP 客户端保留，不再进入 GUI 配置或作为第二套模型默认。
_LEGACY_PRESETS = {
    "speed": {"docOrientation": False, "undistort": "off", "textlineOrientation": "off",
              "longSide": 1600, "recBatchSize": 16, "scoreThreshold": 0.60},
    "balanced": {"docOrientation": True, "undistort": "auto", "textlineOrientation": "on",
                 "longSide": 2560, "recBatchSize": 12, "scoreThreshold": 0.50},
    "accuracy": {"docOrientation": True, "undistort": "auto", "textlineOrientation": "on",
                 "longSide": 4000, "recBatchSize": 6, "scoreThreshold": 0.45},
}


def get_ocr_options(is_format=True, backend_id="current", local_options=None):
    source = backend_options("ocr", backend_id) if local_options is None else local_options
    opts = {f"ocr.{key}": value for key, value in source.items()}
    opts["tbpu.parser"] = {
        "title": tr('排版解析方案'), "toolTip": tr('解析和排序图片中的文字块'), "default": "multi_para",
        "optionsList": [["multi_para", tr('多栏-按自然段换行')], ["multi_line", tr('多栏-总是换行')],
                        ["multi_none", tr('多栏-无换行')], ["single_para", tr('单栏-按自然段换行')],
                        ["single_line", tr('单栏-总是换行')], ["single_none", tr('单栏-无换行')],
                        ["single_code", tr('单栏-保留缩进')], ["none", tr('不做处理')]],
    }
    opts["tbpu.ignoreArea"] = {"title": tr('忽略区域'), "default": [], "type": "var",
                               "toolTip": tr('每项为 [[x1,y1],[x2,y2]]。')}
    if is_format:
        opts["data.format"] = {"title": tr('数据返回格式'), "default": "dict",
                               "optionsList": [["dict", tr('原始字典')], ["text", tr('纯文本')]]}
    return initConfigDict(opts)


def check_ocr_options(opts):
    import math
    areas = opts.get("tbpu.ignoreArea", [])
    if len(areas) > 256:
        raise ValueError(tr('忽略区域不能超过 256 项。'))
    result = []
    for area in areas:
        if (not isinstance(area, list) or len(area) != 2
                or any(not isinstance(point, list) or len(point) != 2 for point in area)
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(value) for point in area for value in point)):
            raise ValueError(tr('tbpu.ignoreArea 每项必须为有限数值的 [[x1,y1],[x2,y2]]。'))
        result.append([area[0], [], area[1], []])
    opts["tbpu.ignoreArea"] = result
    return opts


def _apply_preset_options(opts, definitions):
    # 支持旧 schema 测试及旧插件；新 PP-OCR 界面不再声明 preset。
    found = False
    for preset_key, definition in definitions.items():
        preset_values = definition.get("presetValues")
        if not preset_values:
            continue
        found = True
        prefix = preset_key.rsplit(".", 1)[0] + "."
        values = preset_values.get(opts.get(preset_key), {})
        if values:
            opts.update({prefix + key: value for key, value in values.items()})
        elif preset_key not in opts:
            managed = {prefix + key for values in preset_values.values() for key in values}
            if any(key in opts for key in managed):
                opts[preset_key] = "custom"
    if not found and "ocr.preset" in opts:
        preset = opts.pop("ocr.preset")
        if preset not in {*_LEGACY_PRESETS, "custom"}:
            raise ValueError(tr('未知历史识别预设。'))
        for key, value in _LEGACY_PRESETS.get(preset, {}).items():
            if "ocr." + key in definitions:
                opts["ocr." + key] = value
    return opts


def init(UmiWeb):
    @UmiWeb.route("/api/backends")
    def _backends():
        return {"code": 100, "data": {kind: available_backends(kind) for kind in ("ocr", "document")}}

    @UmiWeb.route("/api/ocr/get_options")
    def _get_options_json():
        try:
            return json.dumps(get_ocr_options(backend_id=request.query.get("backendId", "current")), ensure_ascii=False)
        except ValueError as exc:
            return json.dumps({"code": 804, "data": str(exc)}, ensure_ascii=False)

    @UmiWeb.route("/api/ocr", method="POST")
    def _ocr():
        try:
            data = request.json
        except Exception as exc:
            return json.dumps({"code": 800, "data": tr('请求无法解析为 JSON：{error}', error=exc)})
        if not data:
            return json.dumps({"code": 801, "data": tr('请求为空。')})
        if not isinstance(data, dict):
            return json.dumps({"code": 805, "data": tr('请求必须为 JSON 对象。')})
        if "base64" not in data:
            return json.dumps({"code": 802, "data": tr('请求中缺少 base64 字段。')})
        if not is_valid_base64(data["base64"]):
            return json.dumps({"code": 805, "data": tr('base64 字段必须为有效的 Base64 字符串。')})
        if not isinstance(data.get("options", {}), dict):
            return json.dumps({"code": 803, "data": tr('options 必须为字典。')})
        selected = None
        try:
            backend_id = data.get("backendId", "current")
            selected = select_backend("ocr", backend_id)
            definitions = get_ocr_options(backend_id=selected.backend_id, local_options=selected.local_options)
            options = dict(data.get("options", {}))
            _apply_preset_options(options, definitions)
            options = validate_options(options, definitions)
            check_ocr_options(options)
            validate_visual_budget(selected.backend_id, selected.config, options.get("ocr.maxOutputTokens", 4096))
            if "taskTimeoutSeconds" in data:
                timeout = data["taskTimeoutSeconds"]
                if type(timeout) is not int or not 1 <= timeout <= 300:
                    raise ValueError(tr('taskTimeoutSeconds 必须为 1 到 300 的整数。'))
                options["ocr.taskTimeoutSeconds"] = timeout
            results = selected.manager.addMissionWait(options, {"base64": data["base64"]})
            result = results[0]["result"]
            if options["data.format"] == "text" and result["code"] == 100:
                result["data"] = getDataText(result["data"])
            return json.dumps(result, ensure_ascii=False)
        except (ValueError, TypeError) as exc:
            return json.dumps({"code": 804, "data": tr('参数无效：{error}', error=exc), "errorType": "INVALID_OPTIONS"}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"code": 806, "data": str(exc), "errorType": "BACKEND_UNAVAILABLE"}, ensure_ascii=False)
        finally:
            if selected:
                selected.close()
