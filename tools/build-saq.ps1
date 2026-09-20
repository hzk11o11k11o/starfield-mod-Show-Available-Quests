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
    [switch]$SkipDeploy
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
    Step '1/6' '生成静态任务表（gen_quest_table.py）'
    & python (Join-Path $root 'tools\esm\gen_quest_table.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "gen_quest_table.py 失败（exit $LASTEXITCODE）" }
    Ok 'plugin\src\SAQ_QuestTable.h'
    # ★ 第 27 轮：无限任务入口（任务板）条目表（扫 Starfield.esm 的世界引用，约 1~2 分钟）
    Step '1/6' '生成入口条目表（gen_entry_table.py：任务板引用）'
    & python (Join-Path $root 'tools\esm\gen_entry_table.py') | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "gen_entry_table.py 失败（exit $LASTEXITCODE）" }
    Ok 'plugin\src\SAQ_EntryTable.h'
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
# ★ 无论走哪条路，都要把「引导别名 + 引导目标」补进去（xEdit 重新生成会把它冲掉）。
#   幂等，可反复运行；结构与自校验见 tools/esm/patch_saq_esm.py。
& python (Join-Path $root 'tools\esm\patch_saq_esm.py') | Write-Host

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
        & $papyrusCmp $f.FullName "-f=$papyrusFlags" "-i=$papyrusInc" "-o=$pt\out" 2>&1 |
            Select-Object -Last 2 | Write-Host
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
