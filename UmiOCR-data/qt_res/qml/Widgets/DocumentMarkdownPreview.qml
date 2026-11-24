import QtQuick 2.15
import QtQuick.Window 2.15
import QtWebEngine
import MarkdownPreviewConnector 1.0

Item {
    id: reader
    property string text: ""
    property var resources: []
    property string errorText: ""
    property bool ready: false
    property real previewZoom: 1.0
    property int revision: 0
    property alias browser: browserLoader.item
    property var presentation: ({
        background: String(theme.bgColor), foreground: String(theme.textColor),
        muted: String(theme.subTextColor), link: String(theme.specialTextColor || theme.textColor),
        border: String(theme.coverColor3), font: theme.dataFontFamily,
        fontSize: size_.text,
        dark: (theme.bgColor.r * 0.2126 + theme.bgColor.g * 0.7152 + theme.bgColor.b * 0.0722) < 0.5,
        empty: qsTr("解析结果将在这里渲染。可切换到 Markdown 源码查看原始内容。"),
        blocked: qsTr("部分图片未获授权或超出预览预算，已阻止加载。原始 Markdown 未改变。"),
        longBlock: qsTr("此段内容较长，按源码显示以保持预览响应。")
    })

    function resetScroll() {
        if(ready && browserLoader.item) browserLoader.item.runJavaScript("window.scrollTo(0,0)")
    }
    function refresh() { refreshTimer.restart() }
    function renderDocument() {
        if(!ready || !browserLoader.item) return
        const ticket = ++revision
        const controller = browserLoader.item.controller
        const prepared = controller.prepare(text, resources, presentation)
        errorText = prepared.error ? qsTr("文档超过 16 MiB 预览预算，请查看 Markdown 源码或导出文件。") : ""
        if(prepared.error) {
            browserLoader.item.runJavaScript("umiPreview.clear()")
            return
        }
        function append(index) {
            if(ticket !== revision || !ready || !browserLoader.item) return
            const script = index < prepared.chunks ? controller.chunkScript(index) : "umiPreview.finish()"
            browserLoader.item.runJavaScript(script, () => {
                if(index < prepared.chunks) Qt.callLater(() => append(index + 1))
            })
        }
        browserLoader.item.runJavaScript(prepared.begin, () => append(0))
    }
    onTextChanged: refresh()
    onResourcesChanged: refresh()
    onPresentationChanged: {
        if(ready && browserLoader.item)
            browserLoader.item.runJavaScript("umiPreview.theme(" + JSON.stringify(presentation) + ")")
    }
    Timer { id: refreshTimer; interval: 80; onTriggered: reader.renderDocument() }

    Row {
        id: zoomControls
        anchors.top: parent.top
        anchors.right: parent.right
        height: size_.line * 1.5
        spacing: size_.spacing / 2
        Button_ { objectName: "markdownZoomOut"; height: parent.height; text_: "−"; toolTip: qsTr("缩小"); onClicked: reader.previewZoom = Math.max(0.5, reader.previewZoom - 0.1) }
        Button_ { objectName: "markdownZoomReset"; height: parent.height; text_: Math.round(reader.previewZoom * 100) + "%"; toolTip: qsTr("重置缩放"); onClicked: reader.previewZoom = 1.0 }
        Button_ { objectName: "markdownZoomIn"; height: parent.height; text_: "+"; toolTip: qsTr("放大"); onClicked: reader.previewZoom = Math.min(3.0, reader.previewZoom + 0.1) }
    }
    WheelHandler {
        target: null
        acceptedModifiers: Qt.ControlModifier
        onWheel: event => {
            reader.previewZoom = Math.max(0.5, Math.min(3.0, reader.previewZoom + (event.angleDelta.y > 0 ? 0.1 : -0.1)))
            event.accepted = true
        }
    }
    Loader {
        id: browserLoader
        anchors.fill: parent
        anchors.topMargin: zoomControls.height + size_.spacing / 2
        // 逻辑测试、未显示页签和未入窗口的组件不创建 Chromium 页面。
        active: reader.visible && reader.Window.window !== null
        onActiveChanged: if(!active) { reader.ready = false; reader.revision++ }
        sourceComponent: WebEngineView {
            id: web
            objectName: "markdownWebView"
            property alias controller: controller
            MarkdownPreviewConnector { id: controller }
            profile: controller.profile
            url: controller.shellUrl
            backgroundColor: theme.bgColor
            zoomFactor: reader.previewZoom
            settings.localContentCanAccessFileUrls: false
            settings.localContentCanAccessRemoteUrls: false
            settings.javascriptCanOpenWindows: false
            settings.javascriptCanAccessClipboard: false
            settings.allowWindowActivationFromJavaScript: false
            settings.fullScreenSupportEnabled: false
            settings.screenCaptureEnabled: false
            settings.pdfViewerEnabled: false
            onContextMenuRequested: request => request.accepted = true
            onNewWindowRequested: request => {} // 不把新窗口请求交给外部浏览器。
            onNavigationRequested: request => {
                if(request.url.toString() === controller.shellUrl.toString()) return
                request.reject()
                const link = request.url.toString()
                if(request.navigationType === WebEngineNavigationRequest.LinkClickedNavigation && /^https?:\/\//i.test(link)) {
                    qmlapp.popup.dialog(qsTr("打开链接"), link, accepted => {
                        if(accepted) Qt.openUrlExternally(link)
                    }, "", {yesText: qsTr("打开网页")})
                }
            }
            onLoadingChanged: request => {
                if(request.status === WebEngineView.LoadSucceededStatus) {
                    reader.ready = true
                    reader.errorText = ""
                    reader.renderDocument()
                } else if(request.status === WebEngineView.LoadFailedStatus) {
                    reader.ready = false
                    reader.errorText = qsTr("离线预览加载失败，请切换到 Markdown 源码查看结果。")
                }
            }
            onRenderProcessTerminated: (status, exitCode) => {
                reader.ready = false
                reader.errorText = qsTr("预览进程已退出（%1），请切换页签重试或查看 Markdown 源码。").arg(exitCode)
            }
        }
    }
    Text_ {
        anchors.fill: parent
        anchors.margins: size_.spacing
        visible: !!reader.errorText
        text: reader.errorText
        wrapMode: Text.Wrap
        color: theme.subTextColor
    }
}
