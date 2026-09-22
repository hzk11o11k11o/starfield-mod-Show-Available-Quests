# ============================================================================
#  Show Available Quests - 一键构建 + 部署
#
#  用法（必须 pwsh 7，直接 & 调用，不要再套一层 pwsh）：
#     & ".\tools\build-saq.ps1"                 # 全流程（ESM 复用已有产物；DLL 含 harness）
#     & ".\tools\build-saq.ps1" -RebuildEsm     # 用 xEdit 重新生成 ESM（约 5 分钟）
#     & ".\tools\build-saq.ps1" -SkipTable -SkipSwf     # 只重编 DLL
#     & ".\tools\build-saq.ps1" -Harness        # 开发/自测：含 harness + 部署用例 + ini Harness=1
#     & ".\tools\build-saq.ps1" -Release        # 发布构建：DLL **不含 harness**（打包/当玩家跑）
#
#  产物与部署位置见 docs\01-构建与环境.md
# ============================================================================
param(
    [switch]$SkipTable,
    [switch]$RebuildEsm,
    [switch]$SkipPapyrus,
    [switch]$SkipPlugin,
    [switch]$SkipSwf,
    [switch]$SkipDeploy,
    # ★ 第 49 轮：部署时把测试开关 ini 的 [Test] Harness 强制写成 1
    # （引擎内自动化测试模式：启动游戏 → 读档 → 自动跑完用例 → 写 SAQ_testresults.json）。
    # 不加这个开关就只保证 key 存在、**不动已有值**（玩家设置优先）。
    [switch]$Harness,
    # ★★ 第 53 轮（大项 F · 发布就绪）：**发布构建** —— xmake 的 saq_harness 开关设为 n，
    # DLL 里彻底没有 harness（测试命令通道 / 界面测试驱动 / 结果落盘都不编译进去），
    # 部署时也不拷测试用例文件。与 -Harness 互斥。
    # 用途：① tools\package-saq.ps1 用它做「构建 + 部署 → 校验 → 打包」的构建入口；
    #       ② 想「像玩家一样」跑一遍时用。
    # 回到开发构建：不带 -Release 跑一次（默认 saq_harness=y），或加 -Harness（测试版）。
    [switch]$Release,
    # ★★ 第 62 轮补：主菜单自动读档（harness）—— 写进部署 ini 的 [Test] AutoLoad。
    #   填了之后：启动游戏 → 按任意键到主菜单 → 插件**自动读这个存档**并自动开跑用例
    #   （连「手动读档」都省了）。留空 = 保持 ini 已有值（不自动读档）。
    #   例：-Harness -AutoLoad Save1_FDBB7678M54696D6D6568_000034_20260922142854_2_0_4
    #   （★★★ 第 103 轮起测试指定存档 = Save1_FDBB7678M54696D6D6568_000034_20260922142854_2_0_4
    #     —— 它与用例计划 r62 的 `save.load` 子串**必须一致**，verify 里有
    #     「用例计划 · r62 指定存档与部署 ini AutoLoad 一致」检查）
    [string]$AutoLoad = ''
)

$ErrorActionPreference = 'Stop'
$root    = Split-Path -Parent $PSScriptRoot
$mo2Mods = 'D:\Mod Organizer 2\starfield_mods\mods'
$modName = 'Show Available Quests (SFSE)'
$esmName = 'SAQ_ShowAvailableQuests.esm'

$baseSwf     = Join-Path $root 'ui\missionmenu\base\missionmenu.swf'
$baseSwfLrg  = Join-Path $root 'ui\missionmenu_lrg\base\missionmenu_lrg.swf'
$patchDir    = Join-Path $root 'ui\missionmenu\patch'
$patchDirLrg = Join-Path $root 'ui\missionmenu_lrg\patch'
$outSwf      = Join-Path $root 'ui\missionmenu\build\missionmenu.swf'
$outSwfLrg   = Join-Path $root 'ui\missionmenu_lrg\build\missionmenu_lrg.swf'
$outDll      = Join-Path $root 'plugin\build\windows\x64\releasedbg\SAQ_ShowAvailableQuests.dll'
$esmStable   = Join-Path $root "esm\$esmName"          # 入库的 ESM（FormID 必须稳定）
$esmFresh    = Join-Path $root "ref\xedit-out\$esmName" # xEdit 刚生成的
$pexSrc      = Join-Path $root 'scripts'
$pexOut      = Join-Path $root 'scripts\build'

$dataDir     = 'D:\SteamLibrary\steamapps\common\Starfield\Data'
$papyrusCmp  = Join-Path $dataDir '..\Tools\Papyrus Compiler\PapyrusCompiler.exe'
$papyrusFlags= Join-Path $dataDir 'Scripts\Source\Base\Starfield_Papyrus_Flags.flg'
$papyrusInc  = Join-Path $dataDir 'Scripts\Source\Base'

function Step($n, $msg) { Write-Host "[$n] $msg" -ForegroundColor Yellow }
function Ok($msg) { Write-Host "    OK: $msg" -ForegroundColor Green }

# --- 1. 静态表（master + 记录号 -> 中/英文名 + 类型 + 引导目标） ---------------
# ★ 第 17 轮（DLC 支持）：数据源不再只有 Starfield.esm ——
#   fetch_sources.py 会把每个 master 的「字符串表 + QUST 导出」都准备好
#   （ShatteredSpace.esm = 破碎空间 / SFBGS050.esm = 地球舰队 / SFBGS00D.esm = 自由航道更新）。
if (-not $SkipTable) {
    Step '1/6' '准备离线数据（fetch_sources.py：DLC 字符串 + 多 master 任务导出）'
    & python (Join-Path $root 'tools\esm\fetch_sources.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "fetch_sources.py 失败（exit $LASTEXITCODE）" }
    Step '1/6' '生成引导目标表（gen_guide_targets.py，扫全部 master，约 3-6 分钟）'
    & python (Join-Path $root 'tools\esm\gen_guide_targets.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "gen_guide_targets.py 失败（exit $LASTEXITCODE）" }
    # ★ 第 35 轮：进度门槛（「游戏进度还不能让玩家接到 ⇒ 不显示」）——
    #   analyze_ctda.py 从 xEdit 条件 dump（ref\xedit\quests_typed.txt → quests_parsed.json）
    #   与原始字节（ref\quests.json）里提取「引用别的任务」的进度检查 → ref\ctda_gates.json。
    #   依赖的 dump 是离线历史产物；要刷新先跑 tools\run-xedit-quests.ps1 + parse_xedit_dump.py。
    Step '1/6' '提取进度门槛（analyze_ctda.py → ref\ctda_gates.json）'
    & python (Join-Path $root 'tools\esm\analyze_ctda.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "analyze_ctda.py 失败（exit $LASTEXITCODE）" }
    # ★ 大项 D（第 48 轮）：INFO 门槛（对话侧条件）——
    #   ref\info_gates.json 由 scan_info_gates.py 全表扫 Starfield.esm 的 DIAL/INFO 得到
    #   （约 1 分钟；只在需要刷新对话数据时手动跑：python tools\esm\scan_info_gates.py）。
    #   ★★ 第 78 轮：**DLC 的 INFO 也要扫**（DLC 任务以前一条 INFO 门槛都没有 ⇒ 主线
    #   后续照常冒出来）。四个 master 各扫一份（各约 20~60 秒）——**文件缺失时才扫**
    #   （刷新：删掉 ref\info_gates*.json 再跑；或按脚本头的参数手动跑）。
    $infoScans = @(
        @{ esm = (Join-Path $dataDir 'Starfield.esm');       master = 'Starfield.esm';      out = 'info_gates.json' },
        @{ esm = (Join-Path $dataDir 'SFBGS00D.esm');        master = 'SFBGS00D.esm';       out = 'info_gates_sfbgs00d.json' },
        @{ esm = (Join-Path $dataDir 'SFBGS050.esm');        master = 'SFBGS050.esm';       out = 'info_gates_sfbgs050.json' },
        @{ esm = (Join-Path $dataDir 'ShatteredSpace.esm');  master = 'ShatteredSpace.esm'; out = 'info_gates_shatteredspace.json' }
    )
    foreach ($sc in $infoScans) {
        $rawOut = Join-Path $root ("ref\" + $sc.out)
        if (Test-Path $rawOut) { continue }
        Step '1/6' ("扫对话条件（" + $sc.master + " → ref\" + $sc.out + "，约 20~60 秒）")
        & python (Join-Path $root 'tools\esm\scan_info_gates.py') --esm $sc.esm `
            --self-master $sc.master --out $sc.out | Write-Host
        if ($LASTEXITCODE -ne 0) { throw "scan_info_gates.py（$($sc.master)）失败（exit $LASTEXITCODE）" }
    }
    #   这里只做交叉分析（快）：四份 info_gates*.json + 候选表 → ref\info_gates_final.json。
    Step '1/6' '生成 INFO 门槛（analyze_info_gates.py → ref\info_gates_final.json）'
    & python (Join-Path $root 'tools\esm\analyze_info_gates.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "analyze_info_gates.py 失败（exit $LASTEXITCODE）" }
    # ★ 第 65 轮（任务专属图标）：任务阵营映射 —— QUST 的 FTYP 关键字（FactionType*）
    #   -> 原版 UI 阵营枚举（FactionUtils 顺序）。需要原始 ESM（读 KYWD 组），
    #   产物 ref\faction_types.json 由 gen_quest_table.py 消费（写进静态表与内嵌载荷）。
    Step '1/6' '生成任务阵营映射（gen_faction_types.py → ref\faction_types.json）'
    & python (Join-Path $root 'tools\esm\gen_faction_types.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "gen_faction_types.py 失败（exit $LASTEXITCODE）" }
    # ★★ 第 67 轮：任务链门槛（「上一个任务的收尾 stage 启动下一个任务」）——
    #   gen_quest_chain.py 扫官方 Papyrus 源码（Data\Scripts\Source\Base）里的跨任务
    #   启动调用，只认「编号链路」（前缀相同、编号 +1、调用方是纯编号任务、调用发生在
    #   stage fragment 里；规则见该文件头注释）⇒ ref\quest_chain.json 由
    #   gen_quest_table.py 消费（写进静态表的 kChainGates）。
    Step '1/6' '生成任务链门槛（gen_quest_chain.py → ref\quest_chain.json）'
    & python (Join-Path $root 'tools\esm\gen_quest_chain.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "gen_quest_chain.py 失败（exit $LASTEXITCODE）" }
    # ★★ 第 69 轮：链式门槛的**扩展边**（非编号链路里同形态的「收尾启动下一个」：
    #   Eleos 线 / 霓虹城帮派线 / 城市支线预启动）—— 表是人工核实的，但每条边都在
    #   这里对着官方 Papyrus 源码**重新核验**（找不到调用/宿主/stage 不符 ⇒ 直接失败，
    #   不会静默写一份错数据）⇒ ref\quest_chain_extra.json 由 gen_quest_table.py 合并。
    Step '1/6' '生成扩展链式边（gen_quest_chain_extra.py → ref\quest_chain_extra.json）'
    & python (Join-Path $root 'tools\esm\gen_quest_chain_extra.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "gen_quest_chain_extra.py 失败（exit $LASTEXITCODE）" }
    # ★★★ 第 98 轮：**DLC 的链式启动边**（gen_dlc_chain.py）—— DLC 不发 .psc，所以这里
    #   先把 BA2 里的 .pex 抽出来、用 Champollion（Orvid v1.3.2）反编译成 .psc，
    #   再按与基础游戏同一套形态抽「宿主 stage fragment 启动下一个任务」的边，
    #   产物 ref\quest_chain_dlc.json 由 gen_quest_table.py 合并进 kChainGates
    #   （取证全过程见 docs/06 八节）。宽容策略：没有 Champollion（第三方二进制，
    #   .gitignore 里）+ 没有反编译缓存 ⇒ 保留现有产物、退出 0（不打断构建）。
    Step '1/6' '生成 DLC 链式启动边（gen_dlc_chain.py → ref\quest_chain_dlc.json）'
    & python (Join-Path $root 'tools\esm\gen_dlc_chain.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "gen_dlc_chain.py 失败（exit $LASTEXITCODE）" }
    # ★★ 第 74 轮：同伴好感度任务（固定显示的「入口」+「后续」的启动边）——
    #   gen_companion_quests.py 扫官方 Papyrus 源码核验「只能由好感度里程碑启动」，
    #   产物 ref\companion_quests.json 由 gen_quest_table.py 消费（标记 + 名字前缀 +
    #   把「后续」（承诺任务）的启动边并入链式门槛）。
    Step '1/6' '生成同伴好感度任务表（gen_companion_quests.py → ref\companion_quests.json）'
    & python (Join-Path $root 'tools\esm\gen_companion_quests.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "gen_companion_quests.py 失败（exit $LASTEXITCODE）" }
    # ★★ 第 80 轮：「提供无限任务的 NPC」入口（RAD03 贸易管理局商人 ×4 / RAD04 追踪者联盟
    #   探员 ×4）—— gp 扫 Starfield.esm 拿 REFR + 兜底候选（内景同 cell / 外景世界级），
    #   产物 ref\repeatable_givers.json 由 create_board_markers.py 与 gen_entry_table.py 消费。
    Step '1/6' '生成可重复任务 NPC 入口表（gen_repeatable_givers.py → ref\repeatable_givers.json）'
    & python (Join-Path $root 'tools\esm\gen_repeatable_givers.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "gen_repeatable_givers.py 失败（exit $LASTEXITCODE）" }
    # ★★ 第 81 轮：地球地标任务（「雪景球」收集线，10 条）——
    #   gen_landmark_quests.py 扫 Starfield.esm 核验「书上的 VMAD 属性
    #   （defaultrefoncontainerchangedto / QuestToSetOrCheck / StageToSet=100）」
    #   + 书的世界引用 + 同 cell / world 级常驻兜底，产物 ref\landmark_quests.json
    #   由 gen_quest_table.py 消费（豁免「地标」过滤 + 引导候选 + 说明文本）。
    Step '1/6' '生成地球地标任务表（gen_landmark_quests.py → ref\landmark_quests.json）'
    & python (Join-Path $root 'tools\esm\gen_landmark_quests.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "gen_landmark_quests.py 失败（exit $LASTEXITCODE）" }
    Step '1/6' '生成静态任务表（gen_quest_table.py）'
    & python (Join-Path $root 'tools\esm\gen_quest_table.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "gen_quest_table.py 失败（exit $LASTEXITCODE）" }
    Ok 'plugin\src\SAQ_QuestTable.h'
    # ★★★ 第 109 轮（大项 B）：门槛覆盖盘点报告（survey_gate_coverage.py，秒级只读分析）——
    #   产物 ref\gate_coverage.json 进了黄金快照 ⇒ 必须跟着数据一起重建（否则快照会
    #   拿旧报告比对，报出一堆假 DIFF）。**不加 --record-scan**（那是一次约 1 分钟的
    #   ESM 结构扫描，写另一个文件 ref\gate_coverage_record.json，按需手动跑）。
    #   tripwire（表内出现「可折叠形态」⇒ 报红）在 tools\test\run-all-tests.ps1 第 3 步。
    Step '1/6' '门槛覆盖盘点（survey_gate_coverage.py → ref\gate_coverage.json）'
    & python (Join-Path $root 'tools\esm\survey_gate_coverage.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "survey_gate_coverage.py 失败（exit $LASTEXITCODE）" }
    # ★ 第 30 轮：入口条目表（任务板）移到 ESM 段**之后**生成（见 2.5 步）——
    #   它的「引导目标候选链」依赖 create_board_markers.py 的产物 ref\board_markers.json。
} else { Step '1/6' '跳过静态表生成' }

# --- 2. ESM ------------------------------------------------------------------
Step '2/6' 'ESM（SAQ_ShowAvailableQuests.esm）'
if ($RebuildEsm) {
    Write-Host '    用 xEdit 重新生成（约 5 分钟，请勿打断）...'
    New-Item -ItemType Directory -Force -Path (Join-Path $root 'ref\xedit-out') | Out-Null
    Remove-Item (Join-Path $root 'ref\xedit-out\h_99_done.txt') -ErrorAction SilentlyContinue
    & (Join-Path $root 'tools\run-xedit-build.ps1') `
        -Exe (Join-Path $root 'tools\vendor\xEdit\xSFEdit64.exe') `
        -ScriptPath (Join-Path $root 'tools\xedit-scripts\build_saq.pas') `
        -DoneFile (Join-Path $root 'ref\xedit-out\h_99_done.txt') `
        -LogPath (Join-Path $root 'ref\xedit-build.log') | Write-Host
    if (-not (Test-Path $esmFresh)) { throw "xEdit 未能生成 ESM：$esmFresh（看 ref\xedit-out\h_98_exception.txt）" }
    New-Item -ItemType Directory -Force -Path (Split-Path $esmStable) | Out-Null
    Copy-Item $esmFresh $esmStable -Force
    Ok "已生成并入库 $esmStable"
} else {
    if (-not (Test-Path $esmStable)) {
        throw "缺少 $esmStable（首次构建请加 -RebuildEsm）"
    }
    Ok "复用 $esmStable"
}
# ★ 第 30 轮：先清掉上一次构建留下的 CELL 组（第 29 轮的无效 override + 旧 marker）——
#   patch_saq_esm.py 是线性重建，不认识嵌套组（文件里留着它会被拒绝运行）。
& python (Join-Path $root 'tools\esm\create_board_markers.py') --clean | Write-Host
if ($LASTEXITCODE -ne 0) { throw "create_board_markers.py --clean 失败（exit $LASTEXITCODE）" }

# ★ 无论走哪条路，都要把「引导别名 + 引导目标」补进去（xEdit 重新生成会把它冲掉）。
#   幂等，可反复运行；结构与自校验见 tools/esm/patch_saq_esm.py。
& python (Join-Path $root 'tools\esm\patch_saq_esm.py') | Write-Host
if ($LASTEXITCODE -ne 0) { throw "patch_saq_esm.py 失败（exit $LASTEXITCODE）" }

# ★ 第 30 轮：给 11 条非常驻任务板新建**常驻 XMarker 引用**（精确落点、任何位置可导航）。
#   第 29 轮的「override 成常驻」已被实机 + 数据双重否定（override 不改变引用的加载分类，
#   官方 70 条同类 override 原记录本来就是常驻）—— 详见 tools/esm/create_board_markers.py。
#   ★ 顺序：必须在 patch_saq_esm.py **之后**（那个工具是线性重建，不认识嵌套组）。
& python (Join-Path $root 'tools\esm\create_board_markers.py') | Write-Host
if ($LASTEXITCODE -ne 0) { throw "create_board_markers.py 失败（exit $LASTEXITCODE）" }

# --- 2.5 入口条目表（任务板 + 引导目标候选链）---------------------------------
# ★ 第 30 轮：gen_entry_table.py 依赖 ESM 段的产物 ref\board_markers.json（新建 marker 的
#   记录号）与 ref\entry_persistent_scan.json（同 cell 常驻兜底候选）⇒ 必须在 ESM 之后跑。
$entryHeader = Join-Path $root 'plugin\src\SAQ_EntryTable.h'
$markersJson = Join-Path $root 'ref\board_markers.json'
$scanJson    = Join-Path $root 'ref\entry_persistent_scan.json'
$needEntryTable = $true
if ($SkipTable -and (Test-Path $entryHeader) -and (Test-Path $markersJson)) {
    if ((Get-Item $entryHeader).LastWriteTime -ge (Get-Item $markersJson).LastWriteTime) {
        $needEntryTable = $false
    }
}
if ($needEntryTable) {
    if (-not (Test-Path $scanJson)) {
        Step '2.5/6' '侦查任务板 cell 里的原生常驻引用（scan_entry_persistent.py，首次，约 1~2 分钟）'
        & python (Join-Path $root 'tools\esm\scan_entry_persistent.py') | Write-Host
        if ($LASTEXITCODE -ne 0) { throw "scan_entry_persistent.py 失败（exit $LASTEXITCODE）" }
    }
    Step '2.5/6' '生成入口条目表（gen_entry_table.py：任务板 + 引导目标候选链，约 1~2 分钟）'
    & python (Join-Path $root 'tools\esm\gen_entry_table.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "gen_entry_table.py 失败（exit $LASTEXITCODE）" }
    Ok 'plugin\src\SAQ_EntryTable.h'
} else {
    Step '2.5/6' '入口条目表已是最新（跳过）'
}

# --- 3. Papyrus --------------------------------------------------------------
Step '3/6' '编译 Papyrus 脚本'
if (-not $SkipPapyrus) {
    # 坑：Starfield 的 PapyrusCompiler 处理不了含空格的路径
    # （会报 "filename does not match script name"），必须用无空格临时目录。
    $pt = Join-Path $env:TEMP 'saq_papyrus'
    Remove-Item $pt -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path "$pt\src", "$pt\out" | Out-Null
    Copy-Item (Join-Path $pexSrc '*.psc') "$pt\src" -Force
    $pscFiles = Get-ChildItem "$pt\src" -Filter '*.psc'
    foreach ($f in $pscFiles) {
        # ★ 第 49 轮：原来只回显最后 2 行，编译错误常常正好被截掉（踩过一次）—— 多给几行。
        & $papyrusCmp $f.FullName "-f=$papyrusFlags" "-i=$papyrusInc" "-o=$pt\out" 2>&1 |
            Select-Object -Last 6 | Write-Host
    }
    $pexes = Get-ChildItem "$pt\out" -Filter '*.pex' -ErrorAction SilentlyContinue
    if (-not $pexes -or $pexes.Count -lt $pscFiles.Count) {
        throw "Papyrus 编译失败（应有 $($pscFiles.Count) 个 pex，实际 $(@($pexes).Count) 个）"
    }
    New-Item -ItemType Directory -Force -Path $pexOut | Out-Null
    Copy-Item "$pt\out\*.pex" $pexOut -Force
    Ok "$($pexes.Count) 个 pex -> scripts\build\"
} else { Step '3/6' '跳过 Papyrus 编译' }

# --- 4. AS3 patch + SWF ------------------------------------------------------
Step '4/6' '同步 AS3 patch 并重编译两个 SWF'
$saqFrag = Join-Path $root 'ui\missionmenu\saqdata\SaqEmbeddedPayload.inc'

# MissionMenu.as 里留了 /*__SAQ_EMBEDDED__*/ 标记，这里把生成好的内嵌任务数据
# （SAQ_EMBEDDED_CHUNKS 的数组元素）拼进去 —— 这样源码文件保持手写可读，
# 而 SWF 里带着一份「C++ 推送失败也能用」的回退数据。
function Sync-MissionMenuPatch([string]$srcMm, [string]$srcQuestUtils, [string]$srcMissionsList, [string]$dstPatchDir) {
    if (-not (Test-Path $srcMm)) { throw "缺少 AS3 源码：$srcMm" }
    if (-not (Test-Path $srcMissionsList)) { throw "缺少 AS3 源码：$srcMissionsList" }
    if (-not (Test-Path $saqFrag)) { throw "缺少内嵌任务数据：$saqFrag（第 1 步未跑？）" }
    $text = [System.IO.File]::ReadAllText($srcMm, [System.Text.Encoding]::UTF8)
    if (-not $text.Contains('/*__SAQ_EMBEDDED__*/')) { throw "$srcMm 里找不到 /*__SAQ_EMBEDDED__*/ 标记" }
    $frag = [System.IO.File]::ReadAllText($saqFrag, [System.Text.Encoding]::UTF8)
    $text = $text.Replace('/*__SAQ_EMBEDDED__*/', "`r`n$frag`r`n")
    New-Item -ItemType Directory -Force -Path $dstPatchDir, (Join-Path $dstPatchDir 'Shared') | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $dstPatchDir 'MissionMenu.as'), $text, (New-Object System.Text.UTF8Encoding $false))
    Copy-Item $srcQuestUtils (Join-Path $dstPatchDir 'Shared\QuestUtils.as') -Force
    # MissionsList.as 也要进补丁：SAQ 条目的可见性判据在 EntryFilterCompare_Impl 里
    # （bSaqAvailable → 只看 AVAILABLE 那一位），不打进去我们那个 tab 就是空的。
    Copy-Item $srcMissionsList (Join-Path $dstPatchDir 'MissionsList.as') -Force
    Ok "$(Split-Path $dstPatchDir -Leaf)：MissionMenu.as ($($text.Length) 字符，含内嵌数据) + MissionsList.as"
}
Sync-MissionMenuPatch (Join-Path $root 'ui\missionmenu\src\MissionMenu.as') `
    (Join-Path $root 'ui\missionmenu\src\Shared\QuestUtils.as') `
    (Join-Path $root 'ui\missionmenu\src\MissionsList.as') $patchDir
& python (Join-Path $root 'tools\ui\make_lrg_source.py') | Write-Host
Sync-MissionMenuPatch (Join-Path $root 'ui\missionmenu_lrg\src\MissionMenu.as') `
    (Join-Path $root 'ui\missionmenu_lrg\src\Shared\QuestUtils.as') `
    (Join-Path $root 'ui\missionmenu_lrg\src\MissionsList.as') $patchDirLrg

if (-not $SkipSwf) {
    foreach ($job in @(
            @{ base = $baseSwf;    out = $outSwf;    patch = $patchDir },
            @{ base = $baseSwfLrg; out = $outSwfLrg; patch = $patchDirLrg })) {
        if (-not (Test-Path $job.base)) { throw "缺少基线 SWF：$($job.base)" }
        New-Item -ItemType Directory -Force -Path (Split-Path $job.out) | Out-Null
        & java -jar (Join-Path $root 'tools\ffdec\ffdec.jar') -importScript $job.base $job.out $job.patch 2>&1 |
            Select-Object -Last 1 | Write-Host
        if (-not (Test-Path $job.out)) { throw "SWF 未生成：$($job.out)" }
        $len = (Get-Item $job.out).Length
        if ($len -lt 100000) { throw "SWF 体积异常（$len B）" }
        Ok "$(Split-Path $job.out -Leaf) ($len B)"
    }
} else { Write-Host '    跳过 SWF 重编译' }

# --- 5. DLL ------------------------------------------------------------------
if (-not $SkipPlugin) {
    if ($Release -and $Harness) { throw '-Release 与 -Harness 互斥（发布版不含 harness）' }
    Step '5/6' ("编译 SFSE 插件（xmake，harness " + $(if ($Release) { '关 —— 发布构建' } else { '开' }) + "）")
    Push-Location (Join-Path $root 'plugin')
    try {
        # ★★ 第 53 轮：显式设置编译开关（y = 含 harness（默认，开发/自测）；n = 发布版）。
        #   值没变化时 xmake 直接复用现有配置、不触发重编 —— 日常构建零额外开销。
        #   ★ 踩过的坑：`xmake f` 只传 --saq_harness 会**把其它构建参数重置回默认**
        #     （实测 mode 从 releasedbg 变回 release、产物跑到 build\windows\x64\release\）
        #     ⇒ 必须每次带全套（与 xmake.lua 头部注释里的手动命令一致）。
        $harnessFlag = if ($Release) { 'n' } else { 'y' }
        & xmake f -y -p windows -a x64 -m releasedbg --vs=2022 "--saq_harness=$harnessFlag" 2>&1 |
            Select-Object -Last 1 | Write-Host
        if ($LASTEXITCODE -ne 0) { throw "xmake 配置失败（exit $LASTEXITCODE）" }
        & xmake build -y SAQ_ShowAvailableQuests 2>&1 | Select-Object -Last 2 | Write-Host
        if ($LASTEXITCODE -ne 0) { throw "xmake 构建失败（exit $LASTEXITCODE）" }
    } finally { Pop-Location }
    if (-not (Test-Path $outDll)) { throw "DLL 未生成：$outDll" }
    Ok (Split-Path $outDll -Leaf)
} else { Step '5/6' '跳过 DLL 构建' }

# --- 6. 部署 -----------------------------------------------------------------
if (-not $SkipDeploy) {
    Step '6/6' "部署到 MO2：$modName"
    $dest = Join-Path $mo2Mods $modName
    foreach ($sub in @('SFSE\Plugins', 'Interface', 'Scripts')) {
        New-Item -ItemType Directory -Force -Path (Join-Path $dest $sub) | Out-Null
    }
    Copy-Item $outDll (Join-Path $dest 'SFSE\Plugins\SAQ_ShowAvailableQuests.dll') -Force
    Copy-Item $outSwf (Join-Path $dest 'Interface\missionmenu.swf') -Force
    Copy-Item $outSwfLrg (Join-Path $dest 'Interface\missionmenu_lrg.swf') -Force
    Copy-Item $esmStable (Join-Path $dest $esmName) -Force
    Copy-Item (Join-Path $pexOut '*.pex') (Join-Path $dest 'Scripts') -Force

    # ★ 第 23 轮：预置空的日志文件 —— MO2 的 usvfs 会把「写 mod 目录里已存在的文件」
    #   重定向回 mod 目录；否则插件新建的日志会落到 overwrite，删 mod 时留下残留
    #   （玩家要求：日志/配置不放 C 盘、删 mod 不残留）。
    $logPath = Join-Path $dest 'SFSE\Plugins\SAQ_ShowAvailableQuests.log'
    if (-not (Test-Path $logPath)) {
        New-Item -ItemType File -Path $logPath -Force | Out-Null
        Write-Host '    已预置空日志文件（让 MO2 把日志写入重定向回 mod 目录）'
    }

    # 配置文件（测试开关）模板已入库（resources\），只在 mod 目录里没有时补一份 ——
    # 已存在则保留（测试时可能改过 Mode，不能被部署覆盖）。
    $iniDest = Join-Path $dest 'SFSE\Plugins\SAQ_ShowAvailableQuests.ini'
    if (-not (Test-Path $iniDest)) {
        Copy-Item (Join-Path $root 'resources\SAQ_ShowAvailableQuests.ini') $iniDest -Force
        Write-Host '    已放入配置文件模板（SFSE\Plugins\SAQ_ShowAvailableQuests.ini）'
    }

    # ★ 第 49 轮（引擎内 harness）：
    #   ① 用例文件（tools\test\scenarios\SAQ_TestPlan.txt）拷进插件目录；
    #   ② 预建空的 SAQ_testresults.json —— MO2 的 usvfs 会「写 mod 目录里已存在的文件」
    #      重定向回 mod 目录，否则 harness 新建的结果文件会落到 overwrite 里；
    #   ③ 保证 ini 的 [Test] 段有 Harness / Plan 两个键（**不改已有值**；-Harness 才强制 1）。
    #   ★ 第 53 轮（大项 F · 发布就绪）：-Release（发布构建）时整段跳过 ——
    #   发布版 DLL 里没有 harness，测试用例/结果文件也不该出现在部署里。
    if (-not $Release) {
    $pluginDest = Join-Path $dest 'SFSE\Plugins'
    Copy-Item (Join-Path $root 'tools\test\scenarios\SAQ_TestPlan.txt') `
        (Join-Path $pluginDest 'SAQ_TestPlan.txt') -Force
    $resDest = Join-Path $pluginDest 'SAQ_testresults.json'
    if (-not (Test-Path $resDest)) {
        [System.IO.File]::WriteAllText($resDest, '{}', (New-Object System.Text.UTF8Encoding $false))
    }
    if (Test-Path $iniDest) {
        $iniText = [System.IO.File]::ReadAllText($iniDest, [System.Text.Encoding]::UTF8)
        $iniChanged = $false
        # ★★ 第 49 轮踩坑：Harness / Plan **必须落在 [Test] 段里** —— 第一版是「追加到文件
        #   末尾」，而 [Test] 段在文件中间 ⇒ 两个键落进了 [Filter] 段，
        #   GetPrivateProfileInt("Test", …) 读不到 ⇒ harness 静默不跑（实机表现为「进游戏
        #   什么也没发生」）。现在改成「插在 [Test] 行之后」。
        $newKeys = @()
        if ($iniText -notmatch '(?m)^\s*Harness\s*=') {
            $newKeys += '; ★ 第 49 轮：引擎内自动化测试（1=启用；普通玩家保持 0；改 0→1 不必重启游戏）'
            $newKeys += 'Harness=0'
        }
        if ($iniText -notmatch '(?m)^\s*Plan\s*=') {
            $newKeys += '; 用例文件（相对插件目录）—— 见 tools\test\scenarios'
            $newKeys += 'Plan=SAQ_TestPlan.txt'
        }
        # ★★ 第 62 轮补：主菜单自动读档 —— 存档名子串（空 = 关）。只补键、不改值。
        if ($iniText -notmatch '(?m)^\s*AutoLoad\s*=') {
            $newKeys += '; ★★ 第 62 轮：主菜单自动读档（存档名子串；空 = 关）—— 启动游戏按任意键后自动读它再跑用例'
            $newKeys += 'AutoLoad='
        }
        if ($newKeys.Count -gt 0) {
            # ★★ 第 62 轮补踩坑（实机症状：AutoLoad 落到文件末尾的**第二个 [Test] 段**里）：
            #   老实现用 `-split "`r`n"` 定位 [Test] 行 —— 而模板 ini 是**LF 换行**
            #   ⇒ 整个文件被当成一行、找不到 [Test] ⇒ 走「追加到末尾」分支，于是出现
            #   重复段（Windows 的 INI 读取对重复段行为不可依赖 ⇒ 键可能读不到）。
            #   现在改用 regex 在**第一个** [Test] 行后插入（对 LF / CRLF 都安全）。
            $insert = ($newKeys -join "`r`n")
            if ($iniText -match '(?m)^\s*\[Test\]\s*$') {
                $iniText = $iniText -replace '(?m)^(\s*\[Test\]\s*)$', "`$1`r`n$insert"
            } else {
                $iniText = $iniText.TrimEnd() + "`r`n[Test]`r`n$insert`r`n"
            }
            $iniChanged = $true
        }
        if ($Harness) {
            $iniText = [regex]::Replace($iniText, '(?m)^\s*Harness\s*=.*$', 'Harness=1')
            $iniChanged = $true
        }
        if ($AutoLoad -ne '') {
            # 键一定已存在（上面 newKeys 补过）；这里强制写入指定存档子串。
            $iniText = [regex]::Replace($iniText, '(?m)^\s*AutoLoad\s*=.*$', "AutoLoad=$AutoLoad")
            $iniChanged = $true
        }
        if ($iniChanged) {
            # 带 BOM 写回（ini 里有中文注释，记事本按 UTF-8 认）
            [System.IO.File]::WriteAllText($iniDest, $iniText, (New-Object System.Text.UTF8Encoding $true))
            Write-Host ("    已更新测试开关 ini：Harness=" + $(if ($Harness) { '1（本轮 -Harness）' } else { '保持原值' }))
        }
    }
    } else {
        Write-Host '    发布构建：跳过测试资产部署（不拷用例文件、不动 ini 测试键）'
    }

    $meta = Join-Path $dest 'meta.ini'
    # ★ 第 53 轮（大项 F）：meta.ini 的版本号与 xmake.lua / main.cpp 同步（本次 0.1.12）。
    #   老逻辑只在文件不存在时创建 ⇒ 升级版本后 MO2 里显示的还是旧版本号。
    $metaVer = '0.1.12'
    if (-not (Test-Path $meta)) {
        @"
[General]
modid=0
version=$metaVer
newestVersion=$metaVer
category="-1,"
installationFile=
"@ | Set-Content -Path $meta -Encoding ASCII
    } else {
        $mt = [System.IO.File]::ReadAllText($meta)
        $mt2 = [regex]::Replace($mt, '(?m)^version=.*$', "version=$metaVer")
        $mt2 = [regex]::Replace($mt2, '(?m)^newestVersion=.*$', "newestVersion=$metaVer")
        if ($mt2 -ne $mt) {
            [System.IO.File]::WriteAllText($meta, $mt2)
            Write-Host "    已同步 meta.ini 版本号 -> $metaVer"
        }
    }

    # ESM 必须在 MO2 的 plugins.txt 里启用
    $pluginsTxt = 'D:\Mod Organizer 2\starfield_mods\profiles\Default\plugins.txt'
    if (Test-Path $pluginsTxt) {
        $lines = [System.IO.File]::ReadAllLines($pluginsTxt)
        if (-not ($lines -contains "*$esmName")) {
            $out = @($lines[0], "*$esmName") + $lines[1..($lines.Count - 1)]
            [System.IO.File]::WriteAllLines($pluginsTxt, $out, (New-Object System.Text.UTF8Encoding $false))
            Write-Host "    已写入 MO2 plugins.txt"
        }
    } else {
        Write-Host "    !! 找不到 MO2 plugins.txt，需手工启用 $esmName" -ForegroundColor Red
    }
    Ok $dest
} else { Step '6/6' '跳过部署' }

Write-Host ''
Write-Host 'Done.' -ForegroundColor Cyan
Write-Host '提醒：MO2 若在运行中，请重启 MO2 让 modlist/plugins.txt 生效。' -ForegroundColor DarkGray
