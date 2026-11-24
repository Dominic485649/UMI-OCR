# Qt 6 RHI 渲染选项

import os
import sys

from umi_log import logger
from . import pre_configs


_RHI_BACKEND = "d3d11" if sys.platform == "win32" else "opengl"


def initOpengl():
    # Qt 6 RHI uses D3D11 on Windows and never selects the software scene graph.
    os.environ.pop("QT_QUICK_BACKEND", None)
    os.environ["QSG_RHI_BACKEND"] = _RHI_BACKEND
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

    graphics_api = (
        QSGRendererInterface.GraphicsApi.Direct3D11
        if sys.platform == "win32"
        else QSGRendererInterface.GraphicsApi.OpenGL
    )
    QQuickWindow.setGraphicsApi(graphics_api)
    setOpengl(_RHI_BACKEND)


def checkOpengl():
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

    expected = (
        QSGRendererInterface.GraphicsApi.Direct3D11
        if sys.platform == "win32"
        else QSGRendererInterface.GraphicsApi.OpenGL
    )
    if QQuickWindow.graphicsApi() != expected:
        raise RuntimeError("Qt Quick hardware renderer initialization failed.")


def setOpengl(opt):
    if opt != _RHI_BACKEND:
        raise ValueError
    pre_configs.setValue("opengl", opt)


def getOpengl():
    return _RHI_BACKEND
