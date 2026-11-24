// 导航入口：名称、用途与键盘焦点始终可见，不依赖悬停简介。
import QtQuick 2.15
import "../../Widgets"

Button_ {
    id: taskButton
    property string description: ""

    activeFocusOnTab: true
    padding: size_.spacing * 2
    implicitHeight: taskContent.implicitHeight + topPadding + bottomPadding
    bgColor_: theme.coverColor1
    borderWidth: visualFocus ? 2 : 1
    borderColor: visualFocus ? theme.specialTextColor : theme.coverColor1
    Accessible.name: text_
    Accessible.description: description

    contentItem: Column {
        id: taskContent
        spacing: size_.spacing
        Text_ {
            width: parent.width
            text: taskButton.text_
            font.pixelSize: size_.largeText
            font.bold: true
            color: taskButton.hovered || taskButton.visualFocus ? theme.specialTextColor : theme.textColor
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
        }
        Text_ {
            width: parent.width
            text: taskButton.description
            color: theme.subTextColor
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
        }
    }
}
