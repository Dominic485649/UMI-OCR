// ===========================================
// =============== 右键弹出菜单 ===============
// ===========================================

import QtQuick 2.15
import QtQuick.Controls 2.15

Menu {
    id: mRoot
    property var menuList: []
    property var childMenu_: null
    signal actionTriggered()
    padding: size_.smallSpacing
    width: size_.line * 10
    // 兼容旧条目 [func, text, color]；新条目可含 enabled、tip、children。
    function value(entry, key, legacyIndex, fallback) {
        if(Array.isArray(entry)) return entry.length > legacyIndex ? entry[legacyIndex] : fallback
        return entry && entry[key] !== undefined ? entry[key] : fallback
    }
    function isEnabled(entry) { return !!value(entry, "enabled", 3, true) }
    function closeChild() {
        if(!childMenu_) return
        const child = childMenu_
        childMenu_ = null
        child.close()
        child.destroy()
    }
    function activate(entry, y) {
        if(!isEnabled(entry)) return
        const children = value(entry, "children", 5, [])
        if(children.length) {
            closeChild()
            // 延迟创建同一菜单类型，避免静态递归实例化；沿用 Menu_ 的全部样式。
            const component = Qt.createComponent(Qt.resolvedUrl("Menu_.qml"))
            const child = component.createObject(mRoot.parent, {menuList: children})
            if(!child) return
            childMenu_ = child
            child.actionTriggered.connect(function() { mRoot.actionTriggered(); mRoot.close() })
            child.x = mRoot.x + mRoot.width - mRoot.padding
            child.y = mRoot.y + y
            child.open()
            return
        }
        const callback = value(entry, "action", 0, undefined)
        if(callback) callback()
        actionTriggered()
        close()
    }
    onClosed: closeChild()
    onMenuListChanged: closeChild() // 状态变化后不保留带旧 enabled/产物链接的子菜单。

    contentItem: Rectangle {
        id: mRect
        color: "transparent"
        implicitHeight: menuColumn.implicitHeight
        Column {
            id: menuColumn
            width: parent.width
            spacing: 2
            Repeater {
                model: menuList
                Item {
                    id: menuRow
                    width: menuColumn.width
                    height: size_.line + size_.smallSpacing * 2
                    property var entry: modelData
                    Button_ {
                        objectName: mRoot.value(menuRow.entry, "objectName", 6, "")
                        anchors.fill: parent
                        radius: size_.btnRadius
                        enabled: mRoot.isEnabled(menuRow.entry)
                        opacity: enabled ? 1 : 0.45
                        contentItem: Text_ {
                            id: menuText
                            text: mRoot.value(menuRow.entry, "text", 1, "")
                                + (mRoot.value(menuRow.entry, "children", 5, []).length ? "  ›" : "")
                            property string colorKey: mRoot.value(menuRow.entry, "color", 2, "textColor")
                            color: theme[colorKey] || theme.textColor
                            verticalAlignment: Text.AlignVCenter
                            function fitWidth() {
                                mRoot.width = Math.max(mRoot.width, implicitWidth + size_.spacing * 3)
                            }
                            Component.onCompleted: fitWidth()
                            onImplicitWidthChanged: fitWidth()
                        }
                        onClicked: mRoot.activate(menuRow.entry, menuRow.y)
                    }
                    // 禁用项仍可解释原因，不让悬停层接管鼠标点击。
                    MouseArea {
                        id: rowHover
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.NoButton
                    }
                    ToolTip_ {
                        visible: rowHover.containsMouse && text.length > 0
                        text: mRoot.value(menuRow.entry, "tip", 4, "")
                    }
                }
            }
        }
    }
    background: Rectangle {
        color: theme.specialBgColor
        border.width: 1
        border.color: theme.coverColor4
        radius: size_.panelRadius
    }
    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 }
        NumberAnimation { property: "scale"; from: 0.98; to: 1; duration: 140; easing.type: Easing.OutCubic }
    }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 100 } }
}
