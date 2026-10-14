import re


_BASE64_PATTERN = re.compile(
    r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=|[A-Za-z0-9+/]{2,3})?\Z"
)


def is_valid_base64(value):
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) % 4 == 0
        and _BASE64_PATTERN.fullmatch(value) is not None
    )
