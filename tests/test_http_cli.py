import argparse
import base64
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _request(opener, url, payload=None, timeout=300):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _exercise_document_and_qrcode(opener, base_url, image_bytes):
    import fitz

    qr = _request(opener, base_url + "/api/qrcode", {"text": "Umi-OCR v3 HTTP QR"})
    assert qr["code"] == 100 and qr["data"], qr
    decoded = _request(opener, base_url + "/api/qrcode", {"base64": qr["data"]})
    assert decoded["code"] == 100, decoded
    assert any(item["text"] == "Umi-OCR v3 HTTP QR" for item in decoded["data"]), decoded
    doc_options = _request(opener, base_url + "/api/doc/get_options")
    assert "doc.extractionMode" in doc_options, doc_options
    with fitz.open() as document:
        for _ in range(2):
            page = document.new_page(width=720, height=240)
            page.insert_image(page.rect, stream=image_bytes)
        pdf_bytes = document.tobytes()
    boundary = "umi-release-document-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="http-document.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode("ascii") + pdf_bytes + (
        f"\r\n--{boundary}\r\n"
        'Content-Disposition: form-data; name="json"\r\n\r\n'
        '{"doc.extractionMode":"fullPage","tbpu.parser":"none"}\r\n'
        f"--{boundary}--\r\n"
    ).encode("ascii")
    request = urllib.request.Request(
        base_url + "/api/doc/upload", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with opener.open(request, timeout=60) as response:
        uploaded = json.loads(response.read().decode("utf-8"))
    assert uploaded["code"] == 100 and isinstance(uploaded["data"], str), uploaded
    mission_id = uploaded["data"]
    try:
        deadline = time.monotonic() + 300
        while True:
            result = _request(opener, base_url + "/api/doc/result", {
                "id": mission_id, "is_data": True, "is_unread": False,
            })
            assert result["code"] == 100, result
            if result["is_done"]:
                break
            assert time.monotonic() < deadline, "HTTP document task timed out"
            time.sleep(0.1)
        assert result["state"] == "success", result
        assert result["pages_count"] == result["processed_count"] == 2, result
        assert len(result["data"]) == 2 and all(item["code"] == 100 for item in result["data"]), result
        generated = _request(opener, base_url + "/api/doc/download", {
            "id": mission_id, "file_types": ["pdfLayered"], "ignore_blank": False,
        })
        assert generated["code"] == 100, generated
        download_url = urllib.parse.quote(generated["data"], safe=":/")
        with opener.open(download_url, timeout=60) as response:
            searchable = response.read()
        assert searchable.startswith(b"%PDF"), "HTTP download was not a PDF"
        with fitz.open(stream=searchable, filetype="pdf") as document:
            assert document.page_count == 2
            assert all(page.get_text().strip() for page in document)
    finally:
        cleared = _request(opener, base_url + "/api/doc/clear/" + mission_id)
        assert cleared["code"] == 100, cleared
    missing = _request(opener, base_url + "/api/doc/result", {"id": mission_id})
    assert missing["code"] == 103, "cleared HTTP document task is still visible"


def _argv(opener, base_url, arguments, timeout=60):
    request = urllib.request.Request(
        base_url + "/argv",
        data=json.dumps(arguments).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"argv HTTP {exc.code}: {body}") from exc


def _wait_qml_values(opener, base_url, expected, timeout=10):
    deadline = time.monotonic() + timeout
    values = {}
    last_error = None
    while True:
        try:
            values = json.loads(
                _argv(
                    opener,
                    base_url,
                    [
                        "--call_qml",
                        "ScreenshotOCR",
                        "--func",
                        "getValueDict",
                        "--thread",
                    ],
                    timeout=2,
                )
            )
            last_error = None
            if all(values.get(key) == value for key, value in expected.items()):
                return values
        except (OSError, RuntimeError, ValueError) as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"QML settings did not reach {expected}: {values}; last error: {last_error}"
            )
        time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("staging_root", type=Path)
    args = parser.parse_args()
    staging_root = args.staging_root.resolve()
    data_root = staging_root / "UmiOCR-data"
    executable = staging_root / "Umi-OCR.exe"
    assert executable.is_file()
    handles = configure_runtime(data_root)

    from PIL import Image, ImageDraw, ImageFont
    from PySide6.QtCore import QSettings
    from py_src.server.ocr_server import _apply_preset_options

    preset_definitions = {
        "ocr.preset": {
            "presetValues": {
                "speed": {"longSide": 1600, "scoreThreshold": 0.6},
                "accuracy": {"longSide": 4000, "scoreThreshold": 0.45},
            }
        }
    }
    selected = _apply_preset_options(
        {"ocr.preset": "speed", "ocr.longSide": 3000}, preset_definitions
    )
    assert selected["ocr.longSide"] == 1600
    custom = _apply_preset_options({"ocr.longSide": 3000}, preset_definitions)
    assert custom["ocr.preset"] == "custom"

    settings_path = data_root / ".settings"
    pre_settings_path = data_root / ".pre_settings"
    settings_backup = settings_path.read_bytes() if settings_path.exists() else None
    pre_settings_backup = pre_settings_path.read_bytes() if pre_settings_path.exists() else None
    port = _free_port()
    process = None

    try:
        settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
        settings.setFallbacksEnabled(False)
        settings.clear()
        settings.setValue("Global/window.startupInvisible", True)
        settings.setValue("Global/server.enable", True)
        settings.setValue("Global/server.host", "127.0.0.1")
        settings.setValue("Global/server.port", port)
        settings.setValue("Global/ocr.api", "win32_PaddleOCRv6_CUDA")
        settings.setValue("Global/ocr.win32_PaddleOCRv6_CUDA.device", "gpu:0")
        settings.sync()
        del settings
        pre_settings_path.write_text(
            json.dumps(
                {
                    "i18n": "",
                    "opengl": "d3d11",
                    "server_port": port,
                    "last_pid": -1,
                    "last_ptime": -1,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            temp_dir = Path(temp_dir)
            font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
            font_path = next(
                (
                    path
                    for path in (font_dir / "msyh.ttc", font_dir / "arial.ttf")
                    if path.is_file()
                ),
                None,
            )
            font = (
                ImageFont.truetype(str(font_path), 72)
                if font_path
                else ImageFont.load_default()
            )
            image = Image.new("RGB", (1000, 260), "white")
            ImageDraw.Draw(image).text(
                (40, 75), "Umi OCR HTTP CLI CUDA", font=font, fill="black"
            )
            stream = io.BytesIO()
            image.save(stream, "PNG")
            image_bytes = stream.getvalue()
            image_path = temp_dir / "http-cli.png"
            image_path.write_bytes(image_bytes)
            cli_output = temp_dir / "cli-result.txt"
            log_path = temp_dir / "app.log"

            environment = os.environ.copy()
            environment["PADDLE_PDX_DISABLE_DEVICE_FALLBACK"] = "True"
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    [str(executable), "--force"],
                    cwd=staging_root,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )

                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                base_url = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 90
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"Umi-OCR exited during startup ({process.returncode}).\n"
                            + log_path.read_text("utf-8", errors="replace")
                        )
                    try:
                        options = _request(opener, base_url + "/api/ocr/get_options", timeout=2)
                        break
                    except Exception:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("HTTP server startup timed out")
                        time.sleep(0.25)

                assert "ocr.language" not in options
                assert options["ocr.preset"]["default"] == "accuracy"
                assert options["ocr.detModel"]["default"] == "PP-OCRv6_medium"
                assert options["ocr.recModel"]["default"] == "PP-OCRv6_medium"

                response = _request(
                    opener,
                    base_url + "/api/ocr",
                    {
                        "base64": base64.b64encode(image_bytes).decode("ascii"),
                        "options": {"data.format": "dict", "tbpu.parser": "none"},
                    },
                )
                assert response["code"] == 100, response
                assert response["data"]
                assert all({"text", "box", "score"} <= set(item) for item in response["data"])
                _exercise_document_and_qrcode(opener, base_url, image_bytes)

                cli = subprocess.run(
                    [
                        str(executable),
                        "--path",
                        str(image_path),
                        "--output",
                        str(cli_output),
                    ],
                    cwd=staging_root,
                    env=environment,
                    timeout=300,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                assert cli.returncode == 0, cli.returncode
                deadline = time.monotonic() + 30
                while not cli_output.exists() and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert cli_output.is_file()
                cli_text = cli_output.read_text("utf-8")
                assert cli_text.strip() and "[Error]" not in cli_text

                set_custom = _argv(
                    opener,
                    base_url,
                    [
                        "--call_qml",
                        "ScreenshotOCR",
                        "--func",
                        "setValue",
                        "ocr.longSide",
                        "3000",
                    ],
                )
                assert "Calling" in set_custom
                custom = _wait_qml_values(
                    opener,
                    base_url,
                    {"ocr.longSide": 3000, "ocr.preset": "custom"},
                )

                _argv(
                    opener,
                    base_url,
                    [
                        "--call_qml",
                        "ScreenshotOCR",
                        "--func",
                        "setValue",
                        "ocr.preset",
                        "accuracy",
                    ],
                )
                accuracy = _wait_qml_values(
                    opener,
                    base_url,
                    {"ocr.preset": "accuracy", "ocr.longSide": 4000},
                )

                quit_result = subprocess.run(
                    [str(executable), "--quit"],
                    cwd=staging_root,
                    env=environment,
                    timeout=60,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                assert quit_result.returncode == 0
                process.wait(timeout=60)
                assert process.returncode == 0

            print(
                f"HTTP/CLI tests passed on port {port}: options, Base64 OCR, "
                f"QR round trip, document upload/result/searchable PDF/download/clear, "
                f"path OCR, preset/custom, output file, clean quit "
                f"({len(response['data'])} items)."
            )
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)
        if settings_backup is None:
            settings_path.unlink(missing_ok=True)
        else:
            settings_path.write_bytes(settings_backup)
        if pre_settings_backup is None:
            pre_settings_path.unlink(missing_ok=True)
        else:
            pre_settings_path.write_bytes(pre_settings_backup)
        del handles


if __name__ == "__main__":
    main()
