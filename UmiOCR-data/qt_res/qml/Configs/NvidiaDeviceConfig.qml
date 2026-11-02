// 设备名称只是展示；只提交用户选中的有效 CUDA 逻辑 gpu:N。
import QtQuick 2.15
import QtQuick.Controls 2.15
import "../Widgets"

ConfigItemComp {
    id: deviceItem
    property var deviceSnapshot: qmlapp.globalConfigs.cudaDeviceSnapshot
    property var deviceOptions: []
    property string discoveryText: {
        const state = (deviceSnapshot || {}).state
        if(state === "pending") return qsTr("正在读取 NVIDIA 显卡…")
        if(state === "no_devices") return qsTr("未发现可用的 NVIDIA GPU")
        if(state === "driver_missing") return qsTr("未找到 NVIDIA 驱动")
        if(state === "timeout") return qsTr("读取显卡超时，请刷新重试")
        if(state !== "ready") return qsTr("读取显卡失败，请刷新重试")
        return ""
    }
    onDeviceSnapshotChanged: { if(itemReady) refreshValue() }
    onDiscoveryTextChanged: { if(itemReady) refreshValue() }
    onItemReadyChanged: {
        if(itemReady) {
            refreshValue()
            qmlapp.globalConfigs.refreshCudaDevices(false)
        }
    }
    updateUI: function() {
        const saved = value()
        const snapshot = deviceSnapshot || {}
        const detected = snapshot.state === "ready" ? (snapshot.devices || []) : []
        const options = detected.map(device => ({value: device.value,
            label: "GPU:" + device.ordinal + " · " + device.name, available: true}))
        let index = options.findIndex(option => option.value === saved)
        if(index < 0) {
            const label = String(saved || "").replace(/^gpu:/, "GPU:")
            options.unshift({value: saved, label: discoveryText
                ? (label ? label + " · " + discoveryText : discoveryText)
                : qsTr("已保存但当前不可用：%1").arg(label), available: false})
            index = 0
        }
        deviceOptions = options
        deviceCombo.model = options.map(option => option.label)
        deviceCombo.currentIndex = index
    }

    ComboBox {
        id: deviceCombo
        objectName: "nvidiaDeviceCombo"
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: refreshButton.left
        anchors.rightMargin: size_.smallSpacing
        anchors.margins: 1
        width: parent.width * 0.5 - refreshButton.width - size_.smallSpacing
        model: []
        onActivated: function(index) {
            const option = deviceOptions[index]
            if(option && option.available && (deviceSnapshot || {}).state === "ready") value(option.value)
        }
        Accessible.name: title
        ToolTip.visible: hovered
        ToolTip.text: currentText
        popup: Popup {
            y: deviceCombo.height + size_.smallSpacing
            width: deviceCombo.width
            implicitHeight: Math.min(contentItem.implicitHeight + padding * 2, size_.line * 12)
            padding: size_.smallSpacing
            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: deviceCombo.popup.visible ? deviceCombo.delegateModel : null
                currentIndex: deviceCombo.highlightedIndex
                ScrollIndicator.vertical: ScrollIndicator {}
            }
            background: Rectangle {
                color: theme.specialBgColor
                border.width: 1
                border.color: theme.coverColor4
                radius: size_.panelRadius
            }
        }
        contentItem: Text {
            text: deviceCombo.currentText
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.right: downIcon.left
            anchors.margins: size_.smallSpacing
            verticalAlignment: Text.AlignVCenter
            font.pixelSize: size_.text
            font.family: theme.fontFamily
            color: theme.subTextColor
            elide: Text.ElideRight
        }
        indicator: Icon_ {
            id: downIcon
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            anchors.margins: size_.smallSpacing
            height: size_.smallLine
            width: size_.smallLine
            icon: "down"
            color: theme.subTextColor
        }
        background: Rectangle {
            color: theme.bgColor
            border.width: 2
            border.color: theme.coverColor2
            radius: size_.btnRadius
            MouseAreaBackgroud { cursorShape: Qt.PointingHandCursor }
        }
        delegate: ItemDelegate {
            width: deviceCombo.width
            height: size_.line + size_.spacing
            enabled: deviceOptions[index] && deviceOptions[index].available
            Text {
                text: modelData
                anchors.fill: parent
                anchors.margins: size_.smallSpacing
                verticalAlignment: Text.AlignVCenter
                font.pixelSize: size_.text
                font.family: theme.fontFamily
                color: enabled ? theme.subTextColor : theme.coverColor4
                elide: Text.ElideRight
            }
            background: Rectangle {
                color: deviceCombo.currentIndex === index ? theme.coverColor2 : "transparent"
                radius: size_.btnRadius
            }
        }
    }
    ToolButton {
        id: refreshButton
        objectName: "nvidiaDeviceRefresh"
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        width: size_.line * 1.5
        text: "↻"
        font.pixelSize: size_.text
        Accessible.name: qsTr("刷新显卡列表")
        ToolTip.visible: hovered
        ToolTip.text: qsTr("刷新显卡列表")
        onClicked: qmlapp.globalConfigs.refreshCudaDevices(true)
        background: Rectangle {
            color: refreshButton.hovered ? theme.coverColor2 : theme.bgColor
            border.width: 1
            border.color: theme.coverColor2
            radius: size_.btnRadius
        }
        contentItem: Text {
            text: refreshButton.text
            color: theme.subTextColor
            font: refreshButton.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }
}
