"""文档探测私有入口：只能由可信 bootstrap 在隔离的便携 Python 中执行。"""

import json
import os
import sys


_MAX_REQUEST_BYTES = 2 * 1024 * 1024
_MAX_DOCUMENTS = 16


def _failure(message, kind="unreadable"):
    return {
        "page_count": 0,
        "is_encrypted": False,
        "is_authenticate": False,
        "error": message[:1024],
        "error_kind": kind,
    }


def _probe(fitz, request, password):
    try:
        path = request["absolute_path"]
        if not isinstance(path, str) or not os.path.isabs(path):
            raise ValueError("只接受绝对文档路径")
        with fitz.open(path) as doc:
            encrypted = bool(doc.needs_pass)
            authenticated = not encrypted or bool(doc.authenticate(password))
            return {
                "page_count": doc.page_count,
                "is_encrypted": encrypted,
                "is_authenticate": authenticated,
            }
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        if password:
            message = message.replace(password, "[已隐藏]")
        return _failure(message)


def main():
    # 保留独立的协议输出描述符，再屏蔽 Python/原生解析器的 stdout 诊断。
    # 即使坏文档让 MuPDF 大量输出，也不会污染 JSON 或无界积累诊断日志。
    with os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", newline="\n") as output:
        with open(os.devnull, "w", encoding="utf-8") as silence:
            os.dup2(silence.fileno(), sys.stdout.fileno())
        raw = sys.stdin.buffer.read(_MAX_REQUEST_BYTES + 1)
        if len(raw) > _MAX_REQUEST_BYTES:
            raise ValueError("文档读取请求过大")
        payload = json.loads(raw)
        requests = payload["documents"]
        password = payload["password"]
        if not isinstance(requests, list) or not 0 < len(requests) <= _MAX_DOCUMENTS or not isinstance(password, str):
            raise ValueError("文档读取请求无效")
        try:
            # 只有此隔离进程导入 fitz；不导入主应用、Qt 或任何推理后端。
            import fitz

            fitz.TOOLS.mupdf_display_errors(False)
            fitz.TOOLS.mupdf_display_warnings(False)
            component_error = ""
        except Exception as exc:
            component_error = f"文档读取组件不可用（{type(exc).__name__}）。"
        for index, request in enumerate(requests):
            info = _failure(component_error, "workererror") if component_error else _probe(fitz, request, password)
            output.write(json.dumps({"index": index, "info": info}, ensure_ascii=False) + "\n")
            output.flush()


if __name__ == "__main__":
    main()
