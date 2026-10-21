# Windows CUDA 构建文档

本文档说明 Umi-OCR 独立 Windows x64 基础包和 CUDA 12.6 插件的构建契约，产品版本从 `UmiOCR-data/about.json` 读取。展示名、窗口标题、`Umi-OCR.exe` 和便携设置目录 `.settings` 保持为 `Umi-OCR`；Host API 兼容范围不随产品版本变化。

**日期冻结状态（2026-10-22，本轮 fresh 重建开始前）**：3.0.3 的历史 R2 已完成基础/组合、热 GUI、托盘/HTTP/退出、GPU、归档重装和源码/模型核验；两个公开 `v3.0.3` 源码标签已存在，但 binary Release 尚未创建、上传或公开。本轮计划修正正式门禁接线并 fresh noncandidate `-SkipArchive` prepare，此截点尚未构建，不继承 R2 PASS、哈希或审查同意。实际程序及两份文案须再次交审，同意后才更新 main/tag；正式 source gate 等标签匹配后运行，再受限 finalize。详见 [3.0.3 验收契约](RELEASE_3.0.3_ACCEPTANCE.md)、[审查要求](RELEASE_3.0.3_REVIEW.md)和[源码交付契约](../SOURCE-CODE.md)。

## 构建环境

- Windows 10/11 x64。
- NVIDIA GPU，Windows 驱动 `560.76` 或更高版本。无需预装 CUDA Toolkit；锁定的 CUDA 12.6/cuDNN DLL 随便携包提供。Scoop 等位置中的系统 CUDA 不参与构建产物运行时解析，也不能替代包内 DLL。
- Visual Studio 2026、MSVC 14.51、Windows SDK 10.0.28000.0，安装“使用 C++ 的桌面开发”。脚本使用 `vswhere` 查找，不依赖机器绝对路径。
- CMake、Git、PowerShell 7、`7z.exe` 和 Windows 自带 `tar.exe`、`curl.exe` 可从 `PATH` 调用。
- Qt/PySide6 6.11.2。离线构建只使用已存在的 runtime、wheel 闭包、模型和对应源码缓存；`-Offline` 缺锁定输入即失败，禁止联网。首次准备依赖或升级锁须单独获得批准。

最终用户不需要安装 Python、pip、CUDA Toolkit 或执行任何安装命令。

### 为什么仍使用 CUDA 12.6

当前仍锁定 cu126 组合；没有当前同模型、同机器的验收证据支持切换 cu130/cu133。系统 CUDA Toolkit 不替代便携运行 DLL。本地构建和复制完整性检查不代表当前成品已经通过 GPU E2E。

## 锁定与来源

- `build/requirements-windows-cu126.in`：直接运行时依赖。
- `build/constraints-windows-cu126.in`：已实测的传递依赖约束。
- `build/requirements-base-windows.lock`：基础包 wheel 版本与 SHA256。
- `build/requirements-gpu-plugin-windows-cu126.lock`：GPU 插件 wheel 版本与 SHA256。
- `build/sources-windows-cu126.lock.json`：Python 与 PP-OCRv6 官方模型的 URL、大小和 SHA256。
- `UmiOCR-data/native-dlls.lock.json`：构建时生成并进入发布包，记录所有原生 DLL 的相对路径、文件版本与 SHA256。

重新解析 wheel 锁（只在升级依赖时执行）：

```powershell
pwsh -File .\build\windows\Resolve-Lock.ps1
```

## 离线构建示例与本轮正式准备

从仓库根目录执行；构建编译本地原生组件、复制和静态审计，不启动产品或 GPU，不下载包或模型。所有输出路径必须全新，seed 只读。构建入口不扫描、删除或重建旧 staging。

下面保留带 `-LocalCandidate` 的开发候选示例，路径名沿用 3.0.2 阶段示例，**不是本轮 3.0.3 正式 prepare/finalize 命令**，也不证明这些旧 seed 仍可用。本轮按已批准方案在新目录走 non-`LocalCandidate`、`-SkipArchive` prepare，实际路径、只读 seed、base 与 CUDA overlay 输出须以本轮具名构建记录为准。独立 GPU staging 不自动等同正式 overlay；应在真实 GPU 回执及材料固定后一次性生成实际 overlay，再冻结该 overlay。完成真实本地验收并冻结实际 source/payload 后先交审；获同意及公开标签匹配后才 fresh gate 和受限 finalize。不能直接省略 `-SkipArchive` 绕过此顺序，下面的开发组装/拆分同样不能替代正式 finalize。

```powershell
$repo = (Get-Location).Path
$run = Get-Date -Format 'yyyyMMdd-HHmmss'
$base = Join-Path $repo "build/staging/302-base-$run"
$gpu = Join-Path $repo "build/staging/302-gpu-$run"
# 首次升级示例；清理旧版本后，改为当版验收记录中的有效只读 seed。
$baseSeed = "$repo/build/staging/301-base-20261018"
$gpuSeed = "$repo/build/staging/301-gpu-20261018"
pwsh -File ./build/windows/Build-Release.ps1 -StagingRoot $base `
  -ReuseDependencies -ReuseFromStagingRoot $baseSeed `
  -Offline -SkipTests -SkipArchive -LocalCandidate
pwsh -File ./build/windows/Build-GpuPlugin.ps1 -StagingRoot $gpu -BaseStagingRoot $base `
  -ReuseDependencies -ReuseVendorFromStagingRoot $gpuSeed `
  -ReuseModels -SkipModels -Offline -SkipArchive -LocalCandidate
$python = "$base/UmiOCR-data/runtime/python.exe"
```

Base 只复制 runtime/site-packages 和 Qt manifest，再复制包含未 tracked 文件的当前公开宿主源码，并重新编译启动器/HDR DLL。GPU 复制 vendor 和已派生模型；`-SkipModels` 只禁止模型下载/派生，必须配合 `-ReuseModels`。缺 seed、源码缓存或哈希/大小不符会失败，不回退联网。

可选组装和拆分公开产品，不隐式读取兄弟 CPU/VL 仓库：

```powershell
$complete = "$repo/build/artifacts/3.0.2-$run/complete"
pwsh -File ./build/windows/Assemble-Candidate.ps1 -Destination $complete `
  -BaseStagingRoot $base -GpuStagingRoot $gpu
& $python -B ./build/tools/prepare_products.py --complete-root $complete `
  --products-root "$repo/build/artifacts/3.0.2-products-$run"
& $python -B ./build/tools/export_cuda_source.py `
  --output-dir "$repo/build/artifacts/302-plugin-repository-$run"
```

源码导出仅包含公开 CUDA 适配器、所需公开构建工具、docs、锁、许可证和锁定对应源码材料，保留相对路径，不创建远端、Git 历史或发布。目标存在即失败；不要清理已有导出以重试。显式 `-CpuStagingRoot`、`-VlStagingRoot` 和 `--optional-plugin ID=PATH` 仅用于可选开发工作流；公开默认不选择它们。`source_snapshot.py` 默认为 `public`，包含未 tracked 公开源码，排除 vendor/models/cache/artifacts/临时数据；直接生成快照也要求已有锁定对应源码缓存。

## tar.xz 与安装路径

两个 Build 脚本都调用 `build/tools/package_tar_xz.py`。归档是真正的内层 POSIX tar、外层 xz，默认探测已安装 7-Zip 的标准 LZMA2；若现有 7z-FLZMA2 没有 xz 输出能力，则回退到便携 Python 已有的标准 LZMA2，不下载新工具。同时验证内外层及 SHA256。已有归档和完整性报告均不覆盖。省略 `-SkipArchive` 可生成本地候选归档；独立调用也可使用新路径。

Base 解压到选择的应用根目录，根下直接出现 `Umi-OCR.exe` 和 `UmiOCR-data/`。CUDA tar.xz 解压到同一应用根目录，直接覆盖到 `UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/`，没有额外产品目录前缀。CUDA 的许可证与对应源码材料放在 `LICENSES/plugins/win32_PaddleOCRv6_CUDA/`，保留主程序根目录的许可证、版本与源码记录。图形归档工具需解开 xz 和 tar 两层；Windows `tar.exe -xf archive.tar.xz -C <应用根目录>` 可一次完成。

## 验证

prepare 与 `-SkipArchive` 不代表 public-release 或当前源码 E2E 已通过，旧 R2 的 hash/PASS 也不是本轮证据。按已批准的本轮范围对实际组装目录执行 `Test-Release.ps1 -StagingRoot $complete -Kind combined -Device gpu:0`，另行记录热 GUI、真实 Windows 托盘/退出前 HTTP 就绪、正常退出、GPU 原始回执、源码/模型及人工限制。GPU 正式门禁须绑定实际 CUDA overlay，不以独立 GPU staging 代替。

先固定本轮实际 base/GPU overlay 的 source/payload 并交审；明确同意后才更新 main/tag。标签匹配后运行 fresh 正式 source/运行门禁，再受限 finalize、生成正式归档、全新重装复验与发布。不能在公开标签匹配前预填正式 PASS；`LocalCandidate` 仅是开发候选路径，不能替代本轮正式流程。

该入口覆盖首屏懒加载与后台预热复用、Qt/QML D3D11 和图像多边形/鼠标锚点缩放、图片解码、UVDoc、截图/批量/PDF、二维码、HTTP/CLI、便携设置、HDR shader、DPI 坐标和自动截图捕获。CUDA 缺失测试会隔离 Paddle GPU wheel或请求不存在的 `gpu:N`，并验证 OCR 明确失败且未出现 CPU fallback。不要在正式 staging 中安装 CPU Paddle wheel来模拟失败。

自动截图捕获不等同于人工选区和 HDR 观感验收。发布前还必须按 [HDR 截图测试与校准](https://github.com/Dominic485649/UMI-OCR/blob/v3.0.1/docs/HDR_TEST_WINDOWS.md) 完成人工步骤。

若当前桌面内容不应由自动测试读取，构建时可传 `-SkipScreenshotCapture`；它只跳过自动全屏捕获，其他回归、干净构建、包审计和归档仍执行。必须由人工截图验收补足该项。

## Qt 裁剪

`Build-Release.ps1` 调用 `qmlimportscanner` 扫描仓库 QML，并结合 `build/qt-runtime-whitelist.json` 保留实际需要的 QML 模块、插件、Python 扩展和递归 DLL 依赖。修改 QML import、Qt 插件或 PySide6 扩展后必须执行干净构建；复用已裁剪 staging 不能证明新模块完整。

## 许可证与对应源码

本 fork 的新增和修改部分以及含 PyMuPDF 的组合发行物按 AGPL-3.0-or-later 发布；原 MIT `LICENSE`、hiroi-sora 版权和署名保留。源码镜像使用同一公开源码选择器，包含未 tracked 的当前 required files，保留 GPL/AGPL/MPL 对应源码材料。实际 `source/`、`source-snapshot.zip`、成员哈希和 provenance 须与被冻结产品及公开 commit/tag 一致；`LocalCandidate` 的开发记录不替代正式来源门禁。

最终派生 `source-delivery.json`、`current-source-e2e.json` 和 `RELEASE_EVIDENCE.*` 保存在产物 `LICENSES/`，CUDA overlay 使用 `LICENSES/plugins/win32_PaddleOCRv6_CUDA/`。源码冻结后不得将这些新 PASS 回拷进 canonical source、修改镜像或重算快照冒充冻结源码内容；实际是否满足以当轮 fresh gate 为准，不宣称脚本接线已自动通过。见 [组合发行说明](../LICENSES/COMBINED_DISTRIBUTION.md)。

## 发布约束

基础包审计会拒绝旧 PP-OCR V2-V5、PP-OCRv6 small/tiny、CPU Paddle、ONNX Runtime、DirectML 和不属于基础 OCR 包的模型资产。Windows 7 不受支持，也不作兼容性声明。
