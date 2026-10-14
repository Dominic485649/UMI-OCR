// ===========================================
// =============== 右键弹出菜单 ===============
// ===========================================

import QtQuick 2.15
import QtQuick.Controls 2.15


Menu {
    id: mRoot
    property var menuList: []
    padding: size_.smallSpacing
    // [
    //     [func1, "菜单项1"],
    //     [func2, "菜单项2", "noColor"],
    // ]
    
    contentItem: Rectangle {
        id: mRect
        color: "transparent"
        Column {
            anchors.fill: parent
            spacing: 2
            Repeater {
                model: menuList
                Button_ {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    radius: size_.btnRadius
                    height: size_.line + size_.smallSpacing * 2
                    contentItem: Text_ {
                        text: modelData[1]
                        color: modelData.length>2 ? theme[modelData[2]] : theme.textColor
                        verticalAlignment: Text.AlignVCenter
                        Component.onCompleted: {
                            let w = width + size_.spacing * 2
                            if(w > mRoot.width) {
                                mRoot.width = w
                            }
                        }
                    }

                    onClicked: {
                        const func = menuList[index][0]
                        func && func()
                        mRoot.close()
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
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 100 }
    }
}
