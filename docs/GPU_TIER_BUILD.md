# Windows x64 GPU 插件分档

主程序不分 GPU 档。CUDA 与 PaddleVL 各发布两种互斥的安装归档。同一插件 ID、同一版本的普通档和 RTX 50 档不可叠加解包；切换时先退出程序，按已有程序载荷所有权更新，保留用户配置、任务和模型。

| 档位 | Paddle 私有 CUDA 闭包 | 实际 Paddle 核心架构 | Windows x64 运行后缀 |
| --- | --- | --- | --- |
| 普通 `cu126` | 12.6 | `sm75/80/86/89` | `_CUDA.tar.xz` / `_PaddleVL.tar.xz` |
| RTX 50 `cu129` | 12.9 | `sm75/80/86/89/120` | `_CUDA_RTX50.tar.xz` / `_PaddleVL_RTX50.tar.xz` |

两个 Paddle 核心都必须支持该 GPU；不能把不同 DLL 的目标取并集。MX250（`sm61`）不支持，插件不回退 CPU。RTX 50 档仍含部分旧卡代码；`sm120` 静态覆盖不等于实机通过。PaddleVL 自带的 llama CUDA 13.x 和驱动条件另外核对。

## 构建与溯源

- `Build-GpuPlugin.ps1` 与独立 PaddleVL 仓的 `Build-Plugin.ps1` 使用 `-GpuTier cu126` 或 `-GpuTier cu129`。requirements、GPU 支持记录和来源锁必须属于同一档；不能通过单独换一个 DLL 或修改设置下拉来换档。
- 普通档使用 `-ReviewedSeedArchive` 及写入前重新实测的 `-RepositoryAllocatedBytes`。锁定基线是 CUDA 3.0.6 和 PaddleVL 3.1.4 的已验收精简归档。恢复的是逐成员私有依赖、原始分发记录及 CUDA 随包模型，不复用旧适配器、启动器或版本，也不重播 PaddleX 补丁。新包仍须验证实际新启动器、运行闭包和重新安装。
- RTX 50 档沿用 cu129 的逐文件精简继承锁，采用同一批准的依赖种子、派生 wheel 和许可门禁。PaddleVL 自 3.1.6 起只导入外部已审 llama 成品及对应源码，不调用两仓旧自建入口。
- 新包从冻结运行记录决定文件名，普通档与 RTX 50 档各有独立的对应源码归档名。历史文件保留原名，按真实运行档归类，不按后缀反推旧包内容。每个组件／系统／架构／档位仅保留最新与紧邻上一版；包未验收前不删除可用的旧安装或唯一证据。

本地归档、GPU 通过或源码快照均不构成公开发布授权。每档分别记录来源、真实设备和执行结果；继续保留 NVIDIA 再分发、AGPL/可选私有部件、完整对应源码及当次程序/文案审阅门禁。
