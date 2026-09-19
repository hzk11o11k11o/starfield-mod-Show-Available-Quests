# ============================================================================
#  Show Available Quests - 一键构建 + 部署
#
#  用法（必须 pwsh 7）：
#     pwsh -File tools\build-saq.ps1                    # 全流程
#     pwsh -File tools\build-saq.ps1 -SkipTable         # 跳过静态表重新生成
#     pwsh -File tools\build-saq.ps1 -SkipPlugin        # 只重编 SWF
#     pwsh -File tools\build-saq.ps1 -SkipSwf           # 只重编 DLL
#     pwsh -File tools\build-saq.ps1 -SkipDeploy        # 只构建不部署
#
#  产物：
#     plugin\build\windows\x64\releasedbg\SAQ_ShowAvailableQuests.dll
#     ui\missionmenu\build\missionmenu.swf
#  部署到：
#     D:\Mod Organizer 2\starfield_mods\mods\Show Available Quests (SFSE)\
# ============================================================================
param(
    [switch]$SkipTable,
    [switch]$SkipPlugin,
    [switch]$SkipSwf,
    [switch]$SkipDeploy
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$mo2Mods = 'D:\Mod Organizer 2\starfield_mods\mods'
$modName = 'Show Available Quests (SFSE)'

$gameData = 'D:\SteamLibrary\steamapps\common\Starfield\Data'
# 基线 SWF（从 Starfield - Interface.ba2 提取的原版任务菜单，已入库）
$baseSwf  = Join-Path $root 'ui\missionmenu\base\missionmenu.swf'
$patchDir = Join-Path $root 'ui\missionmenu\patch'
$outSwf   = Join-Path $root 'ui\missionmenu\build\missionmenu.swf'
$outDll   = Join-Path $root 'plugin\build\windows\x64\releasedbg\SAQ_ShowAvailableQuests.dll'

function Step($n, $msg) { Write-Host "[$n] $msg" -ForegroundColor Yellow }
function Ok($msg) { Write-Host "    OK: $msg" -ForegroundColor Green }

# --- 0. 前置检查 -------------------------------------------------------------
if (-not (Test-Path $baseSwf)) {
    throw "缺少反编译基底 SWF：$baseSwf（先从 Starfield - Interface.ba2 提取）"
}
if (-not (Test-Path (Join-Path $root 'ref\quests.json'))) {
    throw "缺少 ref\quests.json（先用 tools/esm/quest_dump.py 导出）"
}

# --- 1. 静态表（FormID -> 中/英文名 + 类型） --------------------------------
if (-not $SkipTable) {
    Step '1/5' '生成静态任务表（gen_quest_table.py）'
    & python (Join-Path $root 'tools\esm\gen_quest_table.py') | Write-Host
    Ok 'plugin\src\SAQ_QuestTable.h'
} else { Step '1/5' '跳过静态表生成' }

# --- 2. 同步 patch 目录（只放被改过的 AS3） ---------------------------------
Step '2/5' '同步 AS3 patch 目录'
$patchShared = Join-Path $patchDir 'Shared'
New-Item -ItemType Directory -Force -Path $patchShared | Out-Null
Copy-Item (Join-Path $root 'ui\missionmenu\src\MissionMenu.as') (Join-Path $patchDir 'MissionMenu.as') -Force
Copy-Item (Join-Path $root 'ui\missionmenu\src\Shared\QuestUtils.as') (Join-Path $patchShared 'QuestUtils.as') -Force
Ok 'patch\MissionMenu.as, patch\Shared\QuestUtils.as'

# --- 3. 编译 DLL -------------------------------------------------------------
if (-not $SkipPlugin) {
    Step '3/5' '编译 SFSE 插件（xmake）'
    Push-Location (Join-Path $root 'plugin')
    try {
        & xmake build -y SAQ_ShowAvailableQuests 2>&1 | Select-Object -Last 3 | Write-Host
        if ($LASTEXITCODE -ne 0) { throw "xmake 构建失败（exit $LASTEXITCODE）" }
    } finally { Pop-Location }
    if (-not (Test-Path $outDll)) { throw "DLL 未生成：$outDll" }
    Ok $outDll
} else { Step '3/5' '跳过 DLL 构建' }

# --- 4. 重编译 SWF（FFDec 批量导入脚本） ------------------------------------
if (-not $SkipSwf) {
    Step '4/5' '重编译 missionmenu.swf（FFDec）'
    New-Item -ItemType Directory -Force -Path (Split-Path $outSwf) | Out-Null
    & java -jar (Join-Path $root 'tools\ffdec\ffdec.jar') -importScript $baseSwf $outSwf $patchDir 2>&1 |
        Select-Object -Last 2 | Write-Host
    if (-not (Test-Path $outSwf)) { throw "SWF 未生成：$outSwf" }
    $len = (Get-Item $outSwf).Length
    if ($len -lt 100000) { throw "SWF 体积异常（$len B），疑似编译失败" }
    Ok "$outSwf ($len B)"
} else { Step '4/5' '跳过 SWF 重编译' }

# --- 5. 部署到 MO2 -----------------------------------------------------------
if (-not $SkipDeploy) {
    Step '5/5' "部署到 MO2：$modName"
    $dest = Join-Path $mo2Mods $modName
    $destPlugin = Join-Path $dest 'SFSE\Plugins'
    $destIfc    = Join-Path $dest 'Interface'
    New-Item -ItemType Directory -Force -Path $destPlugin, $destIfc | Out-Null

    Copy-Item $outDll $destPlugin -Force
    Copy-Item $outSwf (Join-Path $destIfc 'missionmenu.swf') -Force

    # MO2 的 meta.ini（不存在才写，避免覆盖用户改过的版本）
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
    Ok $dest
} else { Step '5/5' '跳过部署' }

Write-Host ''
Write-Host 'Done.' -ForegroundColor Cyan
