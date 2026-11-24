"""HTTP 真实执行边界的 schema 校验，不依赖 GUI 控件范围。"""
from ..utils.runtime_i18n import tr
from copy import deepcopy
import math


class InvalidOptions(ValueError):
    pass


def _same_choice(value, choice):
    if isinstance(value, bool) or isinstance(choice, bool):
        return type(value) is type(choice) and value == choice
    return value == choice


def validate_options(values, definitions):
    if not isinstance(values, dict) or len(values) > 128:
        raise InvalidOptions(tr('options 必须为字典，且字段数量不能超过 128。'))
    unknown = set(values) - set(definitions)
    if unknown:
        raise InvalidOptions(tr('未知或不允许覆盖的参数：{items}', items=', '.join(sorted(unknown))))
    result = {}
    for key, definition in definitions.items():
        value = deepcopy(values.get(key, definition.get("default")))
        choices = definition.get("optionsList")
        default = definition.get("default")
        kind = definition.get("type", "")
        if choices is not None:
            if not any(_same_choice(value, item[0]) for item in choices):
                raise InvalidOptions(tr('{key} 不在允许的选项中。', key=key))
        elif kind == "boolean" or isinstance(default, bool):
            if not isinstance(value, bool):
                raise InvalidOptions(tr('{key} 必须为布尔值。', key=key))
        elif kind == "number" or (isinstance(default, (int, float)) and not isinstance(default, bool)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise InvalidOptions(tr('{key} 必须为有限数值。', key=key))
            if definition.get("isInt", isinstance(default, int)) and not isinstance(value, int):
                raise InvalidOptions(tr('{key} 必须为整数。', key=key))
            if "min" in definition and value < definition["min"]:
                raise InvalidOptions(tr('{key} 小于允许的最小值 {min}。', key=key, min=definition['min']))
            if "max" in definition and value > definition["max"]:
                raise InvalidOptions(tr('{key} 大于允许的最大值 {max}。', key=key, max=definition['max']))
        elif kind == "var" or isinstance(default, (list, dict)):
            if default is not None and not isinstance(value, type(default)):
                raise InvalidOptions(tr('{key} 的容器类型无效。', key=key))
            if isinstance(value, (list, dict)) and len(value) > 1024:
                raise InvalidOptions(tr('{key} 的条目过多。', key=key))
        elif isinstance(default, str) or kind in {"text", "file", ""}:
            if not isinstance(value, str) or len(value) > 4096:
                raise InvalidOptions(tr('{key} 必须为不超过 4096 字符的文本。', key=key))
        result[key] = value
    return result


def validate_visual_budget(backend_id, config, output_tokens):
    # 由资源契约判断是否使用多模态预算，不在本体硬编码可选插件。
    if not any(key in config for key in ("resources.contextLength", "resources.slots", "resources.maxOutputTokens")):
        return
    context = int(config.get("resources.contextLength", 16384))
    slots = int(config.get("resources.slots", 1))
    service_output = int(config.get("resources.maxOutputTokens", 4096))
    task_output = int(output_tokens)
    if task_output > service_output:
        raise InvalidOptions(tr('任务输出预算 {output} 超过服务最大输出 token {service}。请降低任务输出上限或提高服务上限。', output=task_output, service=service_output))
    # 与 VL 插件采用相同的固定视觉输入与提示词预留；不读取已退休的 imageMaxTokens。
    reserve = 2048 + 512
    if slots < 1 or context // slots < reserve + task_output:
        raise InvalidOptions(tr('视觉输入、输出和提示词超过单槽上下文预算，请增大上下文或降低输出上限。'))


def validate_page_range(value):
    if value is None:
        return None
    if (not isinstance(value, list) or len(value) != 2
            or any(type(item) is not int for item in value)
            or value[0] < 1 or value[1] < value[0] or value[1] - value[0] >= 500):
        raise InvalidOptions(tr('pageRange 必须是有效的正整数页范围，且一次不超过 500 页。'))
    return list(value)
