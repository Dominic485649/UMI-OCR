# CUDA 插件 3.0.2 本地候选说明

本地候选插件与 Umi-OCR 主程序产品版本同步为 3.0.2。Host API 兼容范围、CUDA 12.6、推理依赖及模型精度保持现有契约，不因产品 patch 版本改变。

## 安装

1. 将 3.0.2 本体压缩包完整解压到一个新的应用目录。
2. 将匹配的 3.0.2 CUDA 插件压缩包解压到同一应用根目录。
3. 保留 `UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA` 和 `LICENSES/plugins/win32_PaddleOCRv6_CUDA` 的归档层级。
4. 启动该目录中的 `Umi-OCR.exe`。本体与插件版本必须匹配。

归档名为 `Umi-OCR-Plugin_GPU-OCR_v3.0.2-local-candidate_Windows_x64_CUDA12.6.tar.xz`，不是对旧 3.0.1 压缩包简单重命名。插件 manifest、当前适配器和源码材料会重新组装，vendor 与模型字节离线复用。

## 执行与验收边界

- 推理仍在独立 CUDA worker 内执行，主程序不直接装载 Paddle/NVIDIA 推理栈。
- 不提供 CPU fallback。CUDA 缺失或初始化失败必须明确报错，不能用 CPU 执行代替 GPU 验收。
- 不下载或重新派生模型，不变更精度，不声称获得新增模型或商标权利。
- 最终验证从实际本体归档和插件归档重新安装，核对哈希、版本、许可隔离和真实 GPU OCR/PDF。
- 本轮只做本地交付，不发布 GitHub Release，不把公开门禁改为 PASS。

实际结果见 [当版验收记录](RELEASE_3.0.2_ACCEPTANCE.md)及 `build/audit/3.0.2` 的外置记录。历史 3.0.1 的公开接受结论不作为本版验收依据。
