// ========================================================
// =============== 复选框样式，不提供点击事件 ===============
// ========================================================

import QtQuick 2.15
import QtQuick.Controls 2.15

Rectangle {
    id: track
    property bool checked: false // 选中/非选中
    property bool enabledAnime: false // true 启用动画

    height: size_.line
    width: size_.line*2
    clip: true
    color: checked ? theme.yesColor : theme.coverColor2
    radius: height / 2
    border.width: 2
    border.color: checked ? theme.yesColor : theme.coverColor4

    // 颜色和滑块位置共同标记状态，不使用勾选图标。
    Rectangle {
        id: thumb
        width: parent.height - 6
        height: width
        x: checked ? parent.width - width - 3 : 3
        anchors.verticalCenter: parent.verticalCenter
        color: checked ? theme.bgColor : theme.subTextColor
        radius: width / 2
        Behavior on x { // 位移动画
            enabled: qmlapp.enabledEffect && enabledAnime
            NumberAnimation {
                duration: 200
                easing.type: Easing.OutCirc
            }
        }
    }

    Behavior on color {
        enabled: qmlapp.enabledEffect && enabledAnime
        ColorAnimation { duration: 160 }
    }
}
