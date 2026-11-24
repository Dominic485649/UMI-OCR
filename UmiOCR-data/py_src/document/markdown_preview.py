"""离线结果预览：固定壳、只读资产快照与独立匿名 WebEngine profile。"""
from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import unquote
from uuid import uuid4

from PySide6.QtCore import QBuffer, QByteArray, QFile, QIODevice, QObject, Property, QUrl, Slot
from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor, QWebEngineUrlScheme, QWebEngineUrlSchemeHandler, QWebEngineUrlRequestJob
from PySide6.QtWebEngineQuick import QQuickWebEngineProfile, QtWebEngineQuick

SCHEME = b"umi-preview"
ORIGIN = "umi-preview://reader"
SHELL = ORIGIN + "/index.html"
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_ASSET_BYTES = 16 * 1024 * 1024
MAX_ASSETS_BYTES = 128 * 1024 * 1024
MAX_ASSETS = 500
CHUNK_SIZE = 32768
STATIC = {
    "index.html": b"text/html", "render.js": b"text/javascript", "reader.css": b"text/css",
    "vendor/markdown-it.min.js": b"text/javascript", "vendor/purify.min.js": b"text/javascript",
    "vendor/katex.min.js": b"text/javascript", "vendor/auto-render.min.js": b"text/javascript",
    "vendor/highlight.min.js": b"text/javascript", "vendor/katex.min.css": b"text/css",
    "vendor/highlight-light.css": b"text/css", "vendor/highlight-dark.css": b"text/css",
}


def initialize_preview():
    """必须在 QApplication 之前调用；不关闭 Chromium 沙箱。"""
    if not QWebEngineUrlScheme.schemeByName(SCHEME).name():
        scheme = QWebEngineUrlScheme(SCHEME)
        scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
        scheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme | QWebEngineUrlScheme.Flag.CorsEnabled)
        QWebEngineUrlScheme.registerScheme(scheme)
    QtWebEngineQuick.initialize()


def _static_mime(relative):
    if relative in STATIC: return STATIC[relative]
    if re.fullmatch(r"vendor/fonts/KaTeX_[A-Za-z0-9_-]+\.woff2", relative): return b"font/woff2"
    return None


def _static_root(module_file):
    path = Path(module_file).resolve()
    for parent in path.parents:
        if parent.name.casefold() == "app.zip":
            return parent.parent / "qt_res/preview"
    return path.parents[2] / "qt_res/preview"


def _read_static(relative):
    source = _static_root(__file__) / relative
    file = QFile(":/qt_res/preview/" + relative)
    if not file.exists(): file.setFileName(str(source))
    if not file.open(QIODevice.OpenModeFlag.ReadOnly): return None
    try: return bytes(file.readAll())
    finally: file.close()


def _plain_file(path, root):
    path, root = Path(path).absolute(), Path(root).absolute()
    path.relative_to(root)
    for node in (path, *path.parents):
        if node.is_symlink() or node.is_junction(): raise ValueError("链接不允许用于结果预览")
    if path.resolve() != path or not path.is_file(): raise ValueError("无效的结果资产")
    return path


def _raster_mime(content):
    if content.startswith(b"\x89PNG\r\n\x1a\n"): return b"image/png"
    if content.startswith(b"\xff\xd8\xff"): return b"image/jpeg"
    if content[:6] in (b"GIF87a", b"GIF89a"): return b"image/gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP": return b"image/webp"
    return None  # 不向识别 HTML 开放 SVG、HTML 或任意二进制。


class _Requests(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        url = info.requestUrl()
        allowed = (url.scheme() == SCHEME.decode() and url.host() == "reader"
                   and not url.userInfo() and url.port() == -1 and not url.hasQuery())
        if not allowed: info.block(True)


class _Resources(QWebEngineUrlSchemeHandler):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.assets = {}

    def requestStarted(self, job):
        url = job.requestUrl()
        if (job.requestMethod() != b"GET" or url.host() != "reader" or url.userInfo()
                or url.port() != -1 or url.hasQuery()):
            job.fail(QWebEngineUrlRequestJob.Error.RequestDenied)
            return
        relative = url.path().lstrip("/")
        if relative in self.assets:
            mime, data = self.assets[relative]
        else:
            mime = _static_mime(relative)
            data = _read_static(relative) if mime else None
        if data is None:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        buffer = QBuffer(job)
        buffer.setData(QByteArray(data))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(QByteArray(mime), buffer)


class MarkdownPreviewConnector(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._profile = QQuickWebEngineProfile(self)
        self._profile.setOffTheRecord(True)
        self._profile.setHttpCacheType(QQuickWebEngineProfile.HttpCacheType.NoCache)
        self._requests = _Requests(self)
        self._resources = _Resources(self)
        self._profile.setUrlRequestInterceptor(self._requests)
        self._profile.installUrlSchemeHandler(SCHEME, self._resources)
        self._profile.downloadRequested.connect(lambda request: request.cancel())
        self._asset_root = Path.cwd() / "temp_doc"
        self._chunks = []
        self._revision = 0

    @Property(QObject, constant=True)
    def profile(self): return self._profile

    @Property(QUrl, constant=True)
    def shellUrl(self): return QUrl(SHELL)

    @Slot(str, "QVariant", "QVariant", result="QVariant")
    def prepare(self, markdown, records, presentation):
        if hasattr(records, "toVariant"): records = records.toVariant()
        if hasattr(presentation, "toVariant"): presentation = presentation.toVariant()
        self._revision += 1
        self._chunks = []
        self._resources.assets = {}
        if len(markdown.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            return {"error": "size", "chunks": 0}
        assets, aliases, total, denied = {}, {}, 0, 0
        records = records if isinstance(records, (list, tuple)) else []
        for record in records[:MAX_ASSETS]:
            if not isinstance(record, dict): continue
            try:
                path = _plain_file(str(record["path"]), self._asset_root)
                size = path.stat().st_size
                if size > MAX_ASSET_BYTES or total + size > MAX_ASSETS_BYTES: raise ValueError("资产超出预览预算")
                # 快照后不再按浏览器提供的路径读盘，也不受后续文件替换／junction 变化影响。
                with path.open("rb") as stream: content = stream.read(MAX_ASSET_BYTES + 1)
                mime = _raster_mime(content)
                if not mime or len(content) > MAX_ASSET_BYTES: raise ValueError("非支持的栅格图片")
                key = "assets/" + uuid4().hex
                assets[key] = (mime, content)
                total += len(content)
                references = [str(path), path.as_posix(), path.as_uri(), record.get("uri"), record.get("source")]
                references.extend(record.get("sourceReferences") or [])
                for reference in references:
                    if isinstance(reference, str) and reference:
                        aliases[reference] = ORIGIN + "/" + key
                        aliases[unquote(reference)] = ORIGIN + "/" + key
            except (OSError, TypeError, ValueError, KeyError):
                denied += 1
        self._resources.assets = assets
        self._chunks = [markdown[index:index + CHUNK_SIZE] for index in range(0, len(markdown), CHUNK_SIZE)]
        config = {"revision": self._revision, "assets": aliases, "deniedAssets": denied,
                  "presentation": presentation if isinstance(presentation, dict) else {}}
        return {"chunks": len(self._chunks), "begin": "umiPreview.begin(" + json.dumps(config, ensure_ascii=True) + ")", "error": ""}

    @Slot(int, result=str)
    def chunkScript(self, index):
        if not 0 <= index < len(self._chunks): return "false"
        return "umiPreview.append(" + json.dumps(self._chunks[index], ensure_ascii=True) + ")"
