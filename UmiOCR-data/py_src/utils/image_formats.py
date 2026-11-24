"""图片 OCR 与结构化文档共用的格式清单；解码仍须校验实际内容。"""

IMAGE_SUFFIXES = (
    ".jpg", ".jpe", ".jpeg", ".jfif", ".png", ".avif", ".webp", ".jxl",
    ".jxr", ".wdp", ".hdp", ".bmp", ".tif", ".tiff",
)
DOCUMENT_SUFFIXES = (".pdf", *IMAGE_SUFFIXES)


def document_name_filter():
    return "文档和图片 (" + " ".join("*" + suffix for suffix in DOCUMENT_SUFFIXES) + ")"
