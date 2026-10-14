// =========================================
// =============== 图片管理器 ===============
// =========================================

import QtQuick 2.15
import ImageConnector 1.0 // 图片连接器

Item {
    // ========================= 【接口】 =========================

    // 截图，向回调函数传入裁切后的 clipImgID
    readonly property var screenshot: screenshotManager ? screenshotManager.screenshot : undefined
    // 重复截图
    readonly property var reScreenshot: screenshotManager ? screenshotManager.reScreenshot : undefined
    // 获取指定区域的截图ID
    readonly property var getScreenshot: screenshotManager ? screenshotManager.getScreenshot : undefined
    // 复制图片
    readonly property var copyImage: imageConnector ? imageConnector.copyImage : undefined
    // 用系统默认应用打开图片
    readonly property var openImage: imageConnector ? imageConnector.openImage : undefined
    // 保存图片
    readonly property var saveImage: imageConnector ? imageConnector.saveImage : undefined
    // 获取剪贴板
    readonly property var getPaste: imageConnector ? imageConnector.getPaste : undefined
    // 解码 Qt 不原生支持的图片并返回缓存 ID
    readonly property var loadImage: imageConnector ? imageConnector.loadImage : undefined

    // ===========================================================

    // 图片连接器
    property QtObject imageConnector: ImageConnector {}
    // 截图管理器
    property QtObject screenshotManager: ScreenshotManager {}
}
