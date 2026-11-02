# 本地 3.1.0 候选安装

状态：2026-10-26，已按用户“什么都不保留，直接却换”的明确要求，删除旧固定安装及全部旧配置、日志和任务数据，不做备份，直接切换到本地3.1.0候选版。

**固定安装现已更新到release/Umi-OCR。** 程序内主版本保持3.1.0，归档名称及安装附加说明标明非最终候选。没有推送GitHub、打标签或创建Release。

可运行 [固定目录主程序](../release/Umi-OCR/Umi-OCR.exe)，安装状态见 [非最终候选说明](../release/Umi-OCR/LOCAL-CANDIDATE.txt)。

## 组件与归档

| 组件 | 实际版本 | 本地候选归档 |
| --- | --- | --- |
| Umi-OCR 主程序 | 3.1.0 | [纯本体候选](../release/Umi-OCR_v3.1.0-local-candidate_Windows_x64.tar.xz) |
| CUDA 插件 | 3.0.5 | [CUDA候选](../release/Umi-OCR-Plugin_v3.0.5-local-candidate_Windows_x64_CUDA.tar.xz) |
| PaddleVL 插件 | 3.1.0 | [PaddleVL候选](../release/Umi-OCR-Plugin_v3.1.0-local-candidate_Windows_x64_PaddleVL.tar.xz) |

插件版本保持独立，不为对齐主程序而改号。归档仍是原先已验收候选的相同字节，文件名保留local-candidate。VL只携带内置llama.cpp，不含用户主GGUF、mmproj或版面权重。

## 实际切换与验证

- 删除前列出旧安装完整元数据清单，检查新旧路径、链接/junction、执行路径及命令行占用，并逐文件校验新候选内容。
- 旧安装整棵目录及其配置、日志、任务数据已按授权删除，没有读取旧配置或文档内容进行备份，没有创建旧目录副本，也没有自动迁移或恢复旧设置。
- 新候选从已验证的暂存位置移动至固定目录，随后完整文件集合、大小与内容哈希再次匹配原候选载荷及附加说明。
- 固定路径使用其自带CPython 3.13.16检查Qt/PySide原生库、宿主模块来源和独立插件清单，结果通过；没有启动GUI、模型服务或GPU。
- 完整七语原生界面、真实HTTP/GPU及资源测量沿用同一归档载荷的原验收，没有冒称本次重跑。密集VL图质量未全通过、原失败图未复现的限制继续保留。

最初执行在任何删除前因Windows目录st_size读取差异被拦截。完整定位确认只有目录大小字段变化，文件清单、文件元数据及目录身份未变。修正仅规范化非可靠目录大小，保留文件大小、mtime、ID、类型、属性、完整路径、占用与权限检查；新增RED/GREEN回归及原安全用例通过后，重新预演并完成直接切换。原失败记录不改写。

## 保留范围与证据

“什么都不保留”按当前对话指旧固定安装及其用户数据，不扩展到其他位置。项目源码、外部模型、release已有归档、历史审计和有复用价值缓存未清理。

此前暂存位置已移动，历史验收记录仍保留当时的绝对路径，未改写为固定位置或冒充重新运行。固定位置的当前证据单独记录：

- [直接切换及实际删除结果](../build/audit/local-candidate-3.1.0-20261026-r1/direct-switch-20261026-r2/switch-result.json)
- [固定路径运行时检查](../build/audit/local-candidate-3.1.0-20261026-r1/direct-switch-20261026-r2/runtime-probe-result.json)
- [删除前清单与范围](../build/audit/local-candidate-3.1.0-20261026-r1/direct-switch-20261026-r2/preflight.json)
- [候选原验收说明](RELEASE_3.1.0_ACCEPTANCE.md)
