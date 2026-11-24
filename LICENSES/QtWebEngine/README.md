# Qt WebEngine 6.11.2 / Chromium 许可与源码

使用锁定 PySide6 6.11.2 官方 wheel 的未修改动态库与 QtWebEngineProcess，保留 Chromium 沙箱。Qt/PySide 使用其开放许可选择；完整 LGPL/GPL 文本在上级 LICENSES。Chromium 及第三方材料不能仅凭 Qt 的许可替代。

同版官方完整源码归档位于独立对应源码材料的 third_party/qtwebengine-everywhere-src-6.11.2.tar.xz（完整构建树为 source/third_party/）；SHA-256 与官方 URL 见 manifest.json。third-party-notices.zip 从该锁定归档只读提取法律文件及 qt_attribution.json，保留原始路径与字节，不执行来源脚本。筛选不再按文件名包含 notice 等子串，界面源码、生成器脚本、图片和哈希旁文件不作为法律文本附送。少数以注释、C++ raw string 或许可补丁承载的原始法律正文按精确路径和 SHA-256 保留，不仅凭扩展名删除许可。

此记录不声称自行重建 Qt/Chromium，也不替代各组件实际许可条件。构建和源文件恢复入口、锁定 wheel 与输入摘要随独立对应源码保留。
