# ============================================================================
#  Show Available Quests - 一键构建 + 部署
#
#  用法（必须 pwsh 7，直接 & 调用，不要再套一层 pwsh）：
#     & ".\tools\build-saq.ps1"                 # 全流程（ESM 复用已有产物）
#     & ".\tools\build-saq.ps1" -RebuildEsm     # 用 xEdit 重新生成 ESM（约 5 分钟）
#     & ".\tools\build-saq.ps1" -SkipTable -SkipSwf     # 只重编 DLL
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
    [switch]$Harness
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
    #   这里只做交叉分析（快）：info_gates.json + 候选表 → ref\info_gates_final.json。
    Step '1/6' '生成 INFO 门槛（analyze_info_gates.py → ref\info_gates_final.json）'
    & python (Join-Path $root 'tools\esm\analyze_info_gates.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "analyze_info_gates.py 失败（exit $LASTEXITCODE）" }
    Step '1/6' '生成静态任务表（gen_quest_table.py）'
    & python (Join-Path $root 'tools\esm\gen_quest_table.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "gen_quest_table.py 失败（exit $LASTEXITCODE）" }
    Ok 'plugin\src\SAQ_QuestTable.h'
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
    Step '5/6' '编译 SFSE 插件（xmake）'
    Push-Location (Join-Path $root 'plugin')
    try {
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
        if ($iniText -notmatch '(?m)^\s*Harness\s*=') {
            $iniText = $iniText.TrimEnd() + "`r`n; ★ 第 49 轮：引擎内自动化测试（1=启用；普通玩家保持 0）`r`nHarness=0`r`n"
            $iniChanged = $true
        }
        if ($iniText -notmatch '(?m)^\s*Plan\s*=') {
            $iniText = $iniText.TrimEnd() + "`r`n; 用例文件（相对插件目录）—— 见 tools\test\scenarios`r`nPlan=SAQ_TestPlan.txt`r`n"
            $iniChanged = $true
        }
        if ($Harness) {
            $iniText = [regex]::Replace($iniText, '(?m)^\s*Harness\s*=.*$', 'Harness=1')
            $iniChanged = $true
        }
        if ($iniChanged) {
            # 带 BOM 写回（ini 里有中文注释，记事本按 UTF-8 认）
            [System.IO.File]::WriteAllText($iniDest, $iniText, (New-Object System.Text.UTF8Encoding $true))
            Write-Host ("    已更新测试开关 ini：Harness=" + $(if ($Harness) { '1（本轮 -Harness）' } else { '保持原值' }))
        }
    }

    $meta = Join-Path $dest 'meta.ini'
    if (-not (Test-Path $meta)) {
        @"
[General]
modid=0
version=0.1.0
newestVersion=0.1.0
category="-1,"
installationFile=
"@ | Set-Content -Path $meta -Encoding ASCII
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
