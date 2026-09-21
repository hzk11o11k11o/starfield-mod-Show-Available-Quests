# ============================================================================
#  run-all-tests.ps1 —— 离线测试一键（第 64 轮 · 大项 K）
#
#  跑两件事（都不需要游戏、秒级）：
#    ① 决策单元测试（plugin/tests，纯 C++，不链接 commonlibsf）；
#    ② 数据管线黄金快照（tools/test/golden_snapshot.py）。
#  退出码 = 0 全过。
#
#  引擎内 harness（要开游戏、覆盖「引擎时序」）不在这里 —— 见 docs\09。
#  = 分工总览（docs\10）：本脚本 = 逻辑 + 数据；harness = 时序；verify = 产物特征。
# ============================================================================
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$failed = @()

# 子进程（测试 exe / python）按 UTF-8 输出中文 —— 让 PowerShell 按 UTF-8 解码。
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host '=== (1/2) 决策单元测试（离线层） ===' -ForegroundColor Cyan
& (Join-Path $here 'run-decision-tests.ps1')
if ($LASTEXITCODE -ne 0) { $failed += '决策单元测试' }

Write-Host ''
Write-Host '=== (2/2) 数据管线黄金快照 ===' -ForegroundColor Cyan
& python (Join-Path $here 'golden_snapshot.py')
if ($LASTEXITCODE -ne 0) { $failed += '数据管线黄金快照' }

Write-Host ''
if ($failed.Count -eq 0) {
    Write-Host '离线测试全部通过。' -ForegroundColor Green
    exit 0
}
Write-Host ("离线测试有失败：{0}" -f ($failed -join '、')) -ForegroundColor Red
exit 1
