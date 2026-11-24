// =============== 文件表格面板 ===============

import QtQuick 2.15
import QtQuick.Controls 2.15
import Qt.labs.qmlmodels 1.0
import Qt5Compat.GraphicalEffects

Item {
    id: fTableRoot
    property var headers: [
        {key: "path", title: "文件"},
        {key: "time", title: "耗时"},
        {key: "state", title: "状态"}
    ]
    property string openBtnText: "选择文件"
    property string clearBtnText: "清空"
    property string defaultTips: "拖入或选择文件"
    property string fileDialogTitle: "请选择文件"
    property var fileDialogNameFilters: ["文件 (*.jpg *.jpe *.jpeg *.jfif *.png *.avif *.webp *.jxl *.jxr *.wdp *.hdp *.bmp *.tif *.tiff)"]
    property int spacing: size_.smallLine
    property int minWidth0: size_.smallLine * 5
    property bool isLock: false
    // 保留原有锁；运行中只按页面授权放开导入，不能顺便放开清空。
    property bool allowOpenWhileLocked: false
    property var clearHandler: undefined
    property string statusText: ""
    property bool dragSortEnabled: false // 默认不改变其它页面的交互。
    property bool contextMenuEnabled: false
    property var canMoveRow: undefined // (稳定路径) => bool
    property var rowMenuBuilder: undefined // (稳定路径) => Menu_ 条目
    property string contextPath: ""
    property string dragPath: ""
    property string dragBeforePath: ""
    property real dragPointerY: 0
    property real dragIndicatorY: 0
    readonly property bool openEnabled: !isLock || allowOpenWhileLocked
    readonly property bool clearEnabled: !isLock
    signal addPaths(var paths)
    signal click(var info)
    signal rowMoveRequested(string path, string beforePath)

    // ========================= 【数据接口】 =========================

    // 所有结构变化共用索引重建，禁止沿用插入/删除/移动之前的 path -> index。
    function rebuildIndex() {
        const dict = {}
        for(let i = 0; i < dataModel.count; i++) dict[dataModel.get(i)[headerKey]] = i
        dataDict = dict
    }
    function ik2i(ik) {
        if(typeof ik === "number") return Number.isInteger(ik) && ik >= 0 && ik < rowCount ? ik : -1
        if(typeof ik === "string" && Object.prototype.hasOwnProperty.call(dataDict, ik)) {
            const i = dataDict[ik]
            if(i >= 0 && i < rowCount && dataModel.get(i)[headerKey] === ik) return i
        }
        return -1
    }
    function add(row, ik=-1) {
        const key = row[headerKey]
        if(typeof key !== "string" || ik2i(key) >= 0) return false
        const i = (ik === -1 || ik === rowCount) ? rowCount : ik2i(ik)
        if(i < 0) return false
        if(i === rowCount) dataModel.append(row)
        else dataModel.insert(i, row)
        rebuildIndex()
        updateWidth()
        return true
    }
    function del(ik) {
        const i = ik2i(ik)
        if(i < 0) return false
        if(dataModel.get(i)[headerKey] === dragPath) cancelRowDrag()
        dataModel.remove(i)
        rebuildIndex()
        updateWidth()
        return true
    }
    function clear() {
        cancelRowDrag()
        rowMenu.close()
        dataModel.clear()
        rebuildIndex()
    }
    // 仅在权威快照到达后移动模型；鼠标松手不先行修改显示顺序。
    function move(ik, to) {
        const from = ik2i(ik)
        if(from < 0 || !Number.isInteger(to) || to < 0 || to >= rowCount) return false
        if(from !== to) dataModel.move(from, to, 1)
        rebuildIndex()
        updateWidth()
        return true
    }
    function set(ik, columnDict) {
        const i = ik2i(ik)
        if(i < 0) return false
        if(columnDict[headerKey] !== undefined && columnDict[headerKey] !== dataModel.get(i)[headerKey]
            && ik2i(columnDict[headerKey]) >= 0) return false
        dataModel.set(i, columnDict)
        if(columnDict[headerKey] !== undefined) rebuildIndex()
        updateWidth()
        return true
    }
    function setProperty(ik, columnKey, value) {
        const change = {}
        change[columnKey] = value
        return set(ik, change)
    }
    function get(ik) {
        const i = ik2i(ik)
        return i < 0 ? {} : dataModel.get(i)
    }
    function getColumnsValue(key) {
        const list = []
        for(let i = 0; i < rowCount; i++) list.push(dataModel.get(i)[key])
        return list
    }
    function getColumnsValues(keys=[]) {
        const list = []
        for(let i = 0; i < rowCount; i++) {
            if(!keys.length) { list.push(dataModel.get(i)); continue }
            const row = {}
            for(const key of keys) row[key] = dataModel.get(i)[key]
            list.push(row)
        }
        return list
    }
    // 增量协调快照，逐页进度更新不再 clear 全表，保留滚动位置和现有 delegate。
    function reconcileRows(rows) {
        const wanted = {}
        for(let i = 0; i < rows.length; i++) {
            const key = rows[i][headerKey]
            if(typeof key !== "string" || Object.prototype.hasOwnProperty.call(wanted, key)) return false
            wanted[key] = true
        }
        for(let i = rowCount - 1; i >= 0; i--)
            if(!Object.prototype.hasOwnProperty.call(wanted, dataModel.get(i)[headerKey])) del(i)
        for(let i = 0; i < rows.length; i++) {
            const row = rows[i]
            const current = ik2i(row[headerKey])
            if(current < 0) add(row, i)
            else {
                if(current !== i) move(current, i)
                const changed = {}, previous = dataModel.get(i)
                for(const key of Object.keys(row))
                    if(previous[key] !== row[key]) changed[key] = row[key]
                if(Object.keys(changed).length) set(i, changed)
            }
        }
        rebuildIndex()
        refreshContextMenu()
        return true
    }
    function replaceRows(rows) { return reconcileRows(rows) }

    // ========================= 【交互接口】 =========================

    function requestClear() {
        if(!clearEnabled) return false
        if(clearHandler) clearHandler()
        else clear()
        return true
    }
    function refreshContextMenu() {
        if(rowMenu.visible && rowMenuBuilder) rowMenu.menuList = rowMenuBuilder(contextPath) || []
    }
    function openRowMenu(path, x, y) {
        if(!contextMenuEnabled || !rowMenuBuilder || ik2i(path) < 0) return false
        contextPath = path // 捕获路径，不捕获会随扫描、排序和移除变化的行号。
        rowMenu.menuList = rowMenuBuilder(path) || []
        rowMenu.x = x
        rowMenu.y = y
        rowMenu.open()
        return true
    }
    function isRowMovable(path) { return dragSortEnabled && (!canMoveRow || canMoveRow(path)) }
    function beginRowDrag(path, y) {
        if(!isRowMovable(path) || ik2i(path) < 0) return false
        dragPath = path
        updateRowDrag(y)
        return true
    }
    function updateRowDrag(y) {
        if(!dragPath) return
        dragPointerY = y
        const stride = size_.smallLine * 1.5 + tableView.rowSpacing
        const landing = Math.max(0, Math.min(rowCount, Math.round((tableView.contentY + y) / stride)))
        let before = ""
        for(let i = landing; i < rowCount; i++) {
            const key = dataModel.get(i)[headerKey]
            if(key !== dragPath && isRowMovable(key)) { before = key; break }
        }
        dragBeforePath = before
        dragIndicatorY = Math.max(0, Math.min(tableView.height - 3,
            (before ? ik2i(before) : rowCount) * stride - tableView.contentY))
    }
    function cancelRowDrag() { dragPath = ""; dragBeforePath = "" }
    function finishRowDrag() {
        const path = dragPath, before = dragBeforePath
        cancelRowDrag()
        if(!path || ik2i(path) < 0) return false
        rowMoveRequested(path, before) // 后端此刻再次检查 pending，真实顺序只取后端快照。
        return true
    }
    function activateColumn(path, x) {
        const i = ik2i(path)
        if(i < 0) return
        let boundary = 0
        for(let column = 0; column < columnCount; column++) {
            boundary += headerModel.get(column).width - 1
            if(x <= boundary) {
                if(headers[column].btn && headers[column].onClicked) headers[column].onClicked(i)
                return
            }
        }
    }
    onDragSortEnabledChanged: { if(!dragSortEnabled) cancelRowDrag() }
    onContextMenuEnabledChanged: { if(!contextMenuEnabled) rowMenu.close() }

    // ========================= 【布局逻辑】 =========================

    property int columnCount: 0
    property int rowCount: dataModel.count
    property string headerKey: "path"
    property var dataDict: ({})
    ListModel { id: headerModel }
    ListModel { id: dataModel }
    Component.onCompleted: {
        columnCount = headers.length
        for(let i = 0; i < columnCount; i++)
            headerModel.append({key: headers[i].key, title: headers[i].title, width: 1})
        headerKey = headers[0].key
        updateWidth(true)
    }
    onRowCountChanged: {
        if(headerModel.count) headerModel.setProperty(0, "title", headers[0].title + ` (${rowCount})`)
    }
    Timer {
        id: updateWidthTimer
        interval: 100
        onTriggered: updateWidth(true)
    }
    function updateWidth(timer=false) {
        if(!timer) { updateWidthTimer.restart(); return }
        const ws = Array(columnCount).fill(1)
        for(let i = 1; i < columnCount; i++) {
            const item = headerRepeater.itemAt(i)
            if(item) ws[i] = Math.max(ws[i], item.maxWidth + spacing * 2)
        }
        for(const row of tableView.contentItem.children) {
            if(!row.repeater) continue
            for(let x = 1; x < columnCount; x++) {
                const cell = row.repeater.itemAt(x)
                if(cell) ws[x] = Math.max(ws[x], cell.maxWidth + spacing * 2)
            }
        }
        let w0 = tableArea.width
        for(let i = 1; i < columnCount; i++) {
            headerModel.setProperty(i, "width", ws[i])
            w0 -= ws[i]
        }
        updateWidth0(w0)
    }
    function updateWidth0(w0=-1) {
        if(!headerModel.count) return
        if(w0 < 0) {
            w0 = tableArea.width
            for(let i = 1; i < columnCount; i++) w0 -= headerModel.get(i).width
        }
        headerModel.setProperty(0, "width", Math.max(minWidth0, w0 + columnCount - 10))
    }

    Rectangle {
        id: tableArea
        anchors.fill: parent
        color: theme.bgColor
        Item {
            id: tableContainer
            anchors.fill: parent
            Item {
                id: tableTopPanel
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: size_.line * 2 + loadingStatus.height
                Text_ {
                    id: loadingStatus
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: fTableRoot.statusText ? size_.smallLine * 1.5 : 0
                    visible: height > 0
                    text: fTableRoot.statusText
                    font.pixelSize: size_.smallText
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                IconTextButton {
                    id: openBtn
                    objectName: "filesOpenButton"
                    visible: parent.width > openBtn.width + clearBtn.width
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: loadingStatus.top
                    anchors.margins: size_.smallSpacing * 0.5
                    icon_: "folder"
                    text_: openBtnText
                    enabled: fTableRoot.openEnabled
                    opacity: enabled ? 1 : 0.45
                    onClicked: { if(openEnabled) fileDialog.open() }
                }
                IconTextButton {
                    id: clearBtn
                    objectName: "filesClearButton"
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: loadingStatus.top
                    anchors.margins: size_.smallSpacing * 0.5
                    icon_: "clear"
                    text_: clearBtnText
                    enabled: fTableRoot.clearEnabled
                    opacity: enabled ? 1 : 0.45
                    onClicked: requestClear()
                }
            }
            DefaultTips {
                visibleFlag: fTableRoot.rowCount
                anchors.top: tableTopPanel.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                tips: defaultTips
            }
            Item {
                id: tableHeaderContainer
                visible: fTableRoot.rowCount > 0
                anchors.top: tableTopPanel.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                height: size_.line * 1.5
                onWidthChanged: updateWidth0()
                Row {
                    anchors.fill: parent
                    spacing: -1
                    Repeater {
                        id: headerRepeater
                        model: headerModel
                        Rectangle {
                            width: model.width
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            color: theme.bgColor
                            border.width: 1
                            border.color: theme.coverColor2
                            property alias maxWidth: hText.width
                            Text_ {
                                id: hText
                                anchors.top: parent.top
                                anchors.bottom: parent.bottom
                                anchors.horizontalCenter: parent.horizontalCenter
                                verticalAlignment: Text.AlignVCenter
                                font.pixelSize: size_.smallText
                                text: model.title
                            }
                        }
                    }
                }
            }
            TableView {
                id: tableView
                objectName: "filesTableViewport"
                anchors.top: tableHeaderContainer.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                flickableDirection: Flickable.VerticalFlick
                boundsBehavior: Flickable.StopAtBounds
                model: dataModel
                clip: true
                rowSpacing: -1
                delegate: Item {
                    id: tableRow
                    objectName: "fileRow:" + rowPath
                    Component.onCompleted: updateWidth()
                    TableView.onReused: { rowContent.y = 0; updateWidth() }
                    implicitHeight: size_.smallLine * 1.5
                    implicitWidth: tableView.width
                    property int rowIndex: index
                    property var rowModel: model
                    property string rowPath: rowModel[headerKey] || ""
                    property alias repeater: repeater
                    z: dragPath === rowPath ? 2 : 0
                    onRowPathChanged: { if(rowContent) rowContent.y = 0 }
                    Row {
                        id: rowContent
                        width: parent.width
                        height: parent.height
                        y: 0
                        opacity: dragPath === tableRow.rowPath ? 0.6 : 1
                        spacing: -1
                        Repeater {
                            id: repeater
                            model: headerModel
                            Rectangle {
                                width: model.width
                                anchors.top: parent.top
                                anchors.bottom: parent.bottom
                                color: theme.bgColor
                                border.width: 1
                                border.color: theme.coverColor2
                                property alias maxWidth: hText.width
                                property int columnIndex: index
                                property string columnKey: model.key
                                property var header: headers[columnIndex]
                                clip: true
                                Button_ {
                                    visible: header.btn ? true : false
                                    anchors.fill: parent
                                    radius: 0
                                    onClicked: { if(header.onClicked) header.onClicked(rowIndex) }
                                }
                                Text_ {
                                    id: hText
                                    property bool isLeft: header.left ? true : false
                                    anchors.top: parent.top
                                    anchors.bottom: parent.bottom
                                    anchors.left: isLeft ? parent.left : undefined
                                    anchors.leftMargin: fTableRoot.spacing * 0.5
                                    anchors.horizontalCenter: isLeft ? undefined : parent.horizontalCenter
                                    verticalAlignment: Text.AlignVCenter
                                    font.pixelSize: size_.smallText
                                    color: (columnKey !== "state" || typeof rowModel.state !== "string" || !rowModel.state.length)
                                        ? theme.subTextColor : (rowModel.state.startsWith("×") ? theme.noColor
                                        : (rowModel.state.startsWith("√") ? theme.yesColor : theme.subTextColor))
                                    text: header.display ? header.display(rowModel[columnKey]) : rowModel[columnKey]
                                }
                            }
                        }
                    }
                    // 与标签栏相同的 MouseArea 阈值拖动和落点反馈，不创建内部 URL DropArea。
                    MouseArea {
                        id: rowMouse
                        objectName: "fileRowMouse:" + tableRow.rowPath
                        anchors.fill: parent
                        enabled: dragSortEnabled || contextMenuEnabled
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        preventStealing: true
                        property string pressedPath: ""
                        property bool moved: false
                        drag.target: dragSortEnabled && isRowMovable(tableRow.rowPath)
                            && (pressedButtons & Qt.LeftButton) ? rowContent : undefined
                        drag.axis: Drag.YAxis
                        drag.threshold: 12
                        property bool dragActive: drag.active
                        onPressed: function(mouse) { pressedPath = tableRow.rowPath; moved = false }
                        onDragActiveChanged: {
                            if(drag.active) {
                                const point = mapToItem(tableView, mouseX, mouseY)
                                moved = beginRowDrag(pressedPath, point.y)
                            }
                        }
                        onPositionChanged: function(mouse) {
                            if(moved) updateRowDrag(mapToItem(tableView, mouse.x, mouse.y).y)
                        }
                        onReleased: {
                            rowContent.y = 0
                            if(moved) finishRowDrag()
                        }
                        onCanceled: { rowContent.y = 0; moved = false; cancelRowDrag() }
                        onClicked: function(mouse) {
                            if(moved) return
                            if(mouse.button === Qt.RightButton) {
                                const point = mapToItem(fTableRoot, mouse.x, mouse.y)
                                openRowMenu(pressedPath, point.x, point.y)
                            }
                            else activateColumn(pressedPath, mouse.x)
                        }
                    }
                }
                ScrollBar.vertical: ScrollBar {}
            }
            Rectangle {
                x: tableView.x
                y: tableView.y + dragIndicatorY
                width: tableView.width
                height: 3
                z: 5
                visible: dragPath.length > 0
                color: theme.specialTextColor
            }
            Timer {
                interval: 40
                repeat: true
                running: dragPath.length > 0
                onTriggered: {
                    const delta = dragPointerY < size_.line ? -size_.smallLine
                        : (dragPointerY > tableView.height - size_.line ? size_.smallLine : 0)
                    if(!delta) return
                    tableView.contentY = Math.max(0, Math.min(Math.max(0, tableView.contentHeight - tableView.height),
                        tableView.contentY + delta))
                    updateRowDrag(dragPointerY)
                }
            }
        }
        layer.enabled: true
        layer.effect: OpacityMask {
            maskSource: Rectangle {
                width: tableContainer.width
                height: tableContainer.height
                radius: size_.btnRadius
            }
        }
    }
    Menu_ { id: rowMenu; objectName: "filesRowMenu" }
    FileDialog_ {
        id: fileDialog
        title: fileDialogTitle
        nameFilters: fileDialogNameFilters
        selectMultiple: true
        onAccepted: addPaths(fileDialog.fileUrls_)
    }
}
