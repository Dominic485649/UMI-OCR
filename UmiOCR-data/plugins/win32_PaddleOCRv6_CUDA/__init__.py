from .config import globalOptions, localOptions


def Api(global_options):
    # Keep plugin discovery light; the CUDA implementation is imported when
    # OCR is configured, after the first UI frame can be shown.
    from .api import Api as PaddleOcrApi

    return PaddleOcrApi(global_options)


PluginInfo = {
    "group": "ocr",
    "global_options": globalOptions,
    "local_options": localOptions,
    "api_class": Api,
}
