// =========================================
// =============== 水平标签栏 ===============
// =========================================

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

import "../Widgets"

RowLayout  {
    id: hTabBarLayout
    anchors.fill: parent
    spacing: 0

    // 标签栏控制（左，置顶按钮）
    Item  {
        width: size_.hTabBarHeight
        Layout.fillHeight: true
        // 图钉按钮
        Button {
            checkable: true
            checked: mainWindowRoot.isMainWindowTop
            onCheckedChanged: { // 双向绑定锁定标记
                mainWindowRoot.isMainWindowTop = checked
                qmlapp.globalConfigs.setValue("window.isMainWindowTop", checked, true)
            }
            anchors.fill: parent
            anchors.margins: 4

            contentItem: Icon_ {
                icon: "pin"
                anchors.fill: parent
                color: parent.checked ? theme.bgColor : theme.textColor
            }

            background: Rectangle {
                anchors.fill: parent
                radius: size_.btnRadius
                color: parent.checked ? theme.coverColor4 : (
                    parent.hovered ? theme.coverColor2 : "#00000000"
                )
            }

            ToolTip_ {
                visible: parent.hovered
                text: qsTr("窗口置顶")
            }
        }
    }

    // 标签栏本体（中）
    Rectangle  {
        id: hTabBarMain
        Layout.fillWidth: true
        Layout.fillHeight: true
        color: "#00000000"

        property int tabWidth: 200 // 标签当前宽度

        // 方法：重设标签按钮宽度
        function resetTabBtnWidth() {
            let w = hTabBarMain.width
            if(!qmlapp.tab.barIsLock) w -= tabBarControl.width // 无锁定时，减去+按钮宽度
            w = w / barManager.model.count
            tabWidth = Math.min(w, size_.line * 8)
        }
        onWidthChanged: resetTabBtnWidth()  // 监听标签栏总宽度变化
        // 监听改变锁定，重设宽度
        property bool isLock: qmlapp.tab.barIsLock
        onIsLockChanged: {
            hTabBarMain.resetTabBtnWidth()
        }

        MouseArea { // 点击标签栏空余位置，都是添加新标签
            anchors.fill: parent
            onClicked: {
                if(!qmlapp.tab.barIsLock)
                    qmlapp.tab.addNavi() // 添加导航页
            }
        }

        // Rectangle { // 标签按钮下方的阴影
        //     anchors.bottom: parent.bottom
        //     width: parent.width
        //     height: size_.hTabBarHeight * 0.5
        //     gradient: Gradient {
        //         GradientStop { position: 0.0; color: "#00000000" }
        //         GradientStop { position: 1.0; color: theme.coverColor2 }
        //     }
        // }

        Rectangle { // 拖拽时的位置指示器
            id: dragIndicator
            visible: false
            width: parent.tabWidth
            height: size_.hTabBarHeight
            gradient: Gradient { // 水平渐变
                orientation: Gradient.Horizontal
                GradientStop { position: 1.0; color: "#00000000" }
                GradientStop { position: 0.0; color: theme.coverColor3 }
            }
        }

        // 水平标签栏行布局
        Row {
            id: hTabBarMainRow
            spacing: -1 // 给负的间隔，是为了让选中标签能覆盖左右两边标签的竖线

            // ===== 标签按钮组 =====
            BarManager {
                id: barManager
                // 标签元素模板
                delegate: TabButton_ {
                    title: title_ // 标题
                    checked: checked_ // 初始时是否选中
                    index: index_ // 初始位置
                    width: hTabBarMain.tabWidth
                }

                // 事件：创建新标签时（与父类的槽同时生效）
                onItemAdded: function(_index, item) {
                    // 链接表现相关的槽函数
                    item.dragStart.connect(dragStart)
                    item.dragFinish.connect(dragFinish)
                    item.dragMoving.connect(dragMoving)
                }

                // 事件：按钮数量变化
                onCountChanged: hTabBarMain.resetTabBtnWidth()

                // ========================= 【拖拽相关】 =========================

                property var intervalList: [] // 记录按钮位置区间的列表
                property var originalPosList: [] // 记录按钮初始位置的列表
                property int originalX // 记录本轮拖拽前，被拖拽按钮原本的位置
                function dragStart(index){ // 方法：开始拖拽
                    // 重新记录当前所有按钮的位置
                    originalX = itemAt(index).x
                    intervalList = [-Infinity] // 下限：负无穷
                    originalPosList = [itemAt(0).x]
                    for(let i=1, c=model.count; i < c; i++){ // 按钮位置区间
                        const it = itemAt(i)
                        intervalList.push(it.x)
                        originalPosList.push(it.x)
                    }
                    intervalList.push(Infinity) // 上限：负无穷
                    dragIndicator.visible = true

                }
                function btnDragIndex(index){ // 函数：返回当前index应该所处的序号
                    const dragItem = itemAt(index)
                    const x = dragItem.x + Math.round(dragItem.width/2) // 被拖动按钮的中心位置
                    let go = 0 // 应该拖放到的位置
                    for(const c=intervalList.length-1; go < c; go++){
                        if(x >= intervalList[go] && x <= intervalList[go+1]){
                            break;
                        }
                    }
                    return go;
                }
                function dragMoving(index, x){ // 方法：拖拽移动
                    let go = btnDragIndex(index) // 应该拖放到的序号
                    dragIndicator.x = originalPosList[go]
                }
                function dragFinish(index){ // 方法：结束拖拽
                    dragIndicator.visible = false
                    let go = btnDragIndex(index) // 应该拖放到的序号
                    if(index !== go){ // 需要移动
                        // model.move(index, go, 1)
                        qmlapp.tab.moveTabPage(index, go)
                    } else { // 无需移动，则回到原位
                        itemAt(index).x = originalX
                    }
                    resetIndex()
                }
            }
            
            // 元素：控制按钮
            Rectangle{
                id: tabBarControl
                color: "#00000000"
                width: size_.hTabBarHeight
                height: size_.hTabBarHeight
                visible: !qmlapp.tab.barIsLock

                // 添加“+”按钮
                IconButton {
                    anchors.fill: parent
                    anchors.margins: 4
                    icon_: "add"
                    color: theme.textColor
                    onClicked: {
                        qmlapp.tab.addNavi() // 添加导航页
                    }
                }
            }

            // 动画
            add: Transition { // 添加子项
                enabled: qmlapp.enabledEffect
                NumberAnimation {
                    properties: "opacity, scale" // 透明度和大小从小到大
                    from: 0; to: 1.0
                    easing.type: Easing.OutBack // 缓动：超出反弹
                    duration: 300
                }
            }
            move: Transition { // 移动子项
                enabled: qmlapp.enabledEffect
                NumberAnimation {
                    properties: "x,y"
                    easing.type: Easing.OutBack
                    duration: 300
                }
            }
        }
    }

    // 标签栏控制（右，锁定按钮）
    Item{
        width: size_.hTabBarHeight
        Layout.fillHeight: true

        // 锁定“🔒︎”按钮
        Button {
            checkable: true
            checked: qmlapp.tab.barIsLock
            onCheckedChanged: { // 双向绑定锁定标记
                qmlapp.tab.barIsLock = checked
                qmlapp.globalConfigs.setValue("window.barIsLock", checked, true)
            }
            anchors.fill: parent
            anchors.margins: 4

            contentItem: Icon_ {
                icon: "lock"
                anchors.fill: parent
                color: parent.checked ? theme.bgColor : theme.textColor
            }

            background: Rectangle {
                anchors.fill: parent
                radius: size_.btnRadius
                color: parent.checked ? theme.coverColor4 : (
                    parent.hovered ? theme.coverColor2 : "#00000000"
                )
            }

            ToolTip_ {
                visible: parent.hovered
                text: qsTr("锁定标签栏")
            }
        }
    }
}
