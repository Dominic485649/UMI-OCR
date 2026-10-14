// =========================================
// =============== 文件选择窗 ===============
// =========================================

import QtQuick
import QtQuick.Dialogs

Item {
    id: root
    property var fileUrls_: [] // 缓存处理好的 fileUrls
    property url fileUrl: ""
    property url folder: ""
    property string title: ""
    property bool selectExisting: true
    property bool selectFolder: false
    property bool selectMultiple: false
    property var nameFilters: []
    signal accepted()
    signal rejected()

    function open() {
        if (selectFolder)
            folderDialog.open()
        else
            fileDialog.open()
    }

    FileDialog {
        id: fileDialog
        title: root.title
        currentFolder: root.folder
        nameFilters: root.nameFilters
        fileMode: root.selectExisting
            ? (root.selectMultiple ? FileDialog.OpenFiles : FileDialog.OpenFile)
            : FileDialog.SaveFile
        onAccepted: {
            root.fileUrl = selectedFile
            root.fileUrls_ = qmlapp.utilsConnector.QUrl2String(selectedFiles)
            if (!root.selectExisting && root.fileUrls_.length === 0)
                root.fileUrls_ = [selectedFile.toString()]
            root.accepted()
        }
        onRejected: root.rejected()
    }

    FolderDialog {
        id: folderDialog
        title: root.title
        currentFolder: root.folder
        onAccepted: {
            root.fileUrl = selectedFolder
            root.fileUrls_ = qmlapp.utilsConnector.QUrl2String([selectedFolder])
            root.accepted()
        }
        onRejected: root.rejected()
    }
}
