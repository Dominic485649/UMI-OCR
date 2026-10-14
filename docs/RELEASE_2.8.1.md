# Umi-OCR 2.8.1 本地候选验收

本次是本地候选，项目导航为 https://github.com/Dominic485649/UMI-OCR 。没有创建公开版本、推送仓库或发布 3.0.0。作者版权、许可证与第三方来源保留。

## 运行时选择

实际运行时为 Python 3.13.16、PySide6/Qt 6.11.2，imagecodecs 2026.8.16、zxing-cpp 3.1.1。基础闭包 15 项、GPU 闭包 73 项重新解析并锁定下载 SHA-256；PaddlePaddle GPU 3.3.1、PaddleOCR 3.7.0、PaddleX 3.7.2 和 CUDA 12.6 相关已验证组件保留。cuDNN 保留经过实际构建验证的 9.9.0.52；依赖解析的 9.5.1.17 元数据约束仍由现有构建流程显式处理，没有静默改变二进制版本。

Python 3.14.7 本次不作为交付运行时：Paddle 官方 Windows 支持列表仍为 3.9–3.13。Qt 与纯 Python 模块可分别评估，但这不能证明 Paddle 的 CP314 原生推理闭包兼容。见[官方要求](https://www.paddlepaddle.org.cn/documentation/docs/install/pip/windows-pip_en.html)。

## 已实现和验证

- CPU、CUDA、VL 依赖仅在私有推理进程加载；三插件同时启用，CPU 使用 ONNX Runtime CPUExecutionProvider，CPU 任务不会启动 VL/llama-server。
- QML 动态值在共同边界转换，包括对象、数组、URL、文件夹及插件参数。版面模型目录 `D:/AI/models/PP-DocLayoutV3` 的保存、读取和真实推理通过。
- 移除应用修改按钮，已提交的有效设置自动保存和应用。任务队列通过同步边界保留旧配置完成当前工作，再切换并放行新任务。插件开关、安装刷新、语言、HTTP 地址/端口/开关即时应用。
- 推理和健康检查、预热放在后台；默认首次使用启动。切离 VL 时按预启动策略释放闲置自管服务，外部服务不停止。
- VL 只保留文字与真实位置的 Spotting 及完整文档解析两个能力，验证缩放坐标还原、文字叠加、阶段反馈、取消/超时/失败/空结果结束状态、区域失败保留成功内容和再次提交。
- 文档页设置面板、窄窗口布局、深浅主题、页签标题刷新和长路径显示修复；关闭页面释放预览文件。结果记录保存实际执行设备与模型快照，未知外部服务如实标记。
- 保存页面 key，兼容旧绝对 QML 路径，因此删除旧便携目录后仍能恢复原页签。
- Qt 的插件路径使用自身匹配运行时，实际 qwindows.dll、D3D11、HDR 截图与原生回退路径通过。

## 文件合并及性能门槛

主程序 `app.zip`、`dependencies.zip` 和 VL 兼容模块的私有 `vendor.zip` 使用 Stored ZIP，带匹配 3.13 的预编译字节码和原始 Python 源码；界面使用可直接读取的 RCC。逐项校验迁移源码/资源 SHA-256，ZIP 校验 CRC，原始包初始化代码保留在 `__original__/`。DLL、PYD、模型、依赖元数据和必须使用磁盘路径的包保持独立文件。没有解压启动器。

CPU 交替复测中两轮初始化超过 5% 门槛（初始化中位数回退约 14%），已恢复全部独立 vendor 文件。CUDA 私有 vendor 合并两轮出现可重复超过 5% 的耗时回退，已整体恢复独立文件。VL 全量合并出现文字定位回退，选择性恢复 openai、paddleocr、paddlex 后交替三轮复测通过门槛。实际计时与文件数记录在随包 `performance-summary.json`，原始验收输出在主仓库 `build/audit/`。

7z/Zstd 适合传输归档，本交付为可直接运行目录。Python ZIP 导入支持 PY/PYC，不支持从归档直接加载 PYD；无需为减少文件数强行拼接原生 DLL。见[Python zipimport](https://docs.python.org/3.13/library/zipimport.html)、[Qt RCC](https://doc.qt.io/qtforpython-6/overviews/qtcore-resources.html)。

## 计时方法与可复现边界

Windows 本机串行测量旧包、未合并候选、最终合并方案；每项三轮。UI 时钟从测试程序启动开始，记录首个已交换帧和事件循环可用时间；内存为 Windows Working Set。CPU/GPU 各三次识别，预热后耗时统计每轮后两次。VL 每轮启动一个新服务并顺序执行两种能力，确认复用同一 PID。工作进程/服务分别读取系统 PeakWorkingSet，显存采样为整个 GPU，包含桌面与其他应用，不能当作模型独占显存。没有清空操作系统缓存，“首次”表示三轮中的第一次，后续计时不能代表重启系统后的冷启动。

旧 CPU 在宿主内推理且模块在停止后保留；新版每轮建立并释放独立进程，因此旧版后两轮重新加载速度不可作为新工作进程启动时间的同口径比较。CPU 旧独立调用在这个测试配置中可运行，原 GUI 的问题与插件互斥及共享依赖加载顺序相关；没有把测试工具最初的接口不兼容误记为应用故障。

复制采用本机同盘 robocopy `/E /COPY:DAT /R:0 /W:0 /MT:16 /NFL /NDL /NJH /NJS /NP`，不清空缓存。其结果是当前机器数据，不能保证所有磁盘或杀毒配置下相同比例。

## 重建与交付

PowerShell 7 中运行 `build/tools/source_snapshot.py` 生成当前源码、锁、测试和构建脚本 ZIP 及逐文件 SHA-256。基础包通过 `build/windows/Build-Release.ps1 -StagingRoot build/staging/281-base-final -OutputRoot build/artifacts/281-products -SkipTests -SkipArchive -LocalCandidate` 从当前源重新编译启动器和 HDR DLL，重新安装哈希锁定的基础依赖。`Assemble-Candidate.ps1` 从此基础包、同一轮已构建并真实验收的三份私有依赖闭包，复制冻结的当前适配器源码，一次性生成完整新候选；不向旧 release 逐文件打补丁。

CPU 闭包入口是插件仓库 `Build-CpuPlugin.ps1`，CUDA 是主仓库 `Build-GpuPlugin.ps1`，VL 是插件仓库 `Build-Plugin.ps1`。依赖闭包输入、模型来源及许可证由各构建脚本和随包锁记录；本机外部 llama-server、GGUF/mmproj、PP-DocLayoutV3 不纳入交付。合并入口是 `build/tools/merge_runtime.py`，VL 必须带 `--keep-package openai --keep-package paddlex --keep-package paddleocr`，CPU、CUDA 不进行模块合并。

完整程序附全部三个插件；独立 CPU/CUDA/VL 产品在主仓库 release，CPU/VL 同份在插件仓库 release，并比对逐文件哈希。迁移原用户设置、预配置、主题和插件启用状态，保留明确预启动策略。旧 release 产品只在候选验收后删除；源码、外部模型与无关文件不删除。

## 实测结果

| 指标 | 旧版 | 未合并 2.8.1 | 最终 2.8.1 |
| --- | ---: | ---: | ---: |
| 三轮中的首次 UI 可交互时间 | 6.01 秒 | 3.07 秒 | 1.93 秒 |
| 后续两轮 UI 可交互时间中位数 | 5.18 秒 | 2.25 秒 | 2.13 秒 |
| UI 空闲 Working Set 中位数 | 318.1 MB | 248.5 MB | 248.6 MB |
| 同盘完整目录复制 | 26.13 秒 | 23.79 秒 | 23.69 秒 |
| 静态交付文件数 | 31,078 | 31,127 | 26,484 |

最终目录相对未合并候选减少 4,643 个静态文件，约 14.92%；迁移的用户配置和运行后生成的缓存、日志不计入该数量。CPU、CUDA 保留独立依赖是性能门槛的回退结果，不为文件数牺牲初始化速度。

最终 CPU 实际 ONNX 识别预热后中位数 2.355 秒，工作进程峰值 Working Set 中位数 502.5 MB；CUDA 实际识别 0.106 秒、1552.6 MB。VL 文字与位置 4.071 秒，完整文档解析 7.859 秒；工作进程与自管服务各自峰值 Working Set 相加的中位数 3498.9 MB，该值不表示同一时刻的总峰值。不同测试时段负载会影响绝对值，是否回退依据交替配对测量及同份依赖文件恢复，不跨时段选择最优值作门槛判断。

完整回归覆盖 Qt/QML、Windows HDR 截图、图片导入、任务队列、实际 GPU 识别、两页可搜索 PDF、HTTP 与 CLI；真实 CPU、VL 两能力及区域失败保留成功结果另行通过。真实 QML 热切换覆盖三插件、语言、HTTP、目录选择、窄窗口和两种主题；文档预览由组件自身在销毁时释放，避免父页面访问已销毁的连接器。

用户设置迁移保留原来的 CPU 禁用状态、VL 选择和明确配置的预热策略，只重置旧进程 PID/创建时间标记。此前看到 llama-server 进程本身不能证明 CPU 任务调用 VL：预热与 OCR 引擎选择也会启动服务。新版任务记录保存实际执行后端；独立 CPU 测试及真实 QML CPU 路由验证未启动 VL。


## 2026-10-06 文字定位修正

修复 VL 小图定位整体缩小并向左上角偏移的问题：PaddleX 的 Spotting 后处理已按原始区域尺寸将 0–1000 归一化坐标换算为像素，插件不再重复乘以 0.5。保留官方小图放大预处理及真实多边形，不修改模型与置信度。

记录中的 VL 模型名称简化为 `Paddlevl1.6`，不再附带 GGUF 文件名。真实 GPU 识别验证 960×380 和 1920×760 图片的三行文字框与已知原图位置相符；真实 QML 验证 50%、100%、104% 缩放下的文字框映射，并保存叠加画面。运行时依赖、启动器和用户配置保持本轮已验证版本，重新生成完整候选及独立插件，校验后替换同名 2.8.1 交付目录。
