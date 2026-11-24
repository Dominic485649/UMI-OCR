# 深度审查：完整发现与反证附录

基线 `876a3a2332bb311fc568d8db4765278cde3a0bcf`；以下位置指该基线，不是修复后行号。
六维审查原始92条候选：85条独立静态确认、6条未证实、1条工程建议；静态确认不等于运行复现。三组反证按领域分工，不是每条三票。
合并重复：PM-001→LIFE-003、HI-04→LIFE-004、UI-CONFIG-06→LIFE-013；89个原始独立条目。后续主线程发现和本轮质量复核另列，不能把不同阶段的数量混算成已复现bug总数。

已修复的条目仍保留原断言。源码回归、原生窗口与包内验证各自独立；最终状态以交付记录为准。

## delivery-docs

### 覆盖

- 以 commit 876a3a2332bb311fc568d8db4765278cde3a0bcf 为基线，只读审查 build/windows 的构建、审计、冻结、归档、恢复入口，以及 build/tools 的 prepare/package/merge/reinstall/source/verify 调用链。
- 检查 tests/test_minimal_distribution.py、tests/test_finalize_release.py、tests/test_local_build_tools.py、tests/test_review_archive_install.py 的现有正反例，但没有执行测试。
- 核对 README.md、README_en.md、README_ja.md、SOURCE-CODE.md，以及当前文档导航、构建说明、使用指南、CLI/HTTP 手册和 3.1.3 草稿。
- 定向核对 LICENSES/COMBINED_DISTRIBUTION.md、LICENSES/THIRD_PARTY_NOTICES.md、QtWebEngine 来源清单；没有全读历史原始证据。
- 只读取固定安装 PaddleVL 的公开清单，核对独立版本、Host API 和下载资源声明；未读取模型、用户配置、用户文档、私有解锁实现或兄弟项目。审查结束时正式脚本及所审文档相对基线没有变化。

### DD-01 · P1 · CUDA 对应源码导出遗漏现有构建入口必需的相邻模块

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`build/tools/export_cuda_source.py:15`
- 触发与影响：从当前导出器生成独立 CUDA 源码后，使用其中的正式构建或验证入口，验证器在启动阶段就会因缺少相邻模块失败；默认最简分包也缺少它调用的工具。
- 依据：TOOLS 白名单没有 release313_directed_evidence.py 和 prepare_minimal_distribution.py。build/tools/release_gate_inputs.py:26-28 无条件加载前者，build/tools/verify_release_evidence.py:23-27 又无条件加载 release_gate_inputs。build/windows/Build-GpuPlugin.ps1:507 直接调用后者。最简工具另外依赖两个 local-review 打包模块，当前导出也不包含它们。
- 原始反证：原工作仓库中这些模块齐全，因此在工作仓库运行和检查导出清单中的旧必需文件会掩盖问题。源码快照/Git 字节一致只能证明导出结果一致，不能补齐调用闭包。
- 独立核验：独立 CUDA 导出遗漏了同步导入和默认构建调用必需的工具，导出的验证/构建入口确实不自包含。工作仓库中运行成功和现有旧清单测试不能证明导出闭包完整。
- 修复方向：补齐独立 CUDA 源码的实际工具依赖闭包，并对导出结果而非工作仓库做隔离的入口导入/工具存在性检查。
- 原始验证范围：仅静态审查。最小安全验证是在项目具名临时根导出合成源码材料，隔离工作仓库后加载导出的验证模块；无需构建原生程序、加载模型或联网。

### DD-02 · P2 · 依赖复用入口不能复用本项目生成的 Stored 布局

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`build/windows/Build-Release.ps1:238`
- 触发与影响：将已验收的 Stored 暂存作为 -ReuseFromStagingRoot，再做离线新构建。原种子的 bottle.py、six.py 已在 dependencies.zip 中，但新构建只复制 runtime 和 site-packages，丢失这两个依赖。CUDA 的相同操作也丢失 vendor.zip 中的依赖。
- 依据：本体复用分支只复制两个目录（238-245）；build/windows/runtime_archives_host.json:6 明确把 bottle.py/six.py 移入数据根的 dependencies.zip。build/windows/Build-GpuPlugin.ps1:278-283 同样只复制 vendor，而 build/windows/runtime_archives_cuda.json:5 把 anyio、httpx、idna 等移入插件根 vendor.zip。新源码复制不会恢复这些第三方依赖。
- 原始反证：loose 种子不受影响；正常运行原 Stored 种子也不受影响。开启测试可能在后续发现缺失，但现有复用预检接受 Stored 种子，且文档没有限制只允许 loose。
- 独立核验：Stored 种子会通过现有目录预检，但仅复制散文件目录会遗漏移到组件根容器中的依赖。后续测试或审计可能阻止交付，不能据此称已生成或已发布可运行的缺依赖包。
- 修复方向：识别并验证种子的布局，完整复用其依赖容器及匹配声明，或在复制前明确拒绝不支持的 Stored 种子；不能仅检查原目录仍存在。
- 原始验证范围：仅静态审查。用含合成模块与 dist-info 的微型 loose/Stored 种子对比复制后的逻辑依赖集合即可，不需要实际 OCR、下载或完整构建。

### DD-03 · P2 · 源码对应性检查漏掉运行 QML/JS 文件的缺失

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`build/tools/finalize_release.py:283`
- 触发与影响：冻结前丢失一个运行 QML 文件，例如配置项基类；canonical source 和源码 ZIP 仍完整。该函数只检查实际存在文件的摘要，并只对 Python 执行集合相等检查，因此缺失 QML 可以通过 freeze 的源码对应性检查。
- 依据：263-286 收集 .py/.qml/.js，但 283 只遍历 actual，285 只比较 .py 集合。基线 UmiOCR-data/qt_res/qml/Configs/Configs.qml:802 等直接使用 ConfigItemComp；build/windows/Audit-Package.ps1 的必需文件表未覆盖该基类。现有对应性测试仅删除 Python，QML 反例只修改内容。
- 原始反证：字节被修改的 QML 会被拒绝，列入结构白名单的 QML 也会被检查；3.1.3 精确运行摘要还会阻断已审载荷的变化。因此这不是已证实绕过本轮全部批准门禁，而是通用 freeze 的完整性缺口。
- 独立核验：冻结前删除未列入结构必需表的 QML/JS，仍可通过通用运行源码对应性检查；对剩余文件验摘要不能发现缺项。本轮3.1.3另有精确载荷批准绑定，不能将此扩大成全部发布门禁已被绕过。
- 修复方向：对受检查的运行源码类型同时核对文件集合与摘要；有意不分发的资源应有显式、可审查的排除规则。
- 原始验证范围：仅静态审查。使用现有合成 finalize fixture 增加一个 QML/JS，再仅删除运行副本，验证 freeze 必须拒绝；不要启动实际界面。

### DD-04 · P2 · 默认最简构建没有传递正式归档必需的源码位置

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`build/windows/Build-Release.ps1:445`
- 触发与影响：通过正式构建入口选择默认 minimal，并提供有效的当次发布门禁。入口生成的分包清单 sourceUrl 恒为 null，随后正式 finalizer 必然拒绝该清单。
- 依据：445 的 prepare 调用没有 --source-url，参数表也没有对应输入。build/windows/Build-GpuPlugin.ps1:507 相同。build/tools/prepare_minimal_distribution.py:129、203 默认记录空 sourceUrl，而 build/tools/finalize_release.py:433-438 要求非空。
- 原始反证：这是正确的 fail-closed，不会把未声明源码位置的包公开放行；底层 prepare CLI 支持 --source-url。但是两个正式构建入口无法传入，也不能靠提供 ReleaseGates 补上该字段。
- 独立核验：正式构建入口没有对应源码位置输入，默认最简记录的 sourceUrl 必为空，无法通过正式 finalizer。这里是正确 fail-closed 上游缺参数，不是未经源码门禁公开放行。
- 修复方向：在正式构建入口显式接入匹配源码位置，并在生成 SOURCE 指引、清单和批准摘要前固定该输入；保留候选与正式发布的区别。
- 原始验证范围：仅静态审查。用微型分包 fixture 检查入口生成的参数和记录，再验证合法源码位置能到达 finalizer、空值仍被拒绝，无需公开发布。

### DD-05 · P2 · 首次最简构建没有创建默认分包清单的父目录

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`build/windows/Build-Release.ps1:443`
- 触发与影响：在干净检出中采用 -SkipTests -SkipArchive 准备默认最简本体。此前没有生成审计目录，入口直接把新清单放进不存在的父目录，准备阶段失败。
- 依据：443 默认选择 build/audit 下的新文件，445 随即调用 prepare；该函数在 build/tools/prepare_minimal_distribution.py:131 要求 report.parent 已存在。两个构建入口均没有创建该默认父目录，基线也没有跟踪该目录中的文件；CUDA 初始化存在相同顺序。
- 原始反证：当前长期使用的工作区已有审计目录，因此不会显现；显式指定已有父目录也可规避。后续 freeze 会创建审计父目录，但它在 minimal prepare 之后，无法修复该顺序。
- 独立核验：在没有历史 audit 目录、无 ReleaseGates 的准备构建中，默认分包记录父目录确实可能尚不存在，导致最简准备失败。正式构建要求的已有 ReleaseGates会隐含已有 audit 目录，但不能反驳候选明确的 SkipArchive 准备场景。
- 修复方向：在默认路径经过边界/链接检查后创建本次所需父目录，再排他创建清单；不要依赖旧构建留下的目录。
- 原始验证范围：仅静态审查。使用全新合成项目树、已有完整输入但没有审计目录，检查准备入口的目录建立顺序即可；不运行正式构建。

### DD-06 · P2 · 干净本体构建留下的 pip 引导位置与 CUDA 构建要求不同

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`build/windows/Build-Release.ps1:217`
- 触发与影响：没有历史 pip-bootstrap 缓存时，先完成本体构建，再按 CUDA 入口提示进行首次依赖安装。CUDA 会报告 pip bootstrap 缺失，即使刚运行过完整本体构建。
- 依据：217-221 在缓存不存在时改为暂存目录内的 .build/pip-bootstrap，436 又删除整个 .build。build/windows/Build-GpuPlugin.ps1:265-267 只接受缓存根 pip-bootstrap，并错误提示先运行完整 Build-Release。
- 原始反证：预先准备过缓存或使用 -ReuseDependencies 可以绕过；本体自身的 pip 安装可以成功。问题是文档化的首次本体→CUDA 链没有产生 CUDA 所需输入。
- 独立核验：首次本体构建不会留下 CUDA 所要求的缓存根 pip bootstrap，CUDA 的错误提示所给恢复步骤因此无效。已预先填好缓存或复用 vendor 的情况不受影响。
- 修复方向：统一经过锁定校验的引导来源，或让 CUDA 在自己的新构建工作区从锁定 pip wheel 建立引导；更新错误提示，不依赖已删除的本体中间产物。
- 原始验证范围：仅静态审查。以合成缓存布局核对两个入口选择的引导路径及生命周期；无需安装依赖或下载 pip。

### DD-07 · P2 · 重装工具仍强制要求最简插件已经移出的许可元数据目录

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`build/tools/reinstall_review_archives.py:180`
- 触发与影响：把三份新最简运行归档交给现有重装工具：新 package-record 会先因旧 schema 校验被拒绝；即使用旧打包器生成可接受记录，装配插件时仍会因不存在外置 LICENSES 命名空间而失败。
- 依据：147-149 只接受旧 local-nonfinal-review-artifact 协议。180-189 对每个插件同时要求运行目录和 LICENSES/plugins 目录存在并重命名；build/tools/prepare_minimal_distribution.py:154-193 将必要许可放在插件运行根，生成的最简包本来就没有该顶层元数据目录。
- 原始反证：safe_extract 的逐文件核对本身适用于最简包；旧完整覆盖层仍可重装。缺陷位于记录协议和组合装配，不表示当前固定安装一定损坏。
- 独立核验：该重装入口既不接受新最简打包记录，也不能装配不含顶层 LICENSES 元数据的最简插件。旧完整归档仍可使用，不据此推断当前固定安装损坏。
- 修复方向：接入最简打包记录，按已绑定运行清单装配；完整布局的外置许可目录只能按实际布局处理，不能要求运行归档重新携带已移出的材料。
- 原始验证范围：仅静态审查。用三个微型最简 tar.xz 和合成记录覆盖整个 install 函数，而非只测试 safe_extract；不运行应用或模型。

### DD-08 · P2 · Python 归档验证未读至 XZ 流结束，可能漏过损坏尾部

- 证据等级：UNVERIFIED；待验证风险，不作已证实缺陷
- 基线位置：`build/tools/package_tar_xz.py:119`
- 触发与影响：小 tar 的文件成员均完整，但 XZ 尾部索引/校验或 footer 被截断、损坏。tar 遇到结束块即停止，解压流尚有未消费数据时便关闭，当前路径可能返回完整性结果而未触发尾部校验。
- 依据：119-121 只调用 tar.getmembers，没有将外层 lzma 流排空至 EOF。142-157 在没有 sevenzip 参数时不做其它完整 XZ 检查。build/tools/finalize_release.py:530 的 ExistingArchive 路径和快打包器都这样调用；后续逐 tar 成员比对也不验证未消费的压缩尾部。
- 原始反证：显式运行 7z t 的分支有完整校验；分卷恢复还会校验预期整包摘要。这里针对没有外部校验器的归档登记/标准库验证，不声称已交付包实际损坏。
- 独立核验：已确认标准库验证没有显式读到 XZ EOF，但尚未证实候选所说的小 tar 尾部损坏一定逃过当前解释器的预读/解压校验。不能仅凭缺少 drain 就把具体损坏反例标成已确认。
- 修复方向：保持有界流式读取并验证完整 XZ EOF/尾部，再做 tar 成员及摘要检查；不要仅把 tar 可枚举等同完整压缩流通过。
- 原始验证范围：仅静态审查，尚未做缓冲行为复现。最小安全验证是自建单文件微型 tar.xz，只截断/翻转尾部，对比 verify_archive 与完整流解压；不读取或修改真实归档。

### DD-09 · P2 · 独立对应源码归档仍依赖未交付的 Git 工作树元数据才能构建

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`build/tools/source_snapshot.py:65`
- 触发与影响：接收者只下载对应源码归档，在独立目录解压并运行其构建入口。源码包没有 Git 元数据，但运行源码复制和来源导出要求 git ls-files、rev-parse HEAD，因而不能直接从该交付物复现构建。
- 依据：65-67 的文件枚举以及155-168的来源记录强依赖 Git。build/windows/Build-Release.ps1:287 和 build/windows/Build-GpuPlugin.ps1:288 无条件调用源码镜像；build/tools/export_cuda_source.py 明确不交付 Git 历史。分开的对应源码 package 也没有建立 Gitless 枚举入口。
- 原始反证：克隆公开源码标签的用户有 Git 元数据，可以走此路径。这里限定只取得独立对应源码归档的接收者；不是要求把整个 Git 历史塞入源码包。
- 独立核验：只取得独立源码材料、且解压位置不在任何 Git 工作树中的接收者，无法直接执行现有构建入口。确认的是独立材料的构建可用性限制，不是要求交付完整 Git 历史或认定许可违规。
- 修复方向：提供基于已交付冻结清单的 Gitless 构建路径和来源记录，或明确、完整地交付归档恢复后的构建步骤；不要静默借用上级无关仓库。
- 原始验证范围：仅静态审查。将合成源码材料放在没有上级 Git 仓库的项目临时根，定向检查文件枚举/镜像行为即可，无需执行应用或编译。

### DD-10 · P2 · 默认正式构建仍会主动执行真实桌面截图测试

- 证据等级：IMPROVEMENT；工程建议，不计缺陷
- 基线位置：`build/windows/Test-Release.ps1:89`
- 触发与影响：按当前构建说明调用本体构建而未额外指定跳过开关，会自动进入真实截图采集，与当前文档和停止继续截图测试的边界不一致。
- 依据：build/windows/Build-Release.ps1:376-381 默认执行 Test-Release，SkipScreenshotCapture 默认关闭。89-90 因而调用 tests/test_screenshot_capture.py；该文件28、55、69行实际采集全部屏幕并测试重复/降级路径，不是纯静态检查。
- 原始反证：-SkipTests 或 -SkipScreenshotCapture 可阻止真实采集，3.1.3 的批准验证也保留 NOT_RUN。本次审查没有执行该路径；问题是正式入口的默认行为没有体现已声明边界。
- 独立核验：默认捕获开关确实是 opt-out，值得改成安全默认；但原候选称当前正常完整构建会到达真实截图，漏掉了 EN-06 的更早必败阻断。不能把这条现存调用分支直接当成本轮已可达或已发生的采集缺陷。
- 修复方向：让当前默认构建明确跳过真实捕获并记录 NOT_RUN，将纯静态/几何检查与 live capture 分离；不得为修复该问题自行补做截图验收。
- 原始验证范围：仅静态审查。通过参数和调用分支检查验证默认不会触发真实采集即可，不建议执行任何截图/HDR/混屏复现。

### DD-11 · P2 · 正式新归档仍把多 GB 中间产物放到系统临时卷

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`build/tools/package_tar_xz.py:190`
- 触发与影响：项目和输出在空间充足的 D 盘，但系统临时目录所在卷空间不足。正式 finalizer 新建归档会在系统临时卷同时生成完整 tar 与压缩副本，可能失败或耗尽该卷空间，而不是使用已经建立的项目工作根。
- 依据：190 的 TemporaryDirectory 未传 dir，208-217 在其中建立完整 payload.tar 和 payload.tar.xz。build/tools/finalize_release.py:516 虽建立项目内工作区，530 调用的 create_archive 默认仍走该内部全局临时路径。
- 原始反证：streaming=True 的本地打包路径没有中间 tar，ExistingArchive 也不重新压缩；显式设置 TEMP 可规避。但正式新归档入口没有传递这种策略。
- 独立核验：未显式重定向 TEMP 的正式新归档路径会在系统临时根生成完整 tar 和压缩副本；项目卷有空间不能保证系统临时卷有空间。确认的是路径/容量故障条件，不是已发生磁盘耗尽。
- 修复方向：正式归档复用已有流式接口，或显式传入本次项目具名临时根并按实际卷做容量预检；保留失败证据，避免默认消耗用户系统临时卷。
- 原始验证范围：仅静态审查。用微型输入记录临时路径，或 mock 容量与临时目录选择即可；不生成大归档、不填满磁盘。

### DD-12 · P2 · 允许源码归档任意改名，但包内源码指引仍写死旧名称

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`build/tools/prepare_minimal_distribution.py:244`
- 触发与影响：合法调用 package 时把 --source-output 指向不同名称的新 tar.xz。操作会成功，但运行包 SOURCE.txt 仍声称源码是 prepare 阶段生成的另一个固定文件名，接收者按指引找不到实际交付附件。
- 依据：188-192 提前写定 correspondingSourceArchiveName；242-269 接受任意 source_output，未要求名称与该记录一致，也未重新生成指引。278-307 的 CLI 没有声明必须同名。现有测试只使用记录中的预期名称，未覆盖不同名称。
- 原始反证：调用者严格沿用记录名称时没有问题；返回的打包结果记录了真实源码路径。但该记录在包外，不能自动修正已冻结进运行包的获取指引。
- 独立核验：源码输出可合法使用另一个 basename，但运行包中已绑定的 SOURCE.txt 不随之变化，产生错误的附件名称指引。包外结果记录真实路径不能修正包内文字。
- 修复方向：在打包前强制校验源码产物名称与已绑定指引一致，或在冻结前把实际名称/位置作为显式输入生成指引并重新批准对应摘要。
- 原始验证范围：仅静态审查。复用微型分包 fixture，传入不同 basename 的 source-output，检查必须拒绝或指引一致；无需联网。

### DD-13 · P3 · 构建文档把 CUDA 最简目录和 SkipArchive 行为写成本体行为

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`docs/BUILD_WINDOWS_CUDA.md:21`
- 触发与影响：按文档寻找 CUDA 默认的 StagingRoot-runtime，或以 -SkipArchive 准备最简 CUDA 供审查，会找不到承诺的运行目录。
- 依据：文档18-25对两个入口统一声明默认目录和准备行为。build/windows/Build-GpuPlugin.ps1:503 实际使用 OverlayRoot-runtime；95、496 使没有显式 OverlayRoot 的 -SkipArchive 根本不进入最简准备分支。英文说明也给出相同的统一默认目录。
- 原始反证：CUDA 代码注释明确有意延迟多 GB 覆盖层复制以节省空间，这个设计本身合理；问题是当前说明没有告知该例外和所需参数。
- 独立核验：文档确实把本体默认运行根和 SkipArchive 准备行为泛化到了 CUDA。CUDA 延迟复制覆盖层是明确设计，不应作为代码缺陷；错误在未写明例外及参数条件。
- 修复方向：分开列明本体与 CUDA 的暂存、覆盖层、最简目录默认值，并说明 -SkipArchive 配合显式 OverlayRoot 的行为。
- 原始验证范围：仅静态审查。对照参数分支和路径字符串即可，不运行构建。

### DD-14 · P3 · 当前 HTTP 手册仍宣称慢请求会阻塞后续全部请求

- 证据等级：CONFIRMED_STATIC；本轮已修复，定向证据另存
- 基线位置：`docs/http/README.md:23`
- 触发与影响：集成方根据标注适用于最新版本的手册，把状态查询/取消请求也串行排在慢 OCR 之后，误以为服务无法并发响应，失去新版允许的任务控制方式。
- 依据：23 明写 WSGI 同步处理、慢 OCR/文档阻塞后续请求。UmiOCR-data/py_src/server/web_server.py:127-162 已采用 ThreadingMixIn 和16连接信号量，注释明确防止同步 OCR 等待阻塞查询/取消。
- 原始反证：重型推理仍由队列限制，不能据 HTTP 多线程推导模型并发；手册的避免重复提交提醒仍有效。应纠正的是连接并发与推理串行的混淆。
- 独立核验：对目标基线876a3a23成立：手册将 HTTP 连接并发与重型推理排队混淆。但当前未提交工作树已经删除这句并改为16连接的有限线程说明，因此不是工作树中仍待重复修复的问题。
- 修复方向：明确区分有界 HTTP 并发、推理排队和连接超限503，保留非幂等请求不要盲目重试的警告。
- 原始验证范围：仅静态审查。直接对照服务器适配器和手册即可，无需启动服务。

### DD-15 · P3 · 当前 CLI 手册错误地把识别模型限定为 PP-OCRv6

- 证据等级：CONFIRMED_STATIC；本轮已修复，定向证据另存
- 基线位置：`docs/README_CLI.md:91`
- 触发与影响：用户在全局模型设置中选择 PaddleVL，再用 --path 调用 OCR，手册却承诺执行模型固定为 PP-OCRv6，导致对后端、模型需求和资源行为的判断错误。
- 依据：91 明写模型固定。UmiOCR-data/py_src/server/cmd_server.py:246-252 把路径调用送到 ScreenshotOCR；全局模型由 UmiOCR-data/qt_res/qml/ApiManager/OcrManager.qml:92-102、248-279 选择注册后端，UmiOCR-data/py_src/mission/mission_ocr.py:157-181 接受注册能力而非硬编码 PP-OCRv6。
- 原始反证：只安装 CUDA 时确实只有该内置模型；不提供 CUDA 识别语言包设置也仍成立。但当前入口已经允许多个 OCR 后端，不能把单插件限制写成 CLI 固定规则。
- 独立核验：对目标基线876a3a23成立：CLI 并未固定使用 PP-OCRv6。当前未提交手册已改为任务参数来自截图页、后端来自全局设置，并分别描述 CUDA/PaddleVL，因此不应再次当作当前残留缺陷修改。
- 修复方向：说明 CLI 继承当前全局 OCR 后端和对应任务参数，将 PP-OCRv6 预设/语言包限制限定到 CUDA 插件。
- 原始验证范围：仅静态审查。沿现有路径调用和后端配置链核对即可，不执行截图、CLI OCR 或模型。

### DD-16 · P3 · CUDA 导出把 docs README 原样移到根目录，破坏相对链接

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`build/tools/export_cuda_source.py:106`
- 触发与影响：接收者打开导出的独立 CUDA 源码根 README，点击构建、插件 API 或源码交付链接，会解析到错误层级或未导出的文档。
- 依据：106-110 逐字节复制 docs/README_CUDA_PLUGIN.md 到导出根 README。原文13行的 ../SOURCE-CODE.md、32行的 BUILD_WINDOWS_CUDA.md/PLUGIN_API.md 按 docs 层级书写；移动后前者越到导出根外，后两者不再指向导出 docs。该 README 还链接了未列入 DOCS 白名单的 MODEL_DOWNLOADS/HISTORY。
- 原始反证：原 docs 目录中的文件路径语义正确，外部 Releases URL 不受影响。缺陷只发生在独立导出根的入口及导出文档集合。
- 独立核验：导出根 README 的相对路径未随位置变化，且部分目标根本没有导出，离线入口链接确定失效。原 docs 层级的链接和外部 Releases URL不受同一位置问题影响。
- 修复方向：生成适合根目录的 README 或重写相对链接，并只链接实际包含的文档；给导出结果增加离线相对路径检查。
- 原始验证范围：仅静态审查。对合成导出树解析 Markdown 本地链接即可，不请求外部网站。

### DD-17 · P3 · 当前第三方声明中的 Qt 法律文件数量与绑定清单不符

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`LICENSES/THIRD_PARTY_NOTICES.md:17`
- 触发与影响：审查者按当前声明核对 QtWebEngine 法律材料，会把旧筛选结果的2170项误当成当前已绑定集合；当前清单实际只有2068条 noticeFiles 记录。
- 依据：16-18 写明2170项。LICENSES/QtWebEngine/manifest.json 使用 legal-file-names-v3-locked-legal-wrappers，定向计数得到2068个 path 字段，均属于 noticeFiles；当前 QtWebEngine README 已描述新筛选策略。
- 原始反证：数量不一致本身不证明缺失许可；新筛选明确排除了非法律源码，并精确保留特殊法律正文。本次没有把差额直接认定为许可违规。
- 独立核验：当前声明的2170与当前绑定清单的2068确实不一致，属于事实性文案过期。数量差异不能推导缺失许可证或再分发违规。
- 修复方向：从当前绑定清单生成数量，或去掉容易陈旧的硬编码计数；不要改写历史原始记录。
- 原始验证范围：仅静态审查，已通过定向内容计数确认文本差异；无需解包、重建或重新下载 Qt 源码。

## engineering-native

### 覆盖

- 基线确认为 876a3a2332bb311fc568d8db4765278cde3a0bcf，分支 audit/ui-docs-3.1.4。本代理仅作静态读取，没有修改文件或运行测试。
- 完整阅读原生启动器 build/windows/CudaWorker/worker_main.cpp、build/windows/PyStand/PyStand.cpp、build/windows/PyStand/PyStand.h 及其 CMakeLists.txt、资源和 manifest；另静态核对 build/windows/HdrCapture/CMakeLists.txt。现有基线分别为 C++17、C++17、C++20，没有提出升标要求。
- 检查 UmiOCR-data/main.py、UmiOCR-data/runtime_archive_bootstrap.py 和 CUDA 插件的公开 bootstrap、worker、api、config、manifest，并沿取消/任务调用链核对现有防护。
- 阅读 benchmarks 下六个 tracked Python 基准入口；检查版本/依赖适配、子进程测量、隔离与配置恢复边界。
- 枚举 tests 的 tracked 清单并作定向检索，重点阅读启动、UTF-8、CUDA 原生入口/协议、运行容器、构建输入、预览资源和原生验收测试；没有把历史日期目录或固定随机种子本身认定为缺陷。
- 核对直接相关的 build/windows/Test-Release.ps1、build/windows/Build-Release.ps1、build/windows/Trim-Qt.ps1、build/qt-runtime-whitelist.json，以及 build/tools 的启动配置、源码快照和构建输入记录实现。

### EN-01 · P2 · CUDA 请求的超时不覆盖管道写入，取消也可能卡在同一管道

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/api.py:112`
- 触发与影响：worker 保持存活但停止读取 stdin 时，发送超过管道容量的合法图片请求会阻塞在 write，任务时间预算不会生效；并发取消也可能等待同一写锁或满管道，无法到达五秒后的 kill 分支。
- 依据：request() 同步执行 stdin.write()/flush() 后才进入 responses.get(timeout=wait)。stop() 又先写入 stop 行，之后才执行有界 wait()/kill()。Api.runBytes()/runBase64() 可达这个路径，Api.cancel() 直接调用 stop()。
- 原始反证：已有请求串行锁、EOF 响应、队列等待超时和自有进程 kill 回退；这些措施都没有给同步写入设置期限，不能解除本场景。正常读取 stdin 的 worker 不受影响。
- 独立核验：在 worker 已启动、仍存活但不再读取 stdin 的故障条件下，大图片请求的写入没有期限；取消也必须先向同一管道写入，不能保证进入 kill 分支。此结论不适用于正常读取协议的 worker。
- 修复方向：将写入纳入同一单调时钟 deadline，并使取消能绕过阻塞的 stdin 写入直接回收本实例 worker；回收后再有界收尾 writer/reader。补充“worker 存活但不读 stdin”的协议故障用例。
- 原始验证范围：仅静态审查，未启动 worker。最小安全复现建议为自有临时目录中的无模型假 worker：确认 start 后停止读 stdin，发送小于图片预算但大于管道容量的数据，验证请求与取消均在有限时间返回。

### EN-02 · P2 · PyStand 未检查定长路径 API 的失败及缓冲区不足

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`build/windows/PyStand/PyStand.cpp:120`
- 触发与影响：从超过传入容量的工作目录启动，GetCurrentDirectoryW 返回所需长度而非有效路径，随后 _cwd = path 会消费无效缓冲内容；可执行路径或展开后的 runtime 路径过长时则可能使用截断/旧内容，定位到错误目录并启动失败。
- 依据：CheckEnviron() 使用未初始化的 wchar_t path[MAX_PATH + 10]，不检查 GetCurrentDirectoryW、GetModuleFileNameW、GetFullPathNameW 的返回值就构造字符串；LoadPython() 对当前目录读取也采用相同模式。
- 原始反证：普通短路径及中文路径可正常走通，CUDA 启动器已经采用动态扩容获取模块路径；但 UTF-16、UTF-8 测试和文件存在性检查不替代这些长度/失败检查。
- 独立核验：路径 API 失败或返回所需容量时仍消费缓冲区，属于实际错误处理缺陷，不是 UTF 编码或代码风格问题。不能断言每个长路径都必然崩溃，但不足容量时未初始化/旧缓冲内容进入字符串的链成立。
- 修复方向：在现有 C++17 下使用动态缓冲并逐个检查返回值；缓冲不足时扩容，真实失败时携带 GetLastError 明确退出，不继续使用缓冲内容。可以复用 CUDA 启动器的路径获取模式。
- 原始验证范围：仅静态审查，未编译或运行启动器。最小验证建议为模型无关的原生路径 API 夹具，分别模拟返回 0、返回所需长度大于容量、成功长路径；不得用真实用户安装作故障夹具。

### EN-03 · P2 · 容器校验失败后，错误处理还依赖尚未挂载的 app.zip

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/main.py:202`
- 触发与影响：Stored 安装的 app.zip 缺失、大小/哈希不匹配或声明损坏时，prepare_archives 先抛异常；由于 app.zip 尚未挂载且没有散文件 py_src，错误处理再次抛 ModuleNotFoundError，原始诊断和 MessageBox 都到不了。GUI 无控制台启动时表现为无提示退出。
- 依据：initRuntimeEnvironment() 在 prepare_archives() 成功返回后才把容器路径加入 sys.path；外层 except 却立即从 py_src.imports.umi_log 导入 logger，然后才调用独立的 MessageBox()。宿主容器策略将整个 py_src 放在 app.zip 中。
- 原始反证：运行容器确实失败关闭，没有回退加载损坏文件，这是正确防护；散文件源码模式下 logger 通常可导入。问题限定于需要容器提供日志模块的早期失败路径。
- 独立核验：清洁 Stored 安装的容器校验早期失败时，异常处理确实再次依赖尚未挂载的应用日志模块，因而到不了最后防线 MessageBox。拒绝损坏容器本身是正确保护，不应为修复提示而绕过校验。
- 修复方向：让 bootstrap 的最后防线只依赖磁盘上的 main.py 与标准库；logger 导入/初始化失败也必须保留原始异常并调用 MessageBox 或独立日志回退，不能为报错而挂载未通过校验的容器。
- 原始验证范围：仅静态审查，未改动或启动安装。最小安全验证建议为合成入口夹具：stub prepare_archives 抛出校验错误，同时禁止 py_src 导入，断言仍能得到原始错误提示和非零退出。

### EN-04 · P2 · 被捕获的启动异常以成功退出码返回给原生调用者

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/main.py:211`
- 触发与影响：容器挂载成功后发生普通启动异常，例如 Qt 导入失败或正式 main() 抛异常，日志/错误框可以正常显示，但关闭错误框后 Umi-OCR.exe 返回 0，外部脚本和只检查退出码的启动诊断会把失败当成功。
- 依据：初始化失败分支和正式入口异常分支分别在 211、230 行调用 sys.exit(0)；build/windows/PyStand/PyStand.cpp 的 RunString()/WinMain 将 Py_Main 的结果原样返回。
- 原始反证：原生入口对缺 Python、缺启动脚本等错误返回非零，未捕获的 SystemExit 也不走这两个 except。部分现有验收另查窗口/阶段，所以不会全部误报；这些不能修正 EXE 本身的退出契约。
- 独立核验：在日志模块可用的启动失败路径中，捕获到普通异常、显示错误框后仍返回成功退出码。它与 EN-03 不重复：EN-03可能提前逃出异常处理，本条限定错误处理能够完整执行的情况。
- 修复方向：两个异常处理分支均返回明确非零状态；正常 CLI 操作和正常退出继续保留 0，并增加入口退出码回归。
- 原始验证范围：仅静态审查，未执行应用。最小安全验证建议为无 Qt、无模型的入口夹具，注入初始化异常及正式 main 异常并替换 MessageBox，检查 SystemExit.code 非零。

### EN-05 · P2 · 旧验收入口仍可直接改写正在运行的固定安装配置

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`tests/test_http_cli.py:187`
- 触发与影响：将参数指向已经运行的 release/Umi-OCR，会在原实例仍使用该目录时替换配置并启动第二实例。原实例并发保存的设置可能被最后的旧快照覆盖；异常时还会强制结束新启动的程序。
- 依据：该入口仅 resolve() 参数路径，就备份并 clear()/改写 .settings、覆盖 .pre_settings、以 --force 启动；finally 按旧快照恢复，未限制 build 副本或预查占用。benchmarks/benchmark_startup_ui.py 的 _preserve_portable_state/_clean_portable_state 和 tests/test_windows_tray.py 有同类可达路径。
- 原始反证：finally 的恢复能处理单实例、无并发修改的正常情形，但不是占用检查。新的 benchmarks/benchmark_startup_isolated.py 和 tests/test_release312_native.py 已有副本/占用限制，旧入口没有调用它们。
- 独立核验：旧工具接受任意安装路径，确实可在原实例运行期间覆盖设置并最终恢复旧快照，从而丢失期间保存的设置。风险属于显式调用这些验收工具，不是生产应用会自行运行这些测试。
- 修复方向：让所有会修改配置或启动程序的旧入口复用现有副本所有权、路径和占用门禁，拒绝固定安装与已有用户状态；若仅保留历史工具，应明确停用执行入口，而非继续接受任意安装路径。
- 原始验证范围：仅静态审查，未读取用户配置或操作固定安装。最小安全验证建议为纯文件夹具加假占用查询：传入非 build 根、已占用根或带状态根时，在任何配置读取/写入和 Popen 之前拒绝。

### EN-06 · P2 · 基础 Qt 回归仍禁止当前策略必需的 WebEngine DLL

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`tests/test_qt_runtime.py:101`
- 触发与影响：符合当前离线 Markdown 富预览依赖策略的正常基础包，运行基础回归会在此断言失败。Build-Release.ps1 未指定 SkipTests 时会调用这条回归链，因此合法闭包被旧的排除规则拒绝。
- 依据：这里断言 Qt6WebEngineCore.dll 不存在；build/qt-runtime-whitelist.json 已要求 QtWebEngineCore.pyd、QtWebEngineQuick.pyd、QtWebEngine QML 和 QtWebEngineProcess.exe。Trim-Qt 保留这些入口的 DLL 依赖；Test-Release.ps1 第 75 行仍调用该测试。
- 原始反证：当前定向构建包装器可显式 SkipTests，另有 Markdown 预览回归；这解释了为何新功能仍可能交付，但不能让正式基础回归的矛盾断言成立。其余禁止项不因此应被整体移除。
- 独立核验：当前合法 WebEngine 闭包与这条否定断言直接矛盾，正常基础回归会拒绝符合策略的包。SkipTests 只绕过测试，不消除矛盾。
- 修复方向：按当前白名单验证 WebEngine 必需闭包及有限资源，而不是保留旧版“无 WebEngine”断言；让白名单与回归共享可检查的契约，避免下一次依赖策略变化再次分叉。
- 原始验证范围：仅静态审查，未启动 Qt 或测试。最小验证建议先用合成白名单/文件集合覆盖包含必需 WebEngine 和缺失闭包两个分支；不涉及截图、HDR 或模型。

### EN-07 · P2 · 构建漂移记录没有覆盖实际编译的原生输入

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`build/tools/run_model_settings_build.py:24`
- 触发与影响：PyStand.cpp、PyStand.h 或原生 CMakeLists 在构建期间发生变化，包装器仍可能记录 sourceChangedDuringBuild=[]、buildPassed=true。尤其在编译后、对应源码镜像生成前变化时，交付源码与已编译 EXE 可以错位而不被这项漂移门禁发现。
- 依据：source_hashes('base') 不包含 build/windows/PyStand 或 HdrCapture；cuda 虽枚举 CudaWorker，但扩展名白名单不含 .txt，因此遗漏 CMakeLists.txt。该函数的 before/after 差异直接决定 buildPassed，Build-Release 则实际从这些目录编译原生目标。
- 原始反证：对应源码快照和产物哈希仍有价值，公开发布也还有独立门禁；但它们记录的是各自最终字节，不能证明遗漏的输入在编译期间未变化。这里不是断言已发生错误发布。
- 独立核验：实际编译输入可发生变化而不改变 before/after 哈希映射，导致本项漂移门禁仍报告 buildPassed。确认的是门禁覆盖缺口，不是已经发生源码/二进制错配或错误发布。
- 修复方向：把每个实际构建目标的源文件、头文件、CMakeLists、资源/manifest、图标和相关工具链输入纳入组件级绑定；更稳妥的是从冻结的受审源码副本编译，并增加输入枚举回归。
- 原始验证范围：仅静态审查，未构建。最小安全验证建议为合成仓库中的 source_hashes 单元测试，逐一改变 PyStand.cpp、PyStand.h 和 CudaWorker/CMakeLists.txt，确认差异被记录，无需运行编译器。

### EN-08 · P2 · 预览资源单测依赖未创建的历史工作目录

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`tests/test_preview_build_assets.py:44`
- 触发与影响：全新 clone 或未保留该历史构建目录的开发环境中，单独运行这个离线测试会在 TemporaryDirectory 创建阶段抛 FileNotFoundError，尚未验证任何镜像行为。
- 依据：test_data_and_corresponding_source_mirrors_retain_exact_browser_bytes() 将 dir 指向 build/tmp/release-312-20261102-r1，却没有在方法、setUp 或模块初始化中创建该目录。
- 原始反证：其他运行容器/预览相关测试通常会先 mkdir(parents=True)，而保留历史工作树的本机会掩盖本缺陷。问题是缺少夹具准备，不是日期字符串本身。
- 独立核验：单独运行该方法时，没有任何夹具负责创建指定父目录；全新检出会在 TemporaryDirectory 处失败，尚未测试镜像行为。保留历史目录的工作区会掩盖问题。
- 修复方向：在经校验的项目专属临时根下显式创建父目录，再使用唯一临时子目录；不要要求保留某次旧构建才能执行单测。
- 原始验证范围：仅静态审查，未创建目录或运行测试。最小安全验证建议在不预建该历史目录的合成仓库根中，仅运行这个方法；只应创建并清理其自有小型文件夹具。

### EN-09 · P2 · bootstrap 离线单测强制读取未声明的兄弟仓库

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`tests/test_runtime_archive_bootstrap.py:58`
- 触发与影响：只检出主程序仓库即可具备 host/CUDA 测试输入，但运行这个标为轻量离线的测试集仍会因旁边没有指定仓库而失败；若旁边存在不同独立版本，则比较的是未绑定的外部工作副本，结果不可复现。
- 依据：VL 常量固定指向 ROOT.parent/Umi-OCR-Plugin/win32_PaddleOCRVL_1_6/runtime_archive_bootstrap.py，test_component_helpers_stay_identical() 无参数或可用性检查就 read_bytes()。该兄弟仓库不是当前仓库的 tracked 输入。
- 原始反证：host/CUDA 的其余合成容器测试不需要 VL，源码快照也明确默认不读取兄弟项目；不能通过本机恰有该目录证明测试自包含。这里只指出依赖，没有读取兄弟仓库内容。
- 独立核验：普通离线测试集确实隐式依赖未声明的兄弟检出；没有该路径时必定失败，有该路径时比较的也是未绑定版本的工作副本。
- 修复方向：将跨组件同步检查分成显式接收并绑定插件源码路径的独立检查；普通 host/CUDA 单测保持自包含。未提供 VL 输入时将跨组件部分明确记为未执行，不把它当作已通过。
- 原始验证范围：仅静态审查，未访问兄弟项目或运行测试。最小安全验证建议在仅有当前仓库输入的合成目录中验证 host/CUDA 测试可运行，另用两份小型显式 helper 文件验证同步检查。

### EN-10 · P3 · 旧 OCR 基准依赖已经移除的进程内 API，当前入口无法运行

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`benchmarks/benchmark_ocr_pipeline.py:301`
- 触发与影响：对当前标准组合包运行此基准，宿主通常先在 import paddle 失败；即便使用 --paddle-override 满足该导入，后续两个已不存在的导出仍会导致 ImportError，无法产生当前架构的基准结果。
- 依据：该入口先 import paddle，随后从 CUDA api 导入 MODELS_DIR、从 config 导入 PRESETS，并遍历 speed/balanced/accuracy。当前 api 没有 MODELS_DIR，config 没有 PRESETS；插件 manifest 的宿主 vendor_dirs/dll_dirs 均为空，Paddle 只在 worker 中加载。
- 原始反证：这是独立旧基准，不是生产 OCR 必经路径；build/tools/benchmark_inference.py 已使用 worker 思路，因此不据此声称实际推理失效。
- 独立核验：旧基准的现存 CLI 入口与当前适配器导出契约不兼容；即使解决 Paddle 导入，仍会在后续导入中失败。此故障不影响生产 worker OCR 的可用性。
- 修复方向：停用并明确标记历史入口，或按当前单一 medium 配置和独立 worker 契约迁移；不要为了让旧脚本导入成功而恢复已移除的产品预设或把 Paddle 重新装进宿主。
- 原始验证范围：仅静态审查，未导入 Paddle、访问模型或执行基准。最小安全验证建议用 AST/模块导出夹具及假 Api 检查依赖契约和参数传递，不执行实际 GPU 推理。

## lifecycle

### 覆盖

- 基线已确认是 876a3a2332bb311fc568d8db4765278cde3a0bcf；结束前对照该提交确认以下核心审查文件没有工作区差异。
- 静态审查 UmiOCR-data/py_src/mission/ 下全部任务管理、共享执行许可、配置应用与预览调度实现；mission_queue.py 当前没有生产调用者，未把其孤立接口问题列为发现。
- 审查 UmiOCR-data/py_src/utils/thread_pool.py、UmiOCR-data/py_src/utils/doc_probe.py、UmiOCR-data/py_src/utils/_doc_probe_worker.py、UmiOCR-data/py_src/utils/file_finder.py 及连接器、主线程回调边界。
- 审查 UmiOCR-data/py_src/tag_pages/BatchOCR.py、UmiOCR-data/py_src/tag_pages/BatchDOC.py、UmiOCR-data/py_src/tag_pages/batch_runtime.py 的准备、提交、暂停、取消、保存及关闭状态机。
- 追踪 UmiOCR-data/qt_res/qml/Configs/GlobalConfigs.qml、UmiOCR-data/qt_res/qml/ApiManager/、UmiOCR-data/qt_res/qml/MainWindow/、两个批量页面及文档预览的直接调度链；退出入口为 UmiOCR-data/py_src/run.py。
- 为验证可达性，定向读取 UmiOCR-data/py_src/server/ 下后端选择、HTTP 文档父任务、同步 OCR 与常驻监听实现，以及 UmiOCR-data/py_src/ocr/output/ 下实际输出实现。
- 仅读取固定安装的公开插件源码和清单：release/Umi-OCR/UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/（清单版本 3.0.5）、release/Umi-OCR/UmiOCR-data/plugins/win32_PaddleOCRVL_1_6/（清单版本 3.1.3），用于核对取消、服务锁及子进程生命周期。
- 交叉阅读 tests/test_mission_runtime.py、tests/test_managed_mission.py、tests/test_backend_runtime.py、tests/test_backend_apply.py、tests/test_backend_apply_qml.py、tests/test_batch_runtime.py、tests/test_batch_shutdown.py、tests/test_batch_queue_qml.py、tests/test_doc_probe.py、tests/test_file_import.py、tests/test_ignore_area_qml.py、tests/test_document_partial_delivery.py、tests/test_structured_http.py 等现有断言；本次均未执行。

### LIFE-001 · P1 · 模型切换屏障与 HTTP 文档父预约形成死锁

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/mission/managed_mission.py:45`
- 触发与影响：通过 /api/doc/upload 接纳一份至少两页、需要 OCR 的文档，在第一页执行期间修改全局模型设置。后续页面的子 OCR 被延后，而父文档预约一直占用 busy；文档和模型切换会互相等待，所有新 GUI 模型任务也无法继续。
- 依据：UmiOCR-data/py_src/server/doc_server.py:129-152 为 HTTP 文档保存私有 OCR manager，并预约整个父文档；预约直到 :330-349 的父 onEnd 才释放。UmiOCR-data/py_src/mission/mission_doc.py:295-304 同步提交每页子 OCR。本处把这些子任务放入 deferred 队列；UmiOCR-data/qt_res/qml/Configs/GlobalConfigs.qml:779-812 则必须等父预约消失才能应用配置并恢复接纳。addMissionWait 没有超时可打破此环。
- 原始反证：已有完成谓词防丢失唤醒、全局接纳屏障和父任务资源预约；这些保护分别正确，但组合形成循环依赖。tests/test_managed_mission.py:165-176 只覆盖顶层任务延后，不覆盖已预约父任务继续提交子 OCR。显式清除 HTTP 文档可以解锁，不等于正常模型切换能自行完成。
- 独立核验：未找到能打破正常模型切换等待环的保护。完成谓词解决的是丢失唤醒，不解决子任务从未获准执行；显式清除 HTTP 文档可以解锁，但不是正常切换流程的一部分。
- 修复方向：给已接纳文档的子 OCR 传递可继承的父准入凭据，让它们在旧配置下排空；仅延后新的顶层任务。不要直接取消父预约，否则会引入文档中途切换后端的问题。
- 原始验证范围：仅静态审查，未执行。最小安全复现建议：用两页假文档、FakeApi 和页间屏障，保留父预约后启用 defer_admissions，再提交第二页；断言父 busy 与 deferred 子任务同时存在且无法自然结束，最后显式取消以完整回收线程。

### LIFE-002 · P1 · 有界全局线程池可被 DOC 同步等待自己的子 OCR 卡死

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/utils/thread_pool.py:31`
- 触发与影响：全局池只有两个工作槽且 HTTP 监听已启用时，启动一份需要 OCR 的普通批量文档：监听占一个槽，MissionDOC 占另一个槽并等待子 OCR，子 OCR runnable 却只能排队，任务永远没有进展。单槽池中不启用 HTTP 也能触发。
- 依据：UmiOCR-data/py_src/server/web_server.py:202、:215-219、:255-257 把 serve_forever 放进同一个全局池；UmiOCR-data/py_src/mission/mission_doc.py:303-304 在该池内调用 addMissionWait；子 Mission 又通过 UmiOCR-data/py_src/mission/mission.py:274-278 排入该池，而 :263-265 无期限等待。没有为这种依赖保留工作槽。
- 原始反证：取消无限扩线程、另设两个槽的 BatchIOPool 都是有效保护；但独立 I/O 池只承接准备和保存，没有承接 DOC 或 OCR 的父子执行链。tests/test_mission_runtime.py:59-68 只验证不扩容，没有验证受限池下的嵌套等待。
- 独立核验：在候选明确限定的池容量下成立，不代表已确认本机默认池只有两个槽。独立 BatchIOPool 隔离了准备和保存，却没有隔离 DOC 父任务与 OCR 子任务的同步依赖。
- 修复方向：将常驻 HTTP 监听移出任务池，并使 DOC→OCR 调度不在同一个有界池内阻塞等待，例如采用 continuation 或独立的推理执行器；不要恢复无界扩线程来掩盖依赖环。
- 原始验证范围：仅静态审查，未执行。最小安全复现建议：在独立测试进程把池限制为两个槽，用可释放的占位任务模拟监听，再运行假 DOC→假 OCR 链，断言 OCR 尚未进入；最后释放占位任务并等待所有 runnable 结束，不启动 HTTP 或模型。

### LIFE-003 · P1 · 共享模型状态轮询会把后台启动等待搬回 UI 线程

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/qt_res/qml/ApiManager/OcrManager.qml:354`
- 触发与影响：选择 PaddleVL 作为 OCR 后端并首次加载或预热模型，启动过程超过三秒。状态定时器在主线程同步查询服务状态，等待后台启动所持的锁，窗口、取消和退出操作会冻结到启动完成或超时，默认可接近 180 秒。
- 依据：本处同步调用 getServiceStatus；同文件 :501-505 的三秒定时器不因后台忙而停用。UmiOCR-data/py_src/plugins_controller/plugins_connector.py:172-176 直接进入服务 get_status。固定安装公开源码 release/Umi-OCR/UmiOCR-data/plugins/win32_PaddleOCRVL_1_6/runtime.py:159-189 在同一 RLock 内完成启动和 _waitReady，而 :64-65 的 get_status 也获取此锁。该插件清单 :219-223 确实给 OCR 声明了共享服务。
- 原始反证：模型预热和服务操作已经通过后台 requestOperation/requestCall 启动，问题不是没有后台线程，而是同步状态读取重新等待长锁。现有 QML 状态机测试把 getServiceStatus 替换为立即返回的桩，未覆盖这个阻塞链。
- 独立核验：后台启动并不能保护同步状态槽；状态轮询没有检查插件操作忙碌状态。启动持锁超过一次三秒轮询周期即可到达主线程等锁，等待持续到启动路径释放锁。PM-001 与此同源，应合并。
- 修复方向：让状态接口只读取短锁保护的缓存快照，把进程启动和健康等待移出状态锁；同时避免在 QML 定时器内同步调用可能等待插件锁的接口。
- 原始验证范围：仅静态审查，未执行。最小安全复现建议：用假的 _waitReady 在后台持锁并等待 Event，调用真实状态查询链验证其阻塞；增加主线程心跳断言，最后释放 Event。无需真实模型、服务端口或 GPU。
- 主线程补充：同PM-001，不把方法等待计时冒充真实模型加载时长

### LIFE-004 · P1 · 预览、文档识别和 PDF 输出仍在多个宿主线程调用 PyMuPDF

- 证据等级：UNVERIFIED；待验证风险，不作已证实缺陷
- 基线位置：`UmiOCR-data/py_src/tag_pages/batch_runtime.py:19`
- 触发与影响：两个批量文档页面同时准备 PDF 输出，或一个页面识别时另一个页面预览、准备或保存 PDF，会从不同宿主线程进入 PyMuPDF。官方明确不支持这种运行方式，存在整个应用原生崩溃或结果错误的风险。
- 依据：UmiOCR-data/py_src/tag_pages/BatchDOC.py:74-84 在线程池构造输出器，实际 fitz.open 位于 UmiOCR-data/py_src/ocr/output/output_pdf_layered.py:34-45；文档读取和输出 print 又在 Mission 工作者执行，onEnd 则回到独立 I/O 池。UmiOCR-data/py_src/mission/doc_preview_connector.py:57-108 另有独立预览工作者。未找到覆盖这些调用的进程级串行边界，且官方文档明确警告多线程可能使 Python 崩溃。
- 原始反证：元信息探测已隔离到子进程；Attempt.io_lock 和 OutputSession._lock 也能防止单个输出会话同时 print/finish。但它们不覆盖其他会话、Mission 文档操作和预览线程。已有真实 PDF 回归主要覆盖单份文档顺序执行，不能证明这一并发模式受支持。
- 独立核验：确认存在跨宿主线程的 PyMuPDF 使用边界，但尚不能把“可并发调用”直接等同于某个具体输入必然导致原生崩溃或错误结果。保留为原生线程安全风险，不升级为已确认的崩溃缺陷。
- 修复方向：将真实文档解析、渲染和 PDF 修改放入独立进程，保持文档对象在所属进程内；至少先统一所有宿主 fitz 调用的串行边界，不要只给单个输出器加锁。
- 原始验证范围：仅静态审查，未复现原生崩溃。最小安全验证建议：用带线程屏障的假 fitz 记录两份输出准备及预览/识别调用的线程身份，证明当前能够交叠；不要为了证明风险而并发操作用户 PDF。

### LIFE-005 · P2 · 退出钩子没有关闭普通任务接纳并排空所有活动管理器

- 证据等级：UNVERIFIED；待验证风险，不作已证实缺陷
- 基线位置：`UmiOCR-data/py_src/run.py:188`
- 触发与影响：HTTP 私有 OCR/文档任务或结构化文档任务仍在运行时退出应用。退出钩子只关闭批量页面并丢弃两个全局 API 句柄，没有先取消这些任务、停止 HTTP 接纳或等待全部执行许可，因此退出后继续推理、长时间等待及子进程残留的边界没有收住。
- 依据：本处只调用 mission.shutdown；UmiOCR-data/py_src/mission/backend_runtime.py:476-481 的 ManagedApi.stop 仅移除当前句柄，:236-240 在任何任务忙时跳过真实清理。UmiOCR-data/py_src/server/backend_router.py:77-83 为正常 HTTP 请求创建私有 manager。随后 PluginServices.shutdownAll 也不检查返回的忙碌结果；固定安装公开源码 release/Umi-OCR/UmiOCR-data/plugins/win32_PaddleOCRVL_1_6/runtime.py:270-280 在活动租约下拒绝停止，atexit 使用的仍是同一路径。
- 原始反证：批量页面已有先取消、等待活跃输出会话、派送终态回调及 30 秒期限，这是有效保护；忙时不强行释放服务同样正确。缺口是非批量任务没有统一退出协议。tests/test_batch_shutdown.py 仅用桩断言调用顺序，没有活动租约或私有 manager 的退出断言。
- 独立核验：静态确认退出钩子缺少非批量任务的统一取消、停止接纳和排空协议；但“最终退出后必然残留子进程”或实际退出等待时长尚未闭合证明。HTTP 还存在稍后的 atexit 停止，后端在许可释放后也会尝试清理，因此不能直接将钩子缺项等同于最终孤儿进程。
- 修复方向：退出时先关闭 HTTP/新任务入口，统一取消所有已登记管理器及非 Mission 工作者，再在明确期限内等待任务、取消动作和输出收尾，最后释放后端；服务返回 busy 时应继续受控收尾或显式报未完成，而非忽略。
- 原始验证范围：仅静态审查，未执行应用退出。最小安全复现建议：以 FakeApi、活动租约和私有 manager 调用抽取出的真实 shutdownBackends，验证取消未被调用、任务在钩子返回后仍活跃；验证修复时再断言全部完成，不创建真实子进程。

### LIFE-006 · P2 · 停止普通文档不会取消它正在等待的子 OCR 队列

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/mission/mission_doc.py:304`
- 触发与影响：批量文档正在 OCR 一页中的多张图片时点击停止或关闭页面。父文档立即显示停止，但子 OCR 队列仍逐项推理；父 DOC 工作者和输出会话要等整页全部 OCR 返回才能结束，后续文档、后端切换和退出收尾都可能被拖住数分钟。
- 依据：本处调用 addMissionWait，没有保存子任务 ID 或传递父取消谓词。_MissionDocClass 继承普通 Mission，UmiOCR-data/py_src/mission/mission.py:130-131 的默认 _cancelExecutions 不做任何事；UmiOCR-data/py_src/tag_pages/batch_runtime.py:665-668 停止时只停止父 MissionDOC。子 OCR 的 stop 状态独立，父 state=stop 不会改变它。
- 原始反证：父任务返回后会再次检查 stop，旧结果不会回写新批次，输出会话也受到跟踪，因此这不是旧结果污染问题。HTTP 清理路径 UmiOCR-data/py_src/server/doc_server.py:293-298 已另行停止私有 OCR manager；GUI 普通文档没有对应动作，现有批量桩测试也不执行真实父子链。
- 独立核验：父任务的停止状态没有传给子 OCR，子队列也没有可供父任务定向取消的身份。旧结果过滤与输出会话跟踪能防污染，却不能缩短已无用途的整页子 OCR 执行。
- 修复方向：让同步子任务支持返回/保存任务身份与取消谓词，停止父文档时只取消其所属的子 OCR 队列，并等待取消收尾；不能用全局 stopAllMissions 误伤其他页面。
- 原始验证范围：仅静态审查，未执行。最小安全复现建议：用一页含多个假图像任务的文档，在首个假 OCR 屏障处停止父 DOC，断言剩余子任务当前仍会执行；最后释放屏障，确认父 onEnd 与输出器各收尾一次。

### LIFE-007 · P2 · GUI 普通文档未纳入整份任务的模型切换排空判断

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/tag_pages/BatchDOC.py:117`
- 触发与影响：一份多页 GUI 批量文档处理到页间、提取或输出阶段时修改识别模型。此时子 OCR 队列可能已经为空，配置立即应用，后续页面会使用新后端，却继续携带该文档旧的参数快照；一份输出可混用两个模型。
- 依据：本处提交 MissionDOC 时没有冻结 ocrManager，也没有整文档预约；UmiOCR-data/py_src/mission/mission_doc.py:303 每页都重新使用全局 MissionOCR。UmiOCR-data/qt_res/qml/Configs/GlobalConfigs.qml:788-794 的排空判断只查询 Managed OCR/document，不查询普通 MissionDOC。因此父文档仍活跃时，页间空隙可以被视为空闲。
- 原始反证：已经进入 ManagedMission 的队列会持有预约，执行期间也受统一许可保护，所以不会在单次 OCR 推理中途换模型。HTTP 普通文档另外冻结了私有 OCR manager 并预约父任务；缺口只在 GUI 普通文档的跨页生命周期。
- 独立核验：跨页模型一致性缺口成立。现有许可和预约保护单次 OCR，不能保护未登记的普通 DOC 父生命周期；与 LIFE-001 有设计关联，但不是同一个触发结果。
- 修复方向：为 GUI 普通文档冻结后端及配置，并纳入整文档排空屏障；与 LIFE-001 一并设计可继承的子任务准入，避免简单补父预约后又造成延后死锁。
- 原始验证范围：仅静态审查，未执行。最小安全复现建议：用两个返回不同模型标记的 FakeApi，在第一页 onGet 后、第二页提交前设置屏障，执行配置应用，再检查同一文档两页的执行标记；不加载真实模型。

### LIFE-008 · P2 · 批量结算把部分识别结果计为完整成功并允许完成后动作

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/tag_pages/BatchDOC.py:148`
- 触发与影响：某页 OCR 只完成部分区域但仍返回 code=100、partial=true，或者混合模式保留原文而图片 OCR 失败。批次仍计成功并允许自动关机/休眠等完成后动作，尽管逐页结果已经明确不完整；批量图片也有相同判断。
- 依据：本处只根据 code 设置 pageError，:155-160 因而可把 partial 页结算成功。UmiOCR-data/py_src/mission/mission_doc.py:307-346 会真实产生这种 code=100、partial=true 的结果。UmiOCR-data/py_src/tag_pages/BatchOCR.py:198-200 同样只检查 code；UmiOCR-data/py_src/tag_pages/batch_runtime.py:900-901 没有不完整结果门禁。
- 原始反证：UmiOCR-data/qt_res/qml/Widgets/ResultLayout/ResultsTableView.qml:19-26、:67-69 已显示部分结果警告，不能说告警完全丢失。HTTP 普通文档终态也已检查 partial；tests/test_structured_http.py:252-270 只验证 MissionDOC 保留告警，未覆盖批量终态和完成后动作。
- 独立核验：确认的是批次结算及完成后动作门禁遗漏 partial，不是警告完全消失。提示性 warnings 不应自动视作失败，但明确 partial 的不完整结果不能按当前逻辑结算为纯成功。
- 修复方向：在图片和文档批次中独立累计 partial/未完成状态，保留已识别内容，但不得把它计为完整成功或允许无条件完成后动作；单纯提示性 warnings 与确实不完整的 partial 应分别处理。
- 原始验证范围：仅静态审查，未执行。最小安全复现建议：让批量测试桩返回 code=100、partial=true、有效文本和 warnings，断言结果仍保留，但批次不能给出纯成功终态，canPostTaskActions 必须为 false。

### LIFE-009 · P2 · 异步准备结束后仍在 Qt 主线程重新打开和验证文档

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/tag_pages/BatchDOC.py:124`
- 触发与影响：导入一个打开需修复或读取较慢的 PDF 后开始任务。尽管元信息探测和输出准备在后台完成，主线程仍会再次同步 fitz.open、认证及读取页数；耗时解析或文件在导入后变化时，窗口停止响应，取消和关闭也无法处理。
- 依据：_prepared 经主线程回调进入本方法，而 _submit 立即执行传入 lambda。UmiOCR-data/py_src/mission/mission_doc.py:83-103 在真正排队前同步打开、认证并访问 page_count，没有调用期限。这段不属于带 30 秒子进程期限的 doc_probe。
- 原始反证：后台文件扫描、隔离元信息探测以及输出器准备均已存在；这不是导入链整体同步。tests/test_batch_runtime.py:101-114 用立即返回的 FakeMission 验证主线程派发，真实文档用例则是很小的正常 PDF，未覆盖慢 admission。
- 独立核验：同步主线程 admission 路径成立，具体卡顿时长取决于文件和存储条件，未测量。后台导入探测及输出准备的隔离不能消除随后重新打开文档的同步 I/O。
- 修复方向：主线程仅提交不可变请求，把文档打开、认证、页范围校验及对象生命周期放到真正的文档执行器/隔离进程中，失败通过一次终态返回；不要把 native 文档对象在 UI 和工作线程之间转交。
- 原始验证范围：仅静态审查，未执行慢文档。最小安全验证建议：用可控阻塞的假 fitz.open 和主线程心跳，验证当前 admission 阻塞 UI；修复后应在后台等待且主线程仍能处理取消。

### LIFE-010 · P2 · GUI 停止动作同步等待 CUDA worker 的退出宽限期

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/mission/managed_mission.py:89`
- 触发与影响：CUDA worker 正在执行较长推理或初始化时，从批量页面点击停止。Qt 主线程直接进入后端 cancel，等待 worker 读取 stop 或五秒宽限期结束，整个界面会同步冻结，退出关闭页面也会经过这条链。
- 依据：UmiOCR-data/qt_res/qml/TabPages/BatchOCR/BatchOCR.qml:74 同步调用 msnStop；UmiOCR-data/py_src/mission/mission.py:158 随即同步执行本处取消。固定安装公开源码 release/Umi-OCR/UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/api.py:308-310 调用 _worker.stop，其 :125-139 发送 stop 后等待五秒才 kill。
- 原始反证：队列 stop 状态已先写入，取消令牌可防止误取消下一任务，执行许可也会等取消完成后才释放，这些保护都应保留。但 tests/test_managed_mission.py:285-322 将 stopper 放在另一个线程，未断言真实 GUI 调用不能被该等待阻塞。
- 独立核验：现有取消令牌和取消完成屏障是必要保护，但没有把阻塞取消移出 GUI 线程。候选所述长推理或初始化尚未返回时，worker 也不能读取后续 stop 消息。
- 修复方向：UI 线程先登记停止，再将可能阻塞的后端取消交给独立收尾执行器；继续用当前取消令牌和取消完成屏障保护许可交接，并把完成通知送回主线程。
- 原始验证范围：仅静态审查，未执行 worker。最小安全复现建议：用等待可释放 Event 的 FakeApi.cancel，从真实页面停止入口验证主线程心跳；不要为证明五秒等待而启动 GPU 推理。

### LIFE-011 · P2 · SimpleMission 的结束交接窗口仍会搁置最后一次预览

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/mission/simple_mission.py:54`
- 触发与影响：预览工作者刚看到空队列、尚未清空 _task 时，主线程提交下一次翻页请求。新请求看到旧 _task 非空而不启动工作者，旧工作者随后只清空 _task 就退出，最后一页预览会一直等待直到另一个请求到来。
- 依据：同文件 :42-46 在释放队列锁后退出循环，:32-35 用 _task 非空阻止新派发，而本处 :55-57 没有重新检查剩余队列。直接调用者为 UmiOCR-data/py_src/mission/doc_preview_connector.py:40-46。普通 Mission 已在 UmiOCR-data/py_src/mission/mission.py:435-444 修复同一交接窗口，SimpleMission 没有对应保护。
- 原始反证：replace=true 会删除旧 pending 预览，代次校验也会阻止旧图回写，但两者都不能唤醒一个已经没有工作者的新队列。现有预览竞争测试控制渲染完成或 Qt 交付次序，没有在 SimpleMission._taskFinish 边界提交请求。
- 独立核验：存在完整的丢调度时序：新提交必须发生在旧工作者观察空队列之后、旧任务槽清空之前。提交在该窗口以外通常正常，replace 和预览代次检查也不解决该窗口。
- 修复方向：在同一任务槽交接协议下清空 _task 并重新检查 pending，必要时重新派发；同时给 _taskRun 增加 finally，确保异常也能归还任务槽。
- 原始验证范围：仅静态审查，未执行。最小安全复现建议：在 _taskFinish 清空槽前加测试屏障，提交第二个普通函数任务，再释放屏障；无需 Qt 窗口或 PDF，即可断言第二个任务当前被搁置。

### LIFE-012 · P2 · 预览代次失效只屏蔽显示，没有取消过期 OCR 任务

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/mission/doc_preview_connector.py:155`
- 触发与影响：开启文档 OCR 预览后快速翻页、修改参数或关闭面板。旧页面的所有 OCR 仍在全局 MissionDOC 中顺序执行，当前预览必须排在它们后面，关闭面板后也继续占用识别资源；用户已经没有对应任务身份可取消。
- 依据：本处每次 addMission 都丢弃返回 ID；:40-46、:139-145、:169-177 只增加修订号或替换渲染请求，没有停止旧 MissionDOC。UmiOCR-data/py_src/tag_pages/BatchOCR.py:272-289 的图片预览也只覆盖 _preview_id，关闭时只能停止最后一个 ID。
- 原始反证：实际交付前的修订号检查和深拷贝正确地阻止了陈旧结果污染 UI；现有 tests/test_ignore_area_qml.py:256-324 对此有明确断言。问题在于被隐藏的工作仍执行，该测试的 addMission 桩不核查旧任务取消。
- 独立核验：确认过期工作继续执行，不确认陈旧结果污染；后者已受到有效代次保护。真实文档预览翻页按钮在 OCR 运行期间仍可触发，因此不是仅可从内部 API 构造的场景。
- 修复方向：按预览会话保存当前任务 ID，在替换、换页、clear 和关闭时取消所属旧队列，并维持修订号保护；普通文档预览还需配合 LIFE-006 取消其子 OCR，而不是清空全局其他任务。
- 原始验证范围：仅静态审查，未执行。最小安全复现建议：让假 MissionDOC 记录 add/stop，连续请求两页再 clear，断言旧任务和当前任务均收到且仅收到所属取消；用屏障保证旧任务尚未完成。

### LIFE-013 · P2 · 文档 OCR 预览失败后加载状态没有结算

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/qt_res/qml/TabPages/BatchDOC/PreviewDoc.qml:173`
- 触发与影响：当前预览 OCR 返回后端不可用、页处理失败或其他非 100/101 结果时，错误框出现后加载图标仍无限显示。若文件在导入后被移除或密码变化导致提交立即失败，则连错误终态也不会收到。
- 依据：toPreview 在同文件 :143-145 把 ocrRunning 设为 true；本处错误分支在 :175 提前 return，只有 :181 的成功分支才清 false，:432-434 的 Loading 因而一直可见。另一路径 UmiOCR-data/py_src/mission/doc_preview_connector.py:154-155 忽略 addMission 返回的立即错误，而该错误发生在入队前，不会触发 onEnd。
- 原始反证：关闭面板、重新 show 或关闭 OCR 开关会重置加载状态，且连接器能过滤过期错误；它们不是当前请求失败的正常终态。已有连接器测试确认当前错误能交付，但没有验证该真实 QML 的 ocrRunning 会复位，也没有覆盖立即拒绝。
- 独立核验：当前请求的错误与提交拒绝均存在不结算分支。关闭或重新显示面板会复位，但并不构成失败请求的正常终态；连接器过滤旧请求不能解决当前请求的 loading 状态。
- 修复方向：将当前请求的成功、失败、取消和提交拒绝统一结算；先核对请求身份，再清除 ocrRunning，随后展示错误或结果。连接器应把 addMission 的立即错误转换成一次失败通知。
- 原始验证范围：仅静态审查，未执行。最小安全复现建议：对真实 QML 注入当前请求的 code=103 失败事件，断言 ocrRunning=false；再令 addMission 桩立即返回 [Error]，断言只产生一次失败通知，无需 OCR 后端。

## ui-config

### 覆盖

- 审查基线为 876a3a2332bb311fc568d8db4765278cde3a0bcf。UmiOCR-data/qt_res/qml/Configs/Configs.qml、UmiOCR-data/qt_res/qml/TabPages/PagesManager.qml、导航及全局设置页存在主线程并行改动，相关审查使用 git 中的基线内容，不将其改版视为回归。
- 覆盖 UmiOCR-data/qt_res/qml 下的页面注册、标签管理、全局和任务配置、批量任务、结果表、图片及文档预览、通用按钮、表格、弹窗、主题和语言尺寸逻辑，并追踪至 UmiOCR-data/py_src 中的对应 Python 桥接。
- 读取 tests 中配置枚举、折叠、模型设置、批量队列、结果序列、忽略区域、文档预览和 UI 门控相关测试源码；未执行这些测试，也不将测试中的 PASS 文案视为本轮验证结果。
- 以下发现均为旧基线遗留问题或明确输入条件下的风险，尚未实施修复；导航工作台和全局设置侧栏的改版建议另列，不替代缺陷修复。

### UI-CONFIG-01 · P2 · 批量图片预览按文件名取得最早历史，可能展示其他图片或旧批次结果

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/qt_res/qml/TabPages/BatchOCR/BatchOCR.qml:176`
- 触发与影响：依次识别 A/page.png、B/page.png 后点击 B，或对同一路径重新识别后再次预览，图片来自当前行，文字和文字框却可能来自第一条同名历史。
- 依据：onOcrGet 将标题设为 res.fileName；onClickPath 只用 path2name(info.path) 调用 getResult。UmiOCR-data/qt_res/qml/Widgets/ResultLayout/ResultsTableView.qml:113-119 从头返回首个同标题记录。Python 已在 UmiOCR-data/py_src/tag_pages/BatchOCR.py:178 保留完整 path，但查询未使用。
- 原始反证：文件队列表以完整路径区分行，且 PreviewImage.show 确实加载点击行的图片；这些防护没有保证叠加数据属于同一路径和最近一次任务。
- 独立核验：预览把展示文件名当身份键，并返回最早匹配记录，无法隔离路径或重识别批次。
- 修复方向：按完整路径及任务身份绑定结果，预览查询最近有效结果；不要把展示标题当作记录主键。
- 原始验证范围：仅静态审查。建议使用内存结果和图片加载替身，加入两个同名不同路径结果及同路径第二批结果，核对传给预览的 source.path 和正文；无需模型或截图。

### UI-CONFIG-02 · P2 · 历史自动淘汰首行后，选区索引会指向另一条记录

- 证据等级：CONFIRMED_STATIC；本轮已修复，定向证据另存
- 基线位置：`UmiOCR-data/qt_res/qml/Widgets/ResultLayout/ResultsTableView.qml:101`
- 触发与影响：历史达到上限时选中最后一条记录，后台再追加一条结果并淘汰首行；随后复制或删除选中记录，会操作新结果而不是仍显示选区的原记录。
- 依据：101-104 行直接 remove(0)，没有平移或清空 tableMouseArea.startIndex/endIndex。351-380 行复制和 404-409 行删除继续使用旧索引；选区角色则随原模型行移动，形成显示与操作对象不一致。
- 原始反证：selectDel 和 selectAllDel 会清理交互索引，但自动历史裁剪没有走这些路径。默认 200 条及 32 MiB 限制使该分支能在正常连续识别中发生。
- 独立核验：自动裁剪改变模型索引，却未改变鼠标保存的选区索引，后续操作对象会错位。
- 修复方向：裁剪时同步修正或清空选区，最好用稳定记录 ID 保存交互身份。
- 原始验证范围：仅静态审查。建议把 historyLimit 设为 2，添加 A/B、选中 B、追加 C，分别检查复制和删除仍作用于 B；只需内存 QML 组件。
- 主线程补充：裁剪选区误移受控QML复现

### UI-CONFIG-03 · P2 · 原生键盘选区与自定义复制索引不同步，Ctrl+C 会复制错误范围

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/qt_res/qml/Widgets/ResultLayout/ResultTextContainer.qml:163`
- 触发与影响：在结果正文点击放置光标，再用 Shift+方向键选择几个字符，按 Ctrl+C；实际可能复制整条记录，而不是屏幕上选中的字符。
- 依据：UmiOCR-data/qt_res/qml/Widgets/TextEdit_.qml:13 允许原生键盘选区，但本文件拦截 Ctrl+C 并调用表级 copy。UmiOCR-data/qt_res/qml/Widgets/ResultLayout/ResultsTableView.qml:351-355 只查看鼠标维护的索引，等位置时会改为整块选择。未发现原生 selectionStart/selectionEnd 到这些索引的同步。
- 原始反证：鼠标跨记录选取和自定义 Ctrl+A 路径会主动设置表级索引；问题是原生键盘选择、光标移动或编辑后的路径。
- 独立核验：原生键盘选区没有同步到表级选区，Ctrl+C 会走陈旧鼠标索引。
- 修复方向：区分原生单框选区与跨记录选区，复制时读取实际 TextEdit 选区，或完整同步键盘选区变化。
- 原始验证范围：仅静态审查。建议用合成按键在真实结果委托中执行点击、Shift+Right、Ctrl+C，并以剪贴板替身检查精确字符；不捕获桌面。

### UI-CONFIG-04 · P2 · 手动删除记录没有扣减历史字节预算，后续结果会被过早淘汰

- 证据等级：CONFIRMED_STATIC；本轮已修复，定向证据另存
- 基线位置：`UmiOCR-data/qt_res/qml/Widgets/ResultLayout/ResultsTableView.qml:408`
- 触发与影响：手动删除若干大结果后继续识别，已经不存在的记录仍占用 historyBytes，后续结果会提前被移除；若删除过单条超预算记录，历史甚至可能长期只保留一条。
- 依据：addOcrResult 按 source.length*2 累加预算，自动删除会扣减，selectAllDel 会归零；selectDel 只调用 resultsModel.remove，没有扣减对应 source 字节。
- 原始反证：清空全部记录及自动淘汰路径已经维护计数，因此不是预算设计本身的问题，而是手动删除路径遗漏。
- 独立核验：手动删除不扣除历史字节，后续裁剪使用的是包含已删除记录的累计值。
- 修复方向：所有删除入口共用维护模型、选区和预算的函数，删除前扣减实际记录字节。
- 原始验证范围：仅静态审查。建议添加两个小结果、手动删除一个，断言 historyBytes 等于剩余 source 长度之和；无需生成大文件。
- 主线程补充：手动删除预算未归还受控QML复现

### UI-CONFIG-05 · P2 · 插件页移除后保留旧 infoIndex，后续导航可能命中禁用页面

- 证据等级：CONFIRMED_STATIC；本轮已修复，定向证据另存
- 基线位置：`UmiOCR-data/qt_res/qml/TabPages/PagesManager.qml:79`
- 触发与影响：插件页 A/B 分别位于信息列表 7/8，先后打开后禁用 A 并刷新；B 被重编号为 7，A 仍保留 7。从导航或按 key 打开 B 时可能返回禁用的 A。
- 依据：基线 registerPluginPages 对仍存在页面更新 infoIndex，但对移除页面仅设置 enabled=false。UmiOCR-data/qt_res/qml/TabView_/TabViewManager.qml:122-125、170-173 仍按 infoIndex 判断是否已有目标页。
- 原始反证：注册刷新已经按稳定 key 查找仍存在的页面，也会阻止创建不可用页面；但旧页面复用发生在创建前，且未排除已移除页面。
- 独立核验：插件页移除后留下旧 infoIndex，可与重新编号的有效页发生身份碰撞。
- 修复方向：页面复用统一比较稳定 key；移除页面应清除索引并标记不可复用，或明确关闭。此项属于旧基线缺陷，可纳入当前导航改版。
- 原始验证范围：仅静态审查。建议用两个无需控制器的内存插件页元信息，模拟移除 A 后打开 B，检查返回对象及 enabled；不涉及私有解锁或模型。

### UI-CONFIG-06 · P2 · 文档 OCR 预览收到错误终态后不复位加载状态

- 证据等级：CONFIRMED_STATIC；后续项；合并到 LIFE-013
- 基线位置：`UmiOCR-data/qt_res/qml/TabPages/BatchDOC/PreviewDoc.qml:173`
- 触发与影响：启用预览 OCR 后遇到后端初始化或识别错误，错误框出现，但右侧加载指示一直转动，直到手动关闭预览或再次操作。
- 依据：toPreview 在 143-145 行设置 ocrRunning=true；onPreviewOcr 对非 100/101 结果先弹错再 return，只有成功分支才在 181 行复位。UmiOCR-data/py_src/mission/doc_preview_connector.py:147-152 会为任务错误发送 code=103 的终态。
- 原始反证：成功、关闭预览和重新打开都会清理状态；连接器也有请求代次防护。遗漏的是当前请求的正常失败终态。
- 独立核验：当前预览 OCR 的失败终态会提前 return，未结算 ocrRunning。
- 修复方向：所有当前请求的终态都结算 ocrRunning，再分别处理错误和成功；保留对旧请求的拒绝。
- 原始验证范围：仅静态审查。建议在 PreviewDoc 替身连接器中发送当前路径、page=-1、code=103 的错误结果，断言加载状态结束且错误只提示一次。

### UI-CONFIG-07 · P2 · 文档预览桥接忽略同步任务拒绝，失败时没有任何 OCR 完成回调

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/mission/doc_preview_connector.py:155`
- 触发与影响：文档在导入后被移走、变为不可读、密码失效或任务接纳失败，用户开启 OCR 预览；addMission 同步返回错误后，界面等待的 previewOcr 永远不会收到。
- 依据：ocr 调用 MissionDOC.addMission 后丢弃返回值。UmiOCR-data/py_src/mission/mission_doc.py:87-96、111-127 在多种校验失败时直接返回错误字符串，不触发提供的 onEnd。
- 原始反证：连接器处理了已接纳任务的异步 onEnd 错误，并对旧代次结果做过滤；这些机制不覆盖任务尚未成功入队的返回路径。
- 独立核验：同步接纳失败的返回值被丢弃，不会产生调用者等待的终态。
- 修复方向：捕获同步拒绝和异常，转换为带当前请求身份的失败终态；不要只依赖异步回调。
- 原始验证范围：仅静态审查。建议把 MissionDOC.addMission 替换为返回受控错误的函数，断言发送一次 previewOcr 错误终态；无需读取文档或启动模型。

### UI-CONFIG-08 · P2 · 图片忽略区域 OCR 预览没有失败终态处理，会永久显示加载中

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/tag_pages/BatchOCR.py:277`
- 触发与影响：打开图片忽略区域预览时没有 OCR 后端或后端启动失败，任务只有 onEnd 没有 onGet，编辑器一直显示加载中。
- 依据：msnPreview 仅提供 onGet，没有 onEnd，也未处理 addMissionList 的错误返回。UmiOCR-data/qt_res/qml/Widgets/IgnoreArea/IgnoreArea.qml:39-45 设置 running=true，只有 getPreview 或关闭路径清理它。
- 原始反证：已有 token、generation 和页面关闭检查能拒绝旧成功结果，但不产生失败回调。无后端时 UmiOCR-data/py_src/mission/mission_ocr.py:67-72 会在预处理阶段结束队列而不返回单图结果。
- 独立核验：图片忽略区域 OCR 预览只有成功结果通道，启动失败或同步拒绝都可能不结束加载。
- 修复方向：为预览补全同步拒绝、异步错误和取消终态，统一结束加载状态并给出可操作错误。
- 原始验证范围：仅静态审查。建议用任务替身仅触发 onEnd('[Error] ...')，检查编辑器 running 复位；不执行 OCR。

### UI-CONFIG-09 · P2 · 通用布尔配置只能鼠标操作，键盘用户无法修改关键开关

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/qt_res/qml/Configs/Configs.qml:817`
- 触发与影响：只使用键盘进入全局或任务设置，无法将焦点移动到允许 HTTP、启动行为、输出文件类型等布尔开关并用空格切换。
- 依据：基线 compBoolean 的唯一交互是填满整行的 MouseArea；其 CheckBox_ 在 UmiOCR-data/qt_res/qml/Widgets/CheckBox_.qml:8 是纯 Rectangle。未声明键盘焦点、按键动作或可访问的可选中角色。
- 原始反证：工具栏上的 CheckButton 继承 Button，枚举也使用 ComboBox；这些控件的键盘能力不能覆盖此通用布尔配置实现。
- 独立核验：通用布尔设置没有可聚焦的键盘操作入口。
- 修复方向：使用 Switch/CheckDelegate 等标准可访问控件，或补齐 Tab 焦点、空格动作、名称及 checked 状态暴露。
- 原始验证范围：仅静态审查。建议用内存设置实例化两个布尔项，发送 Tab/Space 并检查规范值及可访问状态；不修改用户配置。

### UI-CONFIG-10 · P2 · 快速识图任务接纳失败时引用不存在的 self.msnID，丢失错误通知

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/tag_pages/ScreenshotOCR.py:79`
- 触发与影响：模型任务预约达到 64 个上限时，再通过粘贴或图片路径提交快速识图，addMissionList 返回队列已满；处理分支先抛 AttributeError，而不是报告失败并结算请求。
- 依据：_msn 的错误分支格式化 self.msnID，但该类只维护 msnDict，没有该属性。UmiOCR-data/py_src/mission/managed_mission.py:49-53 将预约失败转成错误返回，UmiOCR-data/py_src/mission/backend_runtime.py:55、163-166 定义 64 个预约及明确拒绝路径。
- 原始反证：异步任务失败通常由 _onEnd 正确通知；这里发生在同步接纳失败阶段，且错误字符串的实际变量是局部 msnID。
- 独立核验：同步接纳失败分支读取不存在的属性，先抛异常，未进入原本的结束通知。
- 修复方向：使用实际返回的错误变量，并确保未接纳任务同样触发一次完成通知和状态恢复。
- 原始验证范围：仅静态审查。建议把 MissionOCR.addMissionList 替换为返回队列已满错误，直接调用控制器提交方法并检查事件；无需填满真实队列，不涉及截图。

### UI-CONFIG-11 · P2 · 窄文件面板的列宽总和可超过视口，状态列没有可达的横向滚动

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/qt_res/qml/Widgets/FilesTableView.qml:269`
- 触发与影响：把批量任务左侧面板缩至约 160 像素，或在小窗口提高字号，文件名最小列宽加耗时、状态列超过视口，右侧状态及对应文档操作区域被裁掉。
- 依据：updateWidth 按文字宽度保留所有后续列，并将第一列下限设为 minWidth0；总宽度没有视口上限。TableView 在 375 行限制为 VerticalFlick，委托 implicitWidth 又固定为视口宽度，且只提供竖向滚动条。默认小行高 16 时，第一列下限已有 80 像素。
- 原始反证：单元格有 clip，第一列也会尝试缩窄；但第一列达到下限后仍可能溢出。双栏在大于 hideWidth=80 时不会自动隐藏，窗口最小宽度也只有 300。
- 独立核验：窄面板下列宽总量可以超出视口，组件没有可用的横向到达机制。
- 修复方向：明确窄视口降级策略：允许真正的横向内容宽度与滚动，或压缩/重排次要列并保留状态和操作入口。
- 原始验证范围：仅静态审查。建议用一行内存数据在 160 像素宽度和两档字号下比较各列边界与视口，检查状态列可见或可横向到达；无需文件或截图。

### UI-CONFIG-12 · P2 · 页面 createObject 失败仍会插入 null 页面，导致标签导航失效

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/qt_res/qml/TabPages/PagesManager.qml:164`
- 触发与影响：一个声明合法且编译就绪的插件 QML 因未满足 required 属性而无法实例化；用户打开后得到 obj=null 的页面条目，之后切换和关闭标签都会访问空对象。
- 依据：基线 newPage 在 createObject 后不检查 obj，仍返回 dic，addPage 因 dic 非 undefined 而插入。showPage:231-236 无条件访问 obj.z/visible，closePage:209 无条件调用 obj.closePage。
- 原始反证：getComp 已处理组件编译错误，控制器创建失败也会返回失败；这些防护不覆盖 Component.Ready 之后的对象实例化失败，已创建控制器也未回滚。
- 独立核验：组件编译就绪不保证实例创建成功，null 结果仍被提交进页面列表。
- 修复方向：检查实例创建结果，失败时回收新控制器且不修改页面列表；页面替换应在新对象可用后再提交。
- 原始验证范围：仅静态审查。建议使用带未赋值 required 属性的受控简单页，验证创建返回 false、页面数及控制器数不变，原标签仍可切换；不加载实际插件。

### UI-CONFIG-13 · P2 · 关闭忽略区域编辑器后，晚到的预览仍访问已卸载的图像组件

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/qt_res/qml/Widgets/IgnoreArea/IgnoreArea.qml:67`
- 触发与影响：打开图片忽略区域预览后立即返回，但批量页面仍保留；OCR 成功结果稍后到达，getPreview 会调用已经由 Loader 卸载的 imageWithIgnore。
- 依据：Loader.active 在 82 行绑定编辑器 visible，关闭时只清 running，没有使预览会话失效。getPreview 未检查可见性或组件存活。UmiOCR-data/py_src/tag_pages/BatchOCR.py:282-284 只检查整页关闭、token 和批次 generation，关闭编辑器不会改变这些值。
- 原始反证：整页关闭及开始新预览会阻止旧结果；只关闭这一层编辑器并不会关闭批量页面或取消现有 token。
- 独立核验：编辑器卸载后仍可收到属于同一批量页面的成功回调，未检查目标组件存活。
- 修复方向：为编辑会话建立独立身份，隐藏时取消或失效请求；晚到回调不得访问卸载的 Loader 项。
- 原始验证范围：仅静态审查。建议使用可延迟交付的预览替身，关闭编辑器并处理卸载事件后再交付结果，断言没有 QML 错误或状态回写。

### UI-CONFIG-14 · P2 · 通用按钮只设置自定义 text_，没有可靠的原生可访问名称

- 证据等级：UNVERIFIED；待验证风险，不作已证实缺陷
- 基线位置：`UmiOCR-data/qt_res/qml/Widgets/Button_.qml:11`
- 触发与影响：屏幕阅读器定位开始任务、重置、菜单动作或图标按钮时，控件原生 text 仍为空；可见文字和悬停提示没有被绑定为该按钮的可访问名称。
- 依据：Button_ 单独声明 text_ 并只赋给 contentItem 文本，没有绑定 Button.text 或 Accessible.name。UmiOCR-data/qt_res/qml/Widgets/IconButton.qml 替换前景后同样未提供名称；TabButton_ 也仅使用 title。
- 原始反证：可见标签和部分 tooltip 存在，UmiOCR-data/qt_res/qml/Configs/NvidiaDeviceConfig.qml 还显式设置了 Accessible.name；不能据此证明其他自定义按钮在实际辅助技术中有正确名称。
- 独立核验：自定义文本未绑定原生名称属实，但实际辅助技术读取结果尚缺 Qt 可访问性层证据。
- 修复方向：文字按钮同步原生 text/Accessible.name，纯图标按钮提供明确动作名称，并暴露可见焦点状态。
- 原始验证范围：仅静态审查，未宣称已实测屏幕阅读器。建议查询受控按钮的 QAccessible 名称、角色和动作，核对与可见文字一致，图标按钮名称非空。

### UI-CONFIG-15 · P2 · 通知窗走原生关闭路径时可能留下无法自动解除的主窗口遮罩

- 证据等级：UNVERIFIED；待验证风险，不作已证实缺陷
- 基线位置：`UmiOCR-data/qt_res/qml/Popup_/MessageBoxWin.qml:78`
- 触发与影响：通知或确认窗收到 Alt+F4 等原生关闭事件，窗口被关闭，但没有经过自定义按钮回调，主窗口的 modal 遮罩可能仍保留该 winId。
- 依据：createWin 总会 showMask；只有本文件的 close(winId) 会 hideMask。各 FramelessWindow 和 UmiOCR-data/qt_res/qml/Widgets/FramelessWindow.qml 都没有 onClosing 清理。UmiOCR-data/qt_res/qml/Popup_/MaskLayer.qml:48-49 使用 modal=true、NoAutoClose。
- 原始反证：自定义确认、取消和倒计时结束会正确清遮罩。风险限定为绕过这些回调的原生窗口关闭路径，尚未做原生事件复现。
- 独立核验：原生关闭后的清理缺口有静态依据，但当前平台具体触发路径尚未独立核实。
- 修复方向：统一处理原生 closing 与自定义关闭，保证清理和取消回调恰好执行一次，并移除 winDict 条目。
- 原始验证范围：仅静态审查。建议在受控通知窗发送 QCloseEvent，检查对应 mask id 被移除且确认操作未被误执行；不退出主应用或触发电源动作。

### UI-CONFIG-16 · P2 · 长错误消息使无边框对话框无限增高，确认按钮可能落到屏幕之外

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/qt_res/qml/Popup_/MessageBox.qml:52`
- 触发与影响：插件健康检查或错误详情包含约百行文本时，对话框高度随全文增加，底部确认按钮可能超出工作区，主窗口同时被遮罩阻塞。
- 依据：MessageBox 固定宽度为 25 个行高，高度直接取 childrenRect.height，消息文本换行但没有滚动容器或高度上限；UmiOCR-data/qt_res/qml/Popup_/MessageBoxWin.qml 各窗口直接使用该内容高度。
- 原始反证：短消息正常，窗口也能拖动；但没有针对长诊断、较大字号或小工作区的自动适配。原生平台最终几何行为本轮未实测。
- 独立核验：正文决定的内容高度没有工作区上限，足够长消息会把底部操作推到可见区外。
- 修复方向：将正文放入有工作区高度上限的滚动区，保持标题和确认/取消操作固定可达。
- 原始验证范围：仅静态审查。建议用合成多行文本创建受控消息组件，核对总高度受限、正文可滚动及按钮边界可达；不读取真实日志或截图。

### UI-CONFIG-17 · P3 · 没有选区时点击记录复制会访问 get(-1) 并抛错

- 证据等级：CONFIRMED_STATIC；本轮已修复，定向证据另存
- 基线位置：`UmiOCR-data/qt_res/qml/Widgets/ResultLayout/ResultsTableView.qml:360`
- 触发与影响：在空记录区或没有选中过记录时打开菜单点击复制，startIndex/endIndex 都为 -1，复制函数访问不存在的模型项。
- 依据：getIndexes 返回 li=ri=-1；selectCopy 没有先校验范围，直接 resultsModel.get(li)，随后读取 item.resText。函数原本的“无选中文字”提示因此不会执行。
- 原始反证：selectDel 和 selectSingle 已有负索引防护，正常鼠标选区路径也合法；遗漏的是复制的无选区入口。
- 独立核验：无有效选区的复制菜单入口直接解引用不存在的模型项。
- 修复方向：复制前检查记录数和索引范围，无有效选区时安全返回或显示现有提示。
- 原始验证范围：仅静态审查。建议分别在零条和有记录但未选择的状态调用复制，断言无 QML 异常且未改写剪贴板。
- 主线程补充：空选区复制受控QML复现

### UI-CONFIG-18 · P3 · 仅切换标签不会保存活动页，重启恢复到过时的选中项

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/qt_res/qml/TabView_/TabViewManager.qml:190`
- 触发与影响：打开多个标签后切换到另一页，不再增删或移动标签便退出；下次启动恢复的仍是上一次结构操作时保存的页，而不是退出前正在看的页。
- 依据：showTabPage 更新 showPageIndex 但不 settings.save；保存只发生在初始化及增删改移。UmiOCR-data/qt_res/qml/MainWindow/MainWindowManager.qml:135-138 退出仅保存窗口几何，没有补存标签选择。
- 原始反证：标签列表和结构变化会保存活动索引，所以并非完全没有恢复功能；纯选择操作遗漏了持久化。
- 独立核验：活动标签只在结构保存时写入，纯切换后退出会留下旧索引。
- 修复方向：在选择变化后保存活动页，或以稳定页面身份在明确的退出保存点记录；过滤不可用历史页时也应映射选中身份而非沿用旧数字索引。
- 原始验证范围：仅静态审查。建议使用内存 Settings 替身切换 A/B，检查写入值；以保存快照重建管理器验证活动页，无需启动实际应用。

### UI-CONFIG-19 · P3 · 实时切换语言不会更新对应的文字缩放系数

- 证据等级：CONFIRMED_STATIC；本轮已修复，定向证据另存
- 基线位置：`UmiOCR-data/qt_res/qml/MainWindow/Size_.qml:52`
- 触发与影响：从中文切换到英文后，文字内容已翻译，但仍使用中文的 1.0 系数而非英文 0.85；反向切换也保留英文较小字号，直到重启。
- 依据：textScale 只在 Component.onCompleted 从 languageScale 赋值，没有 onLanguageScaleChanged 或绑定。UmiOCR-data/py_src/utils/i18n_configs.py:111-112 只调用 engine.retranslate，不重建 Size_；基线 dev-tools/i18n/release/en_US.ts 的 1.0 翻译值为 0.85。
- 原始反证：首次启动按语言设置字号有效，ui.scale 的统一缩放也仍有效；问题限定为运行中的语言切换。
- 独立核验：基线缺陷成立；工作区已经有针对该项的未提交修补，不能把基线问题当作当前仍未修复。
- 修复方向：让 textScale 成为经过校验的 languageScale 派生值，或在语言系数变化时重新计算。
- 原始验证范围：仅静态审查。建议在同一个 Size_ 实例上模拟语言重译，核对 languageScale 和 textScale 同步变化；不需要窗口截图。

### UI-CONFIG-20 · P3 · 二维码预处理数值与 UI 约束不一致，合法输入被静默取整或忽略

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/mission/mission_qrcode.py:173`
- 触发与影响：用户按提示输入锐度增强 0.4 或 1.4，实际分别被取整为 0 或 1；中值滤波输入 2 在界面可保存，但后端直接不执行滤波。
- 依据：173-179 行对 sharpness_factor 使用 round，对中值滤波偶数静默跳过。UmiOCR-data/qt_res/qml/TabPages/QRCode/QRCodeConfigs.qml:38-52 将锐度声明为小数，并仅用 0..10 整数范围验证中值滤波，没有实现其提示要求的奇数约束。
- 原始反证：对比度参数保留浮点数，奇数滤波值也能工作，说明问题是特定参数的 UI/处理契约不一致，而非整个预处理接口失效。
- 独立核验：锐度小数被取整、中值滤波偶数被静默跳过，均与可保存的 UI 参数契约不一致。
- 修复方向：锐度保留浮点输入；为中值滤波明确提供关闭值和 1/3/5/7/9 选择或奇数验证，非法值应解释而非静默忽略。
- 原始验证范围：仅静态审查。建议用 PIL 增强/滤波替身记录收到的参数，验证 0.4/1.4 原样传入、偶数在提交前被拒绝；不进行扫码或截图。

### UI-CONFIG-21 · P3 · Esc 退出快捷键录制会删除原先保存的快捷键

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/qt_res/qml/Configs/Configs.qml:1341`
- 触发与影响：已有快捷键的用户点击重新录制，再按提示用 Esc 退出；原先的快捷键被取消并保存为空，而不是保留原设置。
- 依据：UmiOCR-data/py_src/event_bus/key_mouse/keyboard.py:182-183 在 Esc 时发布空字符串；基线 readFinish 无条件调用 changeHotkey(kn)，其空字符串分支删除已有注册并 value('')。界面另有独立清除按钮。
- 原始反证：录制冲突和失败能解释原因，清除按钮也能主动取消快捷键；当前协议却没有区分“取消录制”和“主动清除”。
- 独立核验：取消录制与主动清除共用空字符串，Esc 会撤销并持久化删除旧热键。
- 修复方向：录制结果显式区分取消与空快捷键；Esc 路径恢复原值，不执行持久化清除。
- 原始验证范围：仅静态审查。建议用热键注册和设置替身模拟已有值、录制取消事件，检查旧值及注册仍在；不要启动全局键盘监听或截图。

### UI-CONFIG-22 · P3 · 批量图片预览的打开图片按钮引用了不存在的提示翻译键

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/qt_res/qml/TabPages/BatchOCR/PreviewImage.qml:83`
- 触发与影响：悬停批量图片预览中的“用默认应用打开图片”图标，得不到动作说明，且该控件本身没有可见文字。
- 依据：此处调用 IconButtonBar.tr('用默认应用打开图片')，但 UmiOCR-data/qt_res/qml/Widgets/IconButtonBar.qml:26-37 的 trTable 没有该键；44-52 行将 undefined 转为空 tooltip。
- 原始反证：同一栏的保存、适应窗口等翻译键存在，打开图片动作本身也已连接；缺陷限定为该按钮的动作提示。
- 独立核验：打开图片按钮查询的翻译表键不存在，最终得到空悬停提示。
- 修复方向：补齐统一翻译表，或在调用处使用 qsTr，并给图标按钮提供同义的可访问名称。
- 原始验证范围：仅静态审查。建议遍历预览按钮定义，断言所有应有提示的翻译查询返回非空字符串；不实际打开图片。

## plugins-models

### 覆盖

- 确认 D:/Code/Python/Umi-OCR 的 HEAD 为 876a3a2332bb311fc568d8db4765278cde3a0bcf；专项宿主文件的 git diff --name-only 为空，未把范围外正在进行的 UI、翻译和测试改动归因于该基线。
- 静态审查 UmiOCR-data/py_src/plugins_controller 下的发现、清单、能力、共享服务、连接器和模型下载源码，以及 UmiOCR-data/py_src/ocr/api/__init__.py、UmiOCR-data/py_src/document/api/__init__.py。
- 追踪直接调用链到 UmiOCR-data/py_src/mission/backend_runtime.py、UmiOCR-data/py_src/mission/backend_apply.py、UmiOCR-data/py_src/mission/managed_mission.py、相应任务管理器和连接器，并核对后端路由对待应用配置的拒绝保护。
- 审查 UmiOCR-data/qt_res/qml/Configs/GlobalConfigs.qml、UmiOCR-data/qt_res/qml/ApiManager/OcrManager.qml、UmiOCR-data/qt_res/qml/ApiManager/DocumentManager.qml 的配置延后、预热、清理、状态与下载回填链。
- 审查 UmiOCR-data/py_src/utils/cuda_device_probe.py、UmiOCR-data/py_src/utils/_cuda_device_probe_worker.py 及设备配置展示；核对了响应大小/结构限制、逻辑序号和 UUID、单次进程所有权、超时回收、缓存和并发合并，未形成额外有依据缺陷。
- 只读核对 release/Umi-OCR/UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/umi-plugin.json 的版本 3.0.5、release/Umi-OCR/UmiOCR-data/plugins/win32_PaddleOCRVL_1_6/umi-plugin.json 的版本 3.1.3，并阅读宿主交互所需公开 API、runtime、health 和协议检查适配源码；没有审查整个外部推理引擎。
- 主动核对并保留反例：任务/取消许可和忙时配置延后确有实现；任务每项都会执行 msnPreTask，故未报告共享回调被后一任务永久覆盖；下载已有大小/哈希、HTTPS 跳转、链接/junction/硬链接目标拒绝、排他发布和失败清理防护；插件清单 ready 在界面显示为“已安装”，廉价 health 文案也明确没有验证实际 GPU，因此未把这些本身判为假可用。

### PM-001 · P1 · 同步服务状态轮询会等待模型启动锁，冻结主界面

- 证据等级：CONFIRMED_STATIC；后续项；合并到 LIFE-003
- 基线位置：`UmiOCR-data/qt_res/qml/ApiManager/OcrManager.qml:354`
- 触发与影响：当前 OCR 选择 PaddleVL，首次加载或预启动耗时超过 3 秒。后台启动线程持有服务锁时，主线程定时查询状态，界面因此停止响应，无法及时取消任务；等待可能持续到配置的启动超时。
- 依据：该文件 349–357、501–505 行每 3 秒同步调用 getServiceStatus。UmiOCR-data/py_src/plugins_controller/services.py:122–126 直接调用服务 get_status；release/Umi-OCR/UmiOCR-data/plugins/win32_PaddleOCRVL_1_6/runtime.py:159–189 在同一个 RLock 内完成 ensure_ready 和等待就绪，64–73 行的 get_status 也必须取得此锁。
- 原始反证：预启动本身通过线程池执行，推理许可也有串行保护；但同步状态槽没有缓存、非阻塞获取或后台查询路径，因此这些防护不能避免 UI 等锁。启动很快时可能不触发。
- 独立核验：与 LIFE-003 完全同源，合并到 LIFE-003，不作为第二个独立发现。后台预启动与同步状态查询争用同一个服务 RLock 的调用链成立。
- 修复方向：让 UI 只读取非阻塞状态快照，或异步请求状态后用信号更新；服务端也应避免在完整启动与网络探测期间长期占用状态读取锁。
- 原始验证范围：仅静态审查，未运行。最小安全复现可用 Event 控制假服务启动线程持锁，再调用真实状态转发链，记录查询是否等待；不加载模型、不启动实际服务。
- 主线程补充：服务状态方法锁竞争受控复现；GUI冻结调用链仅静态

### PM-002 · P2 · 非法 meta 类型会中断全部插件发现，而非隔离为单插件错误

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/plugins_controller/manifest.py:398`
- 触发与影响：任一插件的清单是合法 JSON，但 capabilities 中的 meta 为 true、整数或普通字符串。读取该插件时抛出 TypeError/ValueError，之后的健康插件也无法完成注册；刷新期间则会先清空旧能力，再发现失败。
- 依据：398 行直接执行 dict(item.get("meta") or {})，服务和页面元数据也有相同转换。loadManifest 只在读取 JSON 和模型下载声明处捕获异常。UmiOCR-data/py_src/plugins_controller/plugins_controller.py:167–181、266–283 对 _discover/loadManifest 没有逐插件异常隔离，注册阶段在整个扫描循环之后。
- 原始反证：JSON 语法错误、普通缺字段、服务引用不存在等情况已有明确返回错误；当前两个已安装插件的 meta 均合法。这些防护未覆盖合法 JSON 中错误的数据类型。
- 独立核验：使用 meta:true 即可建立确定异常链；并非所有错误类型都会触发，例如 false、0、空字符串被 or {} 吞掉。JSON 语法错误及 serviceRefs 校验的现有保护均不覆盖该转换。
- 修复方向：转换前严格检查 meta 必须为对象，并为逐插件发现增加异常隔离，使坏清单只产生 invalid 记录，不终止整个扫描。
- 原始验证范围：仅静态审查，未运行。最小安全复现是在临时夹具中放置 meta:true 的插件及一个健康插件，调用解析/发现流程，检查是否仅坏插件被标为 invalid；无需导入任何推理依赖。
- 主线程补充：非法meta三类输入受控复现

### PM-003 · P2 · 服务关闭失败仍清空注册表，并向刷新流程报告成功

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/plugins_controller/services.py:50`
- 触发与影响：插件自有服务进程因 terminate/wait 失败而无法退出，或者 shutdown_owned 返回 ok:false。刷新仍丢弃该服务的注册项并重新导入插件，旧进程继续占用端口和资源，新服务却已无法通过当前注册表管理它。
- 依据：48–51 行 reset 无条件在 shutdownAll 后 clear；143–155 行 _shutdown 忽略返回值，并吞掉异常。UmiOCR-data/py_src/plugins_controller/plugins_connector.py:82–88 又把 shutdownAll 无异常返回一律包装为 ok:true。已安装 PaddleVL 的 shutdown_owned 最终调用可能失败的进程 terminate/wait，见 release/Umi-OCR/UmiOCR-data/plugins/win32_PaddleOCRVL_1_6/runtime.py:270–280、316–330。
- 原始反证：UmiOCR-data/py_src/mission/backend_runtime.py:299–320 的普通后端切换会检查关闭结果，执行许可也排除了正常活动任务；但 reset/shutdownAll 不复用这套检查。旧实例的 atexit 回调仍可能保留引用，只是运行期管理入口已丢失。
- 独立核验：确认关闭失败被当作成功并丢失运行期注册入口。普通后端切换确实检查服务关闭结果，但不能覆盖仅通过预启动创建、尚无实际后端实例的服务；该反例可以绕开前置后端实例清理。
- 修复方向：聚合关闭失败并向调用方返回，失败时保留原实例和注册项、停止本次刷新；QML 刷新状态机应检查关闭结果后才重新发现插件。
- 原始验证范围：仅静态审查，未运行。用假服务分别让 shutdown_owned 返回 ok:false 和抛出异常，检查 reset 是否仍清表、shutdownServices 是否仍报告成功；不创建或终止真实进程。

### PM-004 · P2 · 插件开关直接截断写入，崩溃后可能重新启用全部禁用插件

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/plugins_controller/plugins_controller.py:565`
- 触发与影响：已有禁用插件，保存另一项开关时进程退出、磁盘写满或写入中断，使状态文件变成空文件或半截 JSON。下次启动读取失败后返回空字典，所有缺失开关按默认 true 处理，原先禁用的插件重新参与加载。
- 依据：565–566 行用 open(..., "w") 原地截断后 json.dump；550–561 行读取异常后返回 {}，203–204 行 isEnabled 对缺失项默认启用。190–201 行也在持久化成功前修改内存开关。
- 原始反证：写入异常会记录日志并向 UI 返回错误，权限拒绝且尚未截断时旧文件通常仍在；但已截断或部分写入的数据不会恢复，因此错误提示不能保护先前禁用状态。
- 独立核验：这是可达的禁用状态丢失，不只是原子写入风格建议。错误提示不能恢复已经截断的旧状态；但不能泛称任何写入失败都会丢失，失败必须发生在成功截断之后。
- 修复方向：在同目录临时文件中完成写入、刷新并原子替换，成功后再提交内存状态；失败时保留旧文件和旧内存值。
- 原始验证范围：仅静态审查，未读取真实用户状态。最小安全复现用临时状态文件模拟截断后写入失败，再调用状态读取与 isEnabled，核对旧禁用项是否被误认为启用。

### PM-005 · P2 · 下载取消无法打断在途 read，慢速持续来流可长期卡在取消中

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/plugins_controller/model_downloads.py:187`
- 触发与影响：服务器或中间代理持续低速传送数据，每次底层接收间隔小于 20 秒，但很久才凑齐一次 256 KiB 读取。用户取消后只能设置 Event，当前 read 不返回就无法观察取消，也无法进入临时目录清理。
- 依据：175 行设置的是网络操作超时，184–193 行只在 response.read(...) 前检查取消；280–290 行 cancel/close 仅设置 Event，没有关闭活动响应或传递读取截止时间。完整传输也没有总时限。
- 原始反证：完全断流通常会受到 20 秒 socket 超时约束，循环之间和哈希校验中也检查取消；已有测试只覆盖开始前已取消和直接抛出网络错误，不能证明在途慢速读取的取消有界。
- 独立核验：取消只有循环边界上的协作式检查，不能中断正在等待的 read。完全断流的 socket 超时是有效保护，但不等于总读取期限；持续小量来流可能使一次大块读取远超二十秒。
- 修复方向：为活动响应建立明确的取消/关闭所有权，并采用可及时返回的读取方式或独立截止时间；不要把单次 socket 超时当作总读取或取消期限。
- 原始验证范围：仅静态审查，未联网。可用受控假响应让 read 等待 Event，开始读取后取消，检查任务是否能在短期限结束；最后由夹具主动解除等待，避免遗留线程。

### PM-006 · P2 · 单文件模型发布强依赖硬链接，在不支持硬链接的本地盘上失败

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/plugins_controller/model_downloads.py:211`
- 触发与影响：可移植程序安装在可写的 exFAT/FAT 等不支持硬链接的本地文件系统上。模型可以完整下载并通过大小、哈希和 GGUF 检查，但最后 os.link 失败，随后删除暂存，用户只能重新下载仍然失败。
- 依据：139–217 行未检测或限制文件系统能力；kind=file 的最终提交只有 211 行 os.link 路径，没有安全的无覆盖替代方案。当前已安装 PaddleVL 的主模型和视觉投影模型均使用 kind=file，见 release/Umi-OCR/UmiOCR-data/plugins/win32_PaddleOCRVL_1_6/umi-plugin.json:301–321。
- 原始反证：同卷暂存避免了跨卷硬链接问题，在支持硬链接的文件系统上，排他链接确实能防止覆盖竞态目标；未见项目在此入口明确声明只支持这种文件系统。未实测本机卷类型。
- 独立核验：条件性兼容缺陷成立：目标卷可写但不支持硬链接且模型尚未安装时，单文件提交必然失败。未确认本机卷类型，也不应删除现有排他提交保证来规避问题。
- 修复方向：在下载前给出能力检查，或在 Windows 使用同卷、目标存在即失败的原子重命名提交文件；保持不覆盖用户模型的保证。
- 原始验证范围：仅静态审查，未下载真实模型、未检查或改动实际磁盘。可用几字节离线响应并让 os.link 抛出“不支持”错误，验证是否有安全替代提交或至少在下载前明确拒绝。

### PM-007 · P2 · 自有服务进程退出后，轮询仍可报告 ready 和已加载

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`release/Umi-OCR/UmiOCR-data/plugins/win32_PaddleOCRVL_1_6/runtime.py:68`
- 触发与影响：PaddleVL 已预启动成功，随后 llama-server 在空闲时异常退出。下一轮状态查询得到 pid:0，却仍保留 state:ready 和空 error，界面继续显示模型已加载，不能据此识别崩溃或安排重新预热。
- 依据：64–73 行只依据 poll() 计算 pid，state/error 直接返回旧字段，没有退出状态转移。UmiOCR-data/qt_res/qml/ApiManager/OcrManager.qml:354–366 将 ready/busy/sleeping 映射成 loaded，337–343 行又会跳过被认为已加载的预热。
- 原始反证：ensure_ready 在实际任务到来时会检查自有进程并尝试重新启动，显式 health 也能发现未运行；因此不是推理永远无法恢复，而是日常状态与预热判断持续使用假就绪信息。
- 独立核验：确认错误状态快照及预热判断，不确认推理永久失效。下一次 ensure_ready 或显式清理能够恢复状态，但正常轮询本身不会纠正空闲进程退出。
- 修复方向：在进程退出观察点原子更新服务状态与错误，保留退出码或可用诊断；UI 不应把 pid 为零的旧 ready 快照当作模型驻留。
- 原始验证范围：仅静态审查，未运行或终止服务。最小安全复现可给 RuntimeService 注入已退出的假 Popen，设置旧 ready 状态，再调用 get_status，检查 state、pid、error 是否一致。

### PM-008 · P2 · 健康检查不核对运行配置，可为尚未加载的新模型报告就绪

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`release/Umi-OCR/UmiOCR-data/plugins/win32_PaddleOCRVL_1_6/runtime.py:253`
- 触发与影响：服务已按配置 A 运行，用户修改主模型、投影模型或端口为 B，并在配置应用前执行“检查服务”。configure 只更新期望配置，health 校验 B 的文件后，却可以用仍按 A 运行的进程和通用 paddlevl 别名给出 ok:true；端口改变时甚至可能探测到另一个进程。
- 依据：50–59 行 configure 不启动或更新运行指纹；244–256 行 health 只检查任意自有进程仍活着，随后探测传入配置的 endpoint。运行配置差异只在 165–175 行 ensure_ready 中处理。UmiOCR-data/py_src/plugins_controller/services.py:111–114 先 configure 再 health，UmiOCR-data/qt_res/qml/Configs/GlobalConfigs.qml:537–539 检查服务不排除待应用配置。
- 原始反证：实际 ensure_ready 会比较指纹、停止旧自有服务并拒绝占用端口，阻止后续推理偷偷使用外部服务或旧配置；此问题是健康检查对当前目标配置的误报，不是已证明的错误模型推理。
- 独立核验：确认 health 对目标配置的假就绪，结论限于健康检查，不扩展为已经证明使用错误模型推理。实际 ensure_ready 的指纹比较和端口冲突拒绝仍然有效。
- 修复方向：health 应比较期望配置与运行指纹，确认探测 endpoint 属于该自有进程；不一致时返回“配置待应用/模型未就绪”，不要通过健康检查隐式启动或接管服务。
- 原始验证范围：仅静态审查，未读取权重。用假运行进程、假 GGUF 校验和固定成功的协议探测，先保留运行指纹 A，再调用带 B 的 configure/health，检查是否误返回就绪。

### PM-009 · P2 · 热刷新没有撤销进程内 vendor 与 DLL 状态，互斥插件切换可继续使用旧依赖

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/plugins_controller/plugins_controller.py:149`
- 触发与影响：一般 v2 插件 A 和 B 声明互斥，各自 vendor 相同顶层模块但版本不同。使用 A 后禁用 A、启用 B 并刷新，B 仍可能导入 A 已缓存的模块或残留搜索路径中的依赖，尽管插件状态显示切换成功。
- 依据：149–151 行只删除以插件 id 为前缀的 sys.modules；380–410 行加入的 python archive/vendor/sys.path/PATH 和 DLL directory handles 没有对应撤销。顶层 vendor 模块通常不以插件 id 命名，因此不会被上述模块清理覆盖；334–352 行互斥裁决只看本轮已启用记录。
- 原始反证：当前 CUDA 3.0.5 和 PaddleVL 3.1.3 都通过独立 worker 隔离，清单没有进程内 vendor_dirs/dll_dirs，故这不是对当前两插件组合已发生污染的指控。一般 legacy/v2 插件仍明确在支持范围内。
- 独立核验：对受支持的一般进程内 v2 插件可建立确定反例，不只是抽象卸载建议；不适用于声称当前两份隔离 worker 插件已经依赖污染。互斥裁决只排除本轮同时启用，不能清除前一轮进程级导入。
- 修复方向：对挂载进程内依赖的插件明确要求重启后完成切换，或实现有边界的纯 Python 挂载撤销；已加载原生依赖不能仅靠删除插件包模块伪装成安全卸载。
- 原始验证范围：仅静态审查，未导入插件引擎。可用两个临时纯 Python 插件及同名、不同常量的 vendor 模块，执行 A→B 刷新，检查 B 实际取得的常量；不加载 DLL。

### PM-010 · P2 · 合法的嵌套目录模型目标无法完成发布

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/plugins_controller/model_downloads.py:215`
- 触发与影响：插件声明 kind:directory、destination:family/layout，且当前 model 下尚无 family。声明校验通过，所有文件下载并校验完成后，payload.rename 因目标父目录不存在失败，暂存随后被删除。
- 依据：31–40、59–81 行允许多段安全相对目标；145–146 行只创建 model 根目录。210 行为单文件目标创建父目录，但目录分支 213–215 行直接 rename，没有创建 destination.parent。
- 原始反证：当前 PaddleVL 的 PP-DocLayoutV3 目标是单层目录，不触发该缺陷；如果嵌套父目录事先存在也能成功。问题限于校验器已经接受的另一类合法声明。
- 独立核验：合法声明与发布实现不一致。只在 destination 的嵌套父目录尚不存在时触发；当前 PaddleVL 单层目录目标不触发，但不反驳校验器接受的通用路径缺陷。
- 修复方向：在完成路径边界检查后，为目录目标安全创建并复核父目录，再执行不覆盖的原子发布；或者明确限制声明只允许单层目录并在下载前拒绝。
- 原始验证范围：仅静态审查，未下载或写入模型。可用几字节离线目录资源、嵌套 destination 和空白临时插件根复现，检查成功后整组出现且不覆盖既有目标。

## http-inputs

### 覆盖

- 已核对 D:/Code/Python/Umi-OCR 的 HEAD 为 876a3a2332bb311fc568d8db4765278cde3a0bcf；受审 py_src 及主要 HTTP/输入测试相对 HEAD 无本地差异。未触碰工作区既有 UI、翻译及未跟踪审查文档。
- 审查 UmiOCR-data/py_src/server 下全部 11 个 Python 文件，追踪监听、Origin/回环限制、Bottle 请求体解析、后端选择、同步排队、两套文档任务、导出和清理链。
- 审查 UmiOCR-data/py_src/image_controller/image_provider.py、image_connector.py，及 utils/image_decoder.py、utils/image_formats.py、utils/file_finder.py、utils/doc_probe.py、document/image_input.py 和相关调用者。
- 审查 UmiOCR-data/py_src/ocr/output 下输出器，以及 mission/mission.py、managed_mission.py、backend_runtime.py、mission_doc.py、mission_ocr.py、mission_qrcode.py、mission_document.py、doc_preview_connector.py 中直接相关边界。
- 静态核对 tests/test_http_api.py、test_http_cli.py、test_structured_http.py、test_request_budgets.py、test_request_validation.py、test_image_decoder.py、test_document_image_formats.py、test_file_import.py、test_doc_probe.py、test_ocr_workflows.py、test_markdown_outputs.py 等已有防护及覆盖范围，未执行。
- 只读核对 release/Umi-OCR/UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA 与 win32_PaddleOCRVL_1_6 的公开适配器、预算代码和 umi-plugin.json；清单版本分别为 3.0.5、3.1.3。
- 未发现普通 /api/ocr 或 /api/document 上传参数能直接指定任意服务器输入路径、输出路径或外部 URL；未知/全局 options 拒绝、任务资产归属、路径包含关系及链接/junction 检查确实存在。不把本机 CLI 用户原本拥有的读写权限单独列为漏洞。

### HI-01 · P1 · /argv 的同源鉴权可被 X-Forwarded 请求头绕过

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/server/web_server.py:88`
- 触发与影响：外部网页在能够访问本地服务的浏览器环境中发送 /argv，保留浏览器自动生成的外部 Origin，同时把 X-Forwarded-Host、X-Forwarded-Proto 设置为该 Origin 的主机和协议。请求来自浏览器本机，REMOTE_ADDR 仍为回环地址，随后能进入 CmdServer.execute，而非得到 403。
- 依据：88 行把 request.url 当成服务可信 origin；锁定的 Bottle 0.13.4 构造该 URL 时优先信任 X-Forwarded-Host/Proto。这两个头可由 fetch 设置，且本文件 43–55 行允许任意来源、任意请求头的预检。两个比较对象因此均受请求方影响，109 行会执行本机 CLI，包括 --quit 及动态模块调用。
- 原始反证：非回环直接请求、普通外部 Origin、Origin:null 均有拒绝路径，tests/test_http_api.py 也覆盖这些情况；但未覆盖 forwarded 头。浏览器的本地网络权限策略可能另行阻拦连接，不能替代服务端鉴权。单纯本机 CLI 的既有权限不是本条问题。
- 独立核验：基线 876a3a23 的服务端同源检查可由 forwarded 头伪造；确认鉴权绕过，不宣称已经完成浏览器利用。
- 修复方向：不要从 request.url/forwarded 头获取 /argv 的信任基准。该接口可拒绝所有浏览器 Origin，或按实际监听配置校验严格 Host/origin 并加入进程内随机凭据；保留普通 CLI 的兼容方式需单独设计。
- 原始验证范围：仅静态审查。最小安全复现可扩展现有 WSGI 测试，设置外部 Origin 和匹配的 X-Forwarded-Host/Proto，mock CmdServer.execute 返回固定文本，断言应为 403 且不执行；无需浏览器、网络或真实命令。

### HI-02 · P1 · 100 MB 请求体上限没有覆盖 chunked 传输

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/server/web_server.py:36`
- 触发与影响：请求使用 Transfer-Encoding: chunked 且无 Content-Length，进入文档 multipart 或 JSON 路由。传入内容可以超过 MAX_REQUEST_SIZE，在路由的文件大小验证之前持续写入 Bottle 临时文件。
- 依据：唯一的全局限制是 37 行 content_length > MAX_REQUEST_SIZE。Bottle 0.13.4 在长度缺失时返回 -1；其 chunked 解析器读至结束块，MEMFILE_MAX 仅决定何时转存临时文件，不是总字节上限。request.files 会先解析整个请求；doc_server.py 的 64 MiB 复制限制和 structured_document_server.py 的 BUDGET 都发生在此之后。
- 原始反证：有声明长度且超过 100 MB 的请求会被 413 拒绝，连接数也限制为 16；但这些限制不约束单条 chunked 流累计磁盘占用。JSON 的大小错误同样可能在 chunked 请求体已经消费后才发生。
- 独立核验：100 MB 检查没有约束 chunked 请求的实际累计读取量。
- 修复方向：在实际读取层累计并限制请求字节数，或在进入 Bottle 解析前拒绝不支持的 chunked/未知长度请求；总预算应包含 multipart 解析阶段的临时占用，超限立即中止读取并关闭自有临时文件。
- 原始验证范围：仅静态审查。可用 BytesIO 构造极小的合法 chunked WSGI 输入，把测试上限临时设为几十字节，确认超限读取立即停止并返回 413；不要发送大请求或进行磁盘/网络压力测试。

### HI-03 · P2 · 降低 MEMFILE_MAX 同时把 OCR JSON 载荷限制到了 4 MiB

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/server/web_server.py:27`
- 触发与影响：客户端上传一张编码大小略超过 3 MiB 的有效图片；Base64 包装后 JSON 超过 4 MiB，但远低于 100 MB 请求上限和插件 64 MiB 输入预算。/api/ocr 或 /api/qrcode 在读取 request.json 时提前失败，尚未进入图片或后端校验。
- 依据：27 行把 BaseRequest.MEMFILE_MAX 设为 4 MiB，注释意图是尽早转存大请求。Bottle 0.13.4 的 JSON 读取却也把 MEMFILE_MAX 用作硬上限；ocr_server.py:100–102 捕获该错误后返回 code 800。该配置不只是 RAM 转存阈值。
- 原始反证：4 MiB 以下 JSON 和更大的 multipart 文档请求不受这一特定限制。请求体需要上限本身合理，但代码中的 100 MB/64 MiB 边界与此隐含 JSON 上限并不一致，现有大小测试只覆盖超过 100 MB 的情况。
- 独立核验：4 MiB 不只是转存阈值，也成为 OCR、二维码 JSON 的隐含硬上限。
- 修复方向：把内存转存阈值和 JSON 实际接纳上限分离，按编码膨胀后的预算实现一致的读取限制；如果确实只允许 4 MiB JSON，应明确接口契约并返回清晰的大小错误。
- 原始验证范围：仅静态审查。可在 WSGI 测试中把 MEMFILE_MAX 缩小到很小数值、mock 后端，验证超过转存阈值但未超过接口输入预算的合法 JSON 是否仍可进入路由；不需要大图或推理。

### HI-04 · P2 · 传统 HTTP 文档入口仍在宿主的多个线程使用 PyMuPDF

- 证据等级：UNVERIFIED；待验证风险，不作已证实缺陷
- 基线位置：`UmiOCR-data/py_src/server/doc_server.py:99`
- 触发与影响：两个普通 /api/doc/upload 同时到达，或上传与已有文档识别、PDF 导出、桌面预览重叠。HTTP 请求线程调用 fitz.open，同时其他宿主线程也使用 PyMuPDF。
- 依据：web_server.py:127–158 使用最多 16 个请求线程；_DocUnit 在 99 行调用 MissionDOC.getDocInfo，再在 154 行调用 addMission，两者在 mission_doc.py:87、365 直接打开 fitz。任务页处理、output_pdf_layered.py 和 doc_preview_connector.py 还在其他线程调用同一原生库，没有共同执行隔离。官方文档明确警告该用法可能导致错误或进程崩溃。
- 原始反证：GUI 文件元信息导入已通过 utils/doc_probe.py 隔离到进程；MissionDOC 内部队列也按顺序执行。但传统 HTTP 元信息、提交和导出没有复用此防护，且内部队列锁不覆盖这些调用者。未声称已复现原生崩溃。
- 独立核验：跨宿主线程调用 PyMuPDF 的路径成立，但尚不足以静态证明某一具体交错必然产生错误或崩溃。
- 修复方向：将传统文档探测、打开、逐页处理和 PDF 导出放入拥有完整文档生命周期的独立进程，避免把 fitz 对象跨宿主线程交付；不能仅给单个任务的页循环加锁。
- 原始验证范围：仅静态审查。先用 fitz 桩记录并发上传、提交、导出各调用的线程/进程身份，验证所有 PyMuPDF 操作落入统一隔离执行域；无需用真实原生库制造并发崩溃。

### HI-05 · P2 · 传统混合及仅文本提取在预算检查前展开页面图片

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/mission/mission_doc.py:191`
- 触发与影响：HTTP 上传体积小于 64 MiB、页数合法，但页面内含大尺寸压缩位图或大量图片。默认 mixed 以及显式 textOnly 都先执行包含图片的 get_text('dict')，可在宿主中展开大量资源；textOnly 实际不需要这些图片。
- 依据：179 行的像素检查仅位于 fullPage 分支。其余模式在 191 行无条件调用 page.get_text('dict', clip=...)，之后才在 194–196 行判断是否使用图片；没有逐图尺寸、图片总像素、解压后字节或文本块预算。下游 OCR 插件的输入预算无法撤销此前的 MuPDF 页面提取。
- 原始反证：上传文件有 64 MiB 上限、HTTP 一次最多处理 500 页，fullPage 渲染也已有 32 Mi 像素限制；它们不能约束单页嵌入资源的膨胀。结构化文档插件已有独立累计像素预算，本条针对仍公开的传统入口。
- 独立核验：非 fullPage 模式在任何逐图预算前提取带图片的完整字典，textOnly 也未禁用图片。
- 修复方向：textOnly 明确关闭图片保留标志；mixed/imageOnly 在提取前检查图片元信息与累计预算，并将不可安全中断的原生页面处理隔离到受期限约束的进程。
- 原始验证范围：仅静态审查。用 page.get_text 桩核对 textOnly 的 flags 确实不保留图片，并用伪造的大图元信息验证预算在图片提取/渲染调用之前拒绝；不要生成解压炸弹。

### HI-06 · P2 · 二维码 HTTP options 可直接控制无上限的生成尺寸和滤波核

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/server/qrcode_server.py:57`
- 触发与影响：小型 JSON 请求提供超大 w/h，或者对小型 Base64 图片提供远超界面范围的奇数 preprocessing.median_filter_size。请求没有在进入原生图像生成或 Pillow 滤波前被拒绝。
- 依据：57–65 行只检查 options 是字典；text2base 把尺寸交给 MissionQRCode.createImage，后者仅 round 后调用 zxingcpp.write_barcode。锁定 zxing-cpp 3.1.1 的旧 API 把目标尺寸送入 WriterOptions.scale 和 Image 分配，相关路径无应用字节上限。mission_qrcode.py:173–175 同样接受任意正奇数滤波核，而注释约定为 1–9。
- 原始反证：异常通常会转成错误结果，原生库也可能拒绝部分值；但异常处理不是峰值分配或 CPU 工作量预算。OCR/document 的 schema 和资源校验没有应用于二维码接口。
- 独立核验：确认可由小请求绕过二维码预处理资源策略；“滤波核完全无上限”的字面表述应收窄。
- 修复方向：给二维码生成、识别预处理建立独立的有限数值 schema，限制边长、总像素、文本长度、quiet_zone 和滤波核，并在调用原生库前拒绝；重型处理还应有可取消期限。
- 原始验证范围：仅静态审查。mock write_barcode 和图像 filter，传入超过策略上限的尺寸/滤波核，断言原生函数未被调用；不要实际分配超大二维码或运行大核滤波。

### HI-07 · P2 · 二维码识别和图片预览绕过了已有解码像素预算

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/mission/mission_qrcode.py:63`
- 触发与影响：体积很小但解码像素很多的 PNG/JXL 等图片经 /api/qrcode 识别，或作为本地图片预览加载。宿主直接完整解码，既有 3200 万像素、32000 单边预算不生效。
- 依据：61–63 行调用 decode_image_pil 时没有 max_pixels/max_side；image_provider.py:163 的 QImage 失败回退也如此。utils/image_decoder.py 的两个参数默认为 None，只有显式传入才做尺寸拒绝。相比之下 document/image_input.py:60 明确传入了两个预算。
- 原始反证：HTTP 请求体/JSON 有编码大小限制，Pillow/OpenCV 也有各自默认防护；它们不等于项目已制定的解码预算，且受支持的编码和原生分配路径不同。QImage 返回 null 后的回退也不能被视作安全拒绝。
- 独立核验：二维码和预览回退确实绕过宿主现有的显式解码像素、单边预算。
- 修复方向：在所有不可信图片入口统一执行压缩字节、头部尺寸和像素预算，再调用解码器；预览回退不得绕开预算，二维码解码也应使用同一受限接口。
- 原始验证范围：仅静态审查。通过解码器桩检查 QR/预览调用是否传递预算，并把测试像素上限缩小到小图即可触发的值，验证在完整解码前拒绝；无需真实巨图。

### HI-08 · P2 · 同步等待能占满 16 个 HTTP 槽位并阻断状态和取消接口

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/server/web_server.py:139`
- 触发与影响：模型被一个长文档占用，多个同步 OCR 请求排队；客户端超时断开后又重试。旧处理器仍在等待，最终 16 个许可全部被占，后续状态查询及取消请求也只得到 503。
- 依据：许可覆盖整个请求处理周期。Mission.addMissionWait 在 mission.py:263–265 无期限 condition.wait；BackendRuntime.operation 的排队也只有取消谓词、没有请求期限。socket.settimeout(30) 约束套接字 I/O，不会中断这些等待；taskTimeoutSeconds 到真正执行后才进入后端。
- 原始反证：模型队列和连接数都有硬上限，实际推理也有超时，避免了无界线程增长；但没有给控制接口保留容量，也没有在等待请求断连后取消其排队工作。
- 独立核验：可确认长等待期间控制接口被共同连接池拒绝；不将其夸大为必然永久死锁。
- 修复方向：为同步请求建立从接纳开始的期限及取消上下文，等待超时后取消自己所属任务并释放许可；状态/取消接口应有独立的接纳余量，或改为异步任务协议。
- 原始验证范围：仅静态审查。用可释放 Event 的后端桩和缩小的许可池验证排队超时、请求结束后的资源释放及控制接口可用性；不需要网络并发或实际长推理。

### HI-09 · P2 · 并发 CLI OCR 请求会被同一个全局完成事件错误唤醒

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/server/cmd_server.py:219`
- 触发与影响：两个 /argv --path 请求同时等待不同图片，或者一个 CLI 请求等待时桌面上另一批图片识别结束。第一个 ScreenshotOcrEnd 事件会让所有等待者返回同一份结果，而非各自输入的结果。
- 依据：quick_ocr 为每个请求订阅同名全局事件，212–217 行回调无任务 ID/来源过滤。ScreenshotOCR.py:41、68–101 又把 recentResult 存在页面实例上并在每次 ocrPaths 时重置，任一任务结束均发布该全局列表。HTTP 服务现已允许多个请求并行进入这条链。
- 原始反证：Condition 谓词避免了丢失通知，单个串行 CLI 请求通常正确；这不提供请求关联或结果隔离。该问题不要求执行任何截图捕获。
- 独立核验：CLI 等待者没有任务关联，任一全局完成广播都会唤醒所有当时订阅者。
- 修复方向：使用请求/任务 ID 关联回调，并让结果列表属于该请求上下文；纯路径 CLI 可直接等待所属 Mission 的完成，而不是订阅页面级广播。
- 原始验证范围：仅静态审查。使用两个不同结果的事件/Mission 桩模拟两个 --path 调用，只完成其中一个，断言另一个仍等待且结果不串用；不做截图、HDR 或真实 OCR 测试。

### HI-10 · P2 · 同一传统文档的并发导出会互删或截断产物

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/server/doc_server.py:225`
- 触发与影响：两个客户端同时对同一已完成任务请求不同或相同 file_types。一个请求删除旧文件时，另一个可能已创建输出；两个同格式输出器也会打开同名路径写入，导致下载缺失、损坏或临时文件混入打包。
- 依据：get_files 在 225–229 行删除任务目录内所有非源文件，随后在同一目录、同一文件名前缀生成结果并扫描打包。全过程没有任务级导出锁或独立尝试目录；_mutex 仅用于结果读写，不覆盖 get_files。
- 原始反证：任务必须先成功结束才能导出，生成路径也局限于任务目录，因而不是任意路径删除漏洞；但任务结束不代表并发 HTTP 导出被串行化。现有 Markdown/HTTP 输出测试均为顺序调用。
- 独立核验：同任务导出的清理、生成和收集没有互斥，可确定构造交错导致缺失或混合结果。
- 修复方向：让每次导出使用独立自有目录并原子发布，或对同一任务的生成/收集/清理加完整互斥；已返回的下载路径不应被另一个导出尝试在写入中删除。
- 原始验证范围：仅静态审查。可用小文件输出器桩和两个 barrier 固定交错顺序，验证一个导出不能删除另一个正在生成的文件；无需真实 PDF、推理或网络。

### HI-11 · P2 · 结构化任务同步拒绝后仍保留不可寻址的输入和任务配额

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/server/structured_document_server.py:384`
- 触发与影响：后端接纳返回 [Error] busy 等同步错误。客户端只收到错误，没有 jobId，重试会创建新的失败任务；多次正常重试即可耗尽任务数量或临时空间配额，即使后端已恢复空闲。
- 依据：384 行先把 job 放入 JOBS；DocumentJob.start 在同步错误时调用 _on_end，但 387–388 行只返回 _error，不移除任务、不返回其 ID。失败输入按实际大小计入 BUDGET，保留至少三小时；接口没有显式删除任务路由。tests/test_structured_http.py:181–192 也确认了这种保留行为。
- 原始反证：失败会关闭 selection 并结算多余预留，不是预留双重计费；过期后的 _cleanup 能回收当前进程任务。但客户端无法针对这个未返回 ID 的失败任务主动回收。
- 独立核验：同步未接纳的任务仍保留配额和输入，错误响应却不给客户端任务身份。
- 修复方向：对于未被接纳、从未执行的任务，在安全收尾后撤销 JOBS 条目并删除本次自有输入、释放预算；如需保留诊断，则返回 jobId 并提供受控删除接口。
- 原始验证范围：仅静态审查。复用 FakeManager 返回 [Error] busy 的现有测试，把 MAX_JOBS 降为很小值，断言连续拒绝不会消耗后续成功提交的名额，也不会遗留无法查询的输入。

### HI-12 · P2 · 应用重启后 HTTP 任务文件脱离所有保留期和预算管理

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/server/structured_document_server.py:24`
- 触发与影响：存在已完成或未完成 HTTP 文档任务时正常退出或被关闭，再启动应用。上一进程的源文档及资产留在磁盘上，但任务注册表和预算归零，之后无论等待多久或使用 clear 都不能通过新进程回收旧任务。
- 依据：结构化 JOB_ROOT 每次导入生成新的会话 UUID，JOBS/BUDGET 仅在内存，_cleanup 只遍历当前 JOBS。传统 doc_server 的 doc_units 同样每次为空，init 明确不登记历史目录，auto_clear 只遍历内存条目。run.py 的退出钩子仅关闭后端，没有持久化 HTTP 任务所有权。
- 原始反证：不盲删历史目录是合理安全防护，本轮不建议直接清空 temp_doc。当前进程有数量、时间或字节限制；但它们不约束重启后累计磁盘占用，旧任务也无法按声明的保留期到期。
- 独立核验：可确认重启使已知 HTTP 任务文件脱离当前保留期和预算；不是要求盲删历史目录。
- 修复方向：为本模块创建的任务持久化最小所有权/保留期账本，启动时只恢复经标记、路径、链接和占用验证的自有任务；明确处理中断状态及安全回收策略，不扫描删除未知目录。
- 原始验证范围：仅静态审查。可在临时测试根中构造两代注册表及一个带合法所有权标记的旧任务，用固定时钟验证重启后的恢复和到期识别；只操作测试自建目录，不启动应用或清理真实任务数据。

### HI-13 · P2 · 统一接纳的 JXL/JXR 图片没有进入 CUDA 支持的解码链

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/worker.py:125`
- 触发与影响：选择当前安装的 CUDA 3.0.5 后端，导入合法 .jxl/.jxr/.wdp/.hdp 图片，或向 /api/ocr 发送其 Base64。宿主接受格式并原样交给 worker，后者不能使用宿主已有的 imagecodecs 解码支持，返回输入解码错误。
- 依据：utils/image_formats.py 将这些扩展名统一列入 IMAGE_SUFFIXES；MissionOCR.msnTask 和 ManagedApi.runPath/runBase64 直接转发。CUDA worker 的 125–129 行只用 Pillow Image.open 做头检查、OpenCV 4.10 imdecode 解码，没有 JXL/JXR 分支；其依赖锁也无相应 Pillow 插件。固定安装公开 worker 代码相同。
- 原始反证：宿主 utils/image_decoder.py、二维码及 PaddleVL 的 prepared_document_input 已有 JXL/JXR 支持，因此单测解码通过不代表 CUDA OCR 支持。test_ocr_workflows.py 只对未启动 CUDA API 的 JXL/JXR 断言 code 203，没有覆盖已启动解码。
- 独立核验：CUDA 已启动时，统一接纳的 JXL/JXR 没有宿主规范化或 worker 解码适配。
- 修复方向：在进入 CUDA worker 前用有预算的宿主解码/无损规范化适配不支持的编码，或在 CUDA 组件内实现相同的受限解码支持；不要仅删除共享清单中其他后端已支持的格式。
- 原始验证范围：仅静态审查。最小验证只需用小型 JXL/JXR 固件直接调用隔离 worker 的 decode_request，或对宿主规范化入口设桩；无需加载模型、启动 CUDA 引擎或修改插件版本。

### HI-14 · P2 · 依据像素峰值猜测位深会严重提亮合法 16 位图片

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/utils/image_decoder.py:193`
- 触发与影响：16 位 PNG/JXL 的整张图恰好较暗，最大样本值不超过 1023 或 4095。代码把它误认为 10/12 位数据，正常应接近黑色的值会变成亮灰甚至白色，预览及 OCR 输入均改变。
- 依据：_to_uint8 对所有 uint16 图像使用 np.max(image) 决定分母 1023/4095，而不是编码的真实位深。比如完整 16 位输入值 1023，应按 65535 映射为约 4，当前分支映射为 255。该函数也用于普通 cv2.imdecode 的 16 位结果，并不限于 libjxl。
- 原始反证：现有 10/12 位 JXL 回归解释了此分支的目的，但测试样本覆盖完整亮度范围，没有覆盖低峰值的真实 16 位图；uint8 不受影响。
- 独立核验：真实位深被内容峰值替代，合法暗 16 位图像可被确定性提亮。
- 修复方向：从解码器/编码元信息传递实际 bit depth，仅对明确的 10/12 位载荷使用对应量程；不能从图像内容的最大值推断动态范围。
- 原始验证范围：仅静态审查。用几个极小 uint16 数组及小型 16 位 PNG/JXL 对照，区分真正 10/12 位数据与低亮度 16 位数据；不需要应用、推理或大文件。

### HI-15 · P2 · 本地图片路径被无条件 URL 解码，可能预览错误文件

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/image_controller/image_provider.py:134`
- 触发与影响：用户选择名为 scan%20one.jxl 的合法本地图片。文件对话框已把 URL 转为原始路径，但自定义 JXL/AVIF 预览再次 unquote；若 scan one.jxl 存在就预览它，否则报告文件不存在，和实际 OCR 输入不一致。
- 依据：utils.QUrl2String 使用 QUrl.toLocalFile，返回已解码路径；Widgets/Image_.qml:14–15 对特殊编码把该原始路径直接传给 loadImage。_imread 在分辨原始路径与 file URI 之前无条件 unquote，随后用变更后的路径做 exists/read。
- 原始反证：普通没有百分号转义序列的路径，以及经过恰好一次编码的 file:/// 输入通常正确。输入路径包含关系和权限并未被提升；本条是选择身份与实际读取内容不一致。
- 独立核验：原始文件系统路径中的百分号序列被误当 URL 编码，存在选择与读取身份不一致。
- 修复方向：先区分原始文件系统路径和 URL；原始路径保持逐字不变，file: URL 使用 QUrl.toLocalFile 解析一次，而非对所有字符串 unquote。
- 原始验证范围：仅静态审查。对 _readLocalImage/exists 设桩，分别传入含字面 %20 的路径和编码后的 file URI，确认最终读取的是各自预期路径；无需打开 GUI 或实际图片。

### HI-16 · P2 · 图片保存失败时仍向界面返回 Success

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/image_controller/image_provider.py:241`
- 触发与影响：保存目标的父目录不存在、目录不可写，或格式无法保存。Qt 的 save 返回 false 而不抛异常，界面仍显示保存成功；在内存图片的 openImage 分支中也可能继续打开旧缓存文件。
- 依据：241–244 行忽略 data.save(toPath) 的布尔返回值，无条件返回 [Success]。openImage 的 209 行也忽略 data.save(path) 后继续 Platform.startfile。ImageScale.qml:97–99 仅根据 Success 前缀展示成功。Qt 官方文档明确 save 失败可以通过 false 报告。
- 原始反证：抛异常的失败已被捕获，但正常 false 返回不走异常分支。该问题不需要越权或恶意输入，普通保存错误即可触发。
- 独立核验：Qt 正常返回 false 的保存失败不会进入异常分支，却被报告为成功。
- 修复方向：检查 save 的返回值，并在 false 时返回错误且禁止打开缓存；缓存应为本次唯一、确认成功写入的文件，不能把残留文件当成本次保存结果。
- 原始验证范围：仅静态审查。让 _imread 返回一个 save() 为 false 的 pixmap 桩，断言 saveImage 不返回 Success，openImage 不调用 startfile；不需要写入受限目录。

### HI-17 · P2 · CSV 导出会把不可信识别内容交给表格软件作为公式

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/ocr/output/output_csv.py:68`
- 触发与影响：外部 PDF/图片包含以 =、+、-、@ 等公式触发字符开头的识别文本。用户通过桌面或 HTTP 导出 CSV 后，在自动解释公式的表格软件中打开，内容会被当作公式而非识别到的字面文本。
- 依据：print 将 getDataText 得到的原文直接放入 writeLists，onEnd 使用 csv.writer.writerow 原样输出。没有公式中和或明确的安全文本模式；csv 的逗号/引号转义并不阻止 Excel 等对单元格进行公式求值。传统 /api/doc/download 的 csv 工厂直接可达。
- 原始反证：CSV 本身不会执行代码，风险发生在支持公式的下游程序及其配置下；不能由此直接宣称自动远程代码执行。保留 OCR 原文也有合理需求，故应提供明确安全策略而非静默丢失内容。
- 独立核验：不可信 OCR 字面文本会以公式前缀原样进入 CSV；危险解释发生在下游表格软件。
- 修复方向：默认提供表格安全的文本导出，对所有单元格处理公式前缀及相关前导控制字符；若保留原始 CSV 模式，明确提示其不适合直接在公式解释器中打开。
- 原始验证范围：仅静态审查。用无害文本 =1+1 和普通文本导出极小 CSV，检查安全模式输出保留字面含义；无需启动 Excel、调用外部公式或访问网络。

### HI-18 · P2 · CSV 编码选择只检查 OCR 文本，遗漏文件名和路径

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/ocr/output/output_csv.py:52`
- 触发与影响：识别文本全为 ASCII，但源文件名或目录包含当前系统代码页无法表示的字符。编码预检选择 ANSI/ASCII 等窄编码，实际写 Name 或 Path 单元格时才 UnicodeEncodeError，导致整个导出失败并留下空白或部分 CSV。
- 依据：44 行保存 [name, textOut, path] 三列，45 行却只把 textOut 放入 writeText；52 行只测试 writeText.encode(e)，68 行才用所选编码写全部列。后续写入异常不会重新尝试 UTF-8。
- 原始反证：所有三列恰好都能用选中代码页表示时正常；OCR 文本本身不兼容窄编码时也会回退。缺口仅在未参与预检的名称/路径列，UTF-8 系统代码页也可能掩盖它。
- 独立核验：编码预检遗漏文件名和路径，实际逐行写入可能才失败且没有 UTF-8 重试。
- 修复方向：直接使用明确的 Unicode CSV 编码，或把所有表头和所有列都纳入编码预检，并采用临时文件成功写入后发布，避免失败时留下误导产物。
- 原始验证范围：仅静态审查。测试中把候选编码设为 ascii、utf-8，使用 ASCII OCR 文本及中文文件名，断言最终可完整写入并以 UTF-8 回读；无需改变用户系统区域设置。

### HI-19 · P3 · CLI 路径校验提前返回时泄漏全局事件订阅

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/server/cmd_server.py:247`
- 触发与影响：已有 ScreenshotOCR 页面时反复执行不带路径的 --path，或提供没有匹配图片的路径。每次请求返回错误，但所建回调仍永久挂在全局事件列表中，后续每次完成事件都调用全部历史回调。
- 依据：219 行先 subscribe，247–251 行随后可直接 return；唯一 unsubscribe 在正常等待结束后的 258 行，没有 try/finally。pubsub_service.py:32–34 用强引用列表保存回调，不会因 quick_ocr 返回自动回收。参数解析异常的提前返回也有同样问题。
- 原始反证：页面创建失败发生在订阅之前，不泄漏；正常收到完成事件的路径也会取消订阅。单次泄漏很小，本条不以此声称立即耗尽资源。
- 独立核验：订阅后的路径校验提前返回没有取消回调，形成持续的强引用泄漏。
- 修复方向：先完成可以提前失败的参数校验，再订阅；对订阅后的所有执行、等待和错误分支用 finally 精确取消本请求回调。
- 原始验证范围：仅静态审查。mock addPageByKey 成功，调用 quick_ocr(False, False, [])，核对事件回调数量前后不变；不启动页面、不执行图片或截图操作。

### HI-20 · P3 · 传统 HTTP 文档的 32 任务上限可以并发超售

- 证据等级：CONFIRMED_STATIC；后续项
- 基线位置：`UmiOCR-data/py_src/server/doc_server.py:484`
- 触发与影响：已有 31 个保留任务时两个上传并发进行。两者都在锁内看到 31，随后在锁外创建目录和任务，最后各自加入管理器，实际保留任务变为 33；更多请求可进一步超出声明上限。
- 依据：484–486 行只在锁内检查数量，目录创建、文件保存及 _DocUnit 构造在锁外，真正 add 到 533 行才再次加锁。检查与接纳之间没有占位名额。结构化接口则把预算和 JOBS 登记放在同一 LOCK 内。
- 原始反证：16 个连接许可限制了一次竞态的规模，并非无限并发；单线程上传也不会超售。但传统文档没有另一层统一磁盘预算，任务数上限是其主要总量防护之一。
- 独立核验：数量检查和正式登记不是同一接纳事务，32 任务上限可以并发超售。
- 修复方向：在数量检查时原子预留任务名额，把构造/写入失败的名额在 finally 中释放；不要持有全局锁进行耗时解析或文件复制。
- 原始验证范围：仅静态审查。预填 31 个轻量任务桩，对两个小型上传在 _DocUnit 构造处设置 barrier，断言最多一个被接纳且失败分支归还预留；不做真实网络或容量压力测试。

## 主线程补充条目

| ID | 内容 | 证据与处置 |
| --- | --- | --- |
| MAIN-01 | 普通D后一次Ctrl+D误清空全部记录 | 基线真实处理器JS受控复现；本轮修复，覆盖两种松键顺序、自动重复与负时间差。 |
| MAIN-02 | Qt QVariantList保存的标签被Array.isArray拒绝 | 真实PortableSettings＋QML受控复现；本轮修复。 |
| MAIN-03 | 拖动其他标签跨过活动页后保存错误活动索引 | 静态链路及修复后四种QML重排断言；未冒充修复前原生操作复现。本轮修复。 |
| MAIN-04 | 结构化失败页存入None后，部分结果导出抛AttributeError | 无模型受控回调复现md/txt/json/zip失败；本轮不改协议／插件，列入优先修复。 |

## 本轮新增UI／文档／清理复核

独立三维复核有12项候选：9项静态确认、2项改进、1项时序待证。具体原文、证据与反证见本地 `build/audit/project-review-20261108-r1/QUALITY_REVIEW.md`。

- QML-01：键盘滚动后侧栏高亮不跟踪，已修并经真实窗口方向键回归。
- QML-02：无模型组时快捷入口丢失，已回退插件管理，真实Configs无模型分组回归通过。
- QML-03：布局未收敛的时序风险未获确认；首开模型标题已补真实视口坐标断言，不将一次成功推广为所有重建时序无风险。
- visual-01：模型选择位置误导，已纠正文案和六语提示。
- visual-02：页面键先变化导致抓到旧页残影，驱动新增等待及导入区／旧页检查；r6稳定帧已替换。不是已证实用户界面持续叠层。
- visual-03：既有泰米尔语大字号标签省略，列为可用性改进。
- DOCS-CLEANUP-01..04：旧预演误选对应源码、归档身份不完整、嵌套插件版本保护缺口、遗漏NOTICE/COPYING；V1禁用，不能执行。
- DOCS-CLEANUP-05：旧GUI预设与当前HTTP查询不符，已更新现行指南。
- DOCS-CLEANUP-06：旧草稿入口清晰度，旧正文已原字节归档。

## 交付过程补充发现

### DELIVERY-001 · P1 · Windows跨清单大小写别名可破坏原件

旧本地更新引擎 `build/audit/release-312-20261102-r1/apply-fixed-update.py` 以区分大小写的键划分 before／expected；在Windows默认不区分大小写的目录，`source.txt` 可被误当成新增 `SOURCE.txt` 覆盖，失败回滚再删除而无法恢复。发现与独立反证为静态确认，没有在用户目录制造损坏状态。

本次在预演前和旧引擎调用入口双重交叉核对各清单的叶路径与全部目录前缀，并用 `fixed_update_guard_v2.py` 加入实际目标解析及“物理已存在但缺少精确所有权键”拒绝。10项定向检查覆盖正常替换、回滚、实际文件／目录解析及缺失键；其中其它Unicode目标卷行为为显式解析器模拟，当前D卷未原生复现所举i/ı等价。冲突不通过改名／备份／迁移用户文件消歧，原件不变。历史引擎原件不改写，不宣称所有旧调用者自动获得保护；后续应将这一边界收敛进正式更新工具。

清理复核中提出的“上一版必须保留”不适用于本轮：用户已明确仅保留各组件最新版本，这是一次性覆盖，永久CLAUDE规则未改。原始意见保留，主线程上下文反证另存。用户后来另行明确“批准V2清理”，对应8,412项文件和三份具名旧归档；这不是公开发布授权，后续执行与核验另立记录。

### 本轮实际交付状态

新主程序归档与独立对应源码、三包全新重装、包内28组真实窗口及纯本体／组合EXE验收已完成。初次固定安装尝试 `fixed-update-r1.json` 因PID29296占用，在写入前停止；这不是已发生的大小写数据损坏，原FAIL和阻塞回执均不回写。用户随后明确授权直接终止未退出程序；核对身份后仅终止该PID，CIM返回0，无其它终止。

接续 `fixed-update-r2.json` 已实际更新完整固定安装：主程序3.1.4／CUDA3.0.5／PaddleVL3.1.3，替换20项程序文件，23,779项载荷及3,604项原地保留文件摘要通过。两项只读复核未发现本轮已确认阻塞项，其摘要不替代上述实际执行证据；强制终止也不算正常退出验收。

用户另行批准V2精确范围，并在中断后要求接续。中断前1,951项确认删除与本次6,464项新增删除经独立联合核验，合计8,412项二进制＋3份具名旧归档；全部批准路径缺失，无重复计数或未知缺失。26个旧目录、32项组件元数据和清单外保护内容保留，31项当前重点保留摘要通过。详见[V2清理记录](CLEANUP_V2_2026-11-11.md)；最终汇总另立 `build/audit/project-review-20261108-r1/LOCAL_DELIVERY_3.1.4_CLEANUP_V2_R1.json`，此前安装汇总、FAIL与中断证据保留原截点，不回写。

## 证据入口

- 原始结构化六维结果与独立反证：`build/audit/project-review-20261108-r1/deep-audit-results.json`。
- 基线受控复现：`baseline-controlled-reproductions.json`；它保留修复前失败，不改写为通过。
- 完整发现编号永久保留；以后修复在新记录中关联，不删除历史断言。
