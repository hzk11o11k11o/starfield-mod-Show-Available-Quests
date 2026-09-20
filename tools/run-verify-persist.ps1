# ============================================================================
#  run-verify-persist.ps1 —— 用 xEdit 验证「任务板入口常驻化」override（第 29 轮）
#
#  做什么：
#    1. 把 esm\SAQ_ShowAvailableQuests.esm 临时复制到游戏 Data 目录
#       （xEdit 只从 Data 目录读插件；跑完会删掉副本）；
#    2. 确保 tools\plugins.txt 里启用它；
#    3. 无头运行 xEdit（verify_persist.pas）：dump CELL 组树 + 重存一份 SAQ_resaved.esm；
#    4. 打印 ref\xedit-out\verify_persist.txt（组名 / 每条记录的 FormID / flags）。
#
#  判据（第 29 轮已通过一次）：
#    * 11 条 REFR 都在 `Cell Persistent Children of <cell>` 组里；
#    * FormID 是 00xxxxxx（属于 Starfield.esm 空间的 **override**，不是新记录）；
#    * 重存的 SAQ_resaved.esm 里 11 条记录仍在（xEdit 读懂 = 结构合法）。
#
#  用法：& ".\tools\run-verify-persist.ps1"        # 约 4~5 分钟
# ============================================================================
param(
    [int]$TimeoutSec = 1800
)
$ErrorActionPreference = 'Stop'
$root   = Split-Path -Parent $PSScriptRoot
$esm    = Join-Path $root 'esm\SAQ_ShowAvailableQuests.esm'
$data   = 'D:\SteamLibrary\steamapps\common\Starfield\Data'
$target = Join-Path $data 'SAQ_ShowAvailableQuests.esm'
$outDir = Join-Path $root 'ref\xedit-out'

Write-Host '--- 0. 前置检查 ---'
if (-not (Test-Path $esm)) { throw "缺少 $esm（先跑 build-saq.ps1）" }
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
Remove-Item (Join-Path $outDir 'v_done.txt') -ErrorAction SilentlyContinue

Write-Host '--- 1. 复制 ESM 到游戏 Data 目录（临时） ---'
Copy-Item $esm $target -Force
$plugins = Join-Path $root 'tools\plugins.txt'
$lines = @(Get-Content $plugins)
if (-not ($lines -contains '*SAQ_ShowAvailableQuests.esm')) {
    $lines += '*SAQ_ShowAvailableQuests.esm'
    Set-Content $plugins $lines -Encoding ascii
    Write-Host '  plugins.txt 已补上 SAQ_ShowAvailableQuests.esm'
}

try {
    Write-Host '--- 2. 无头运行 xEdit（约 4~5 分钟） ---'
    & (Join-Path $root 'tools\run-xedit.ps1') `
        -Exe (Join-Path $root 'tools\vendor\xEdit\xSFEdit64.exe') `
        -ScriptPath (Join-Path $root 'tools\xedit-scripts\verify_persist.pas') `
        -DoneFile (Join-Path $outDir 'v_done.txt') `
        -LogPath (Join-Path $root 'ref\xedit-verify.log') `
        -TimeoutSec $TimeoutSec | Select-Object -Last 5 | Write-Host
} finally {
    Write-Host '--- 3. 清理 Data 目录里的临时副本 ---'
    Remove-Item $target -ErrorAction SilentlyContinue
}

Write-Host '--- 4. 验证结果 ---'
$rep = Join-Path $outDir 'verify_persist.txt'
if (Test-Path $rep) { Get-Content $rep } else { Write-Host '!! 没有 verify_persist.txt（xEdit 没跑到脚本？看 ref\xedit-verify.log）' }
