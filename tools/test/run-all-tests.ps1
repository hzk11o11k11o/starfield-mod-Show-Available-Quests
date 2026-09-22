# ============================================================================
#  run-all-tests.ps1 —— 离线测试一键（第 64 轮 · 大项 K）
#
#  跑三件事（都不需要游戏、秒级）：
#    ① 决策单元测试（plugin/tests，纯 C++，不链接 commonlibsf）；
#    ② 数据管线黄金快照（tools/test/golden_snapshot.py）；
#    ③ 门槛覆盖盘点 tripwire（tools/esm/survey_gate_coverage.py --check）——
#       ★ 第 109 轮（大项 B）：表内任务一旦出现「可折叠」的 operator 形态
#       （!= / > / >= / < / <= + cmp∈{0,1} + 前置已解析）⇒ 报红，
#       说明 operator 二期需要产品化（折叠规则见 docs/08 4.6）。
#       ★ 只读、不写报告（完整报告用 `--record-scan` 手动跑）。
#  退出码 = 0 全过。
#
#  引擎内 harness（要开游戏、覆盖「引擎时序」）不在这里 —— 见 docs\09。
#  = 分工总览（docs\10）：本脚本 = 逻辑 + 数据 + 覆盖监视；harness = 时序；verify = 产物特征。
# ============================================================================
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$root = Split-Path (Split-Path $here -Parent) -Parent
$failed = @()

# 子进程（测试 exe / python）按 UTF-8 输出中文 —— 让 PowerShell 按 UTF-8 解码。
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host '=== (1/3) 决策单元测试（离线层） ===' -ForegroundColor Cyan
& (Join-Path $here 'run-decision-tests.ps1')
if ($LASTEXITCODE -ne 0) { $failed += '决策单元测试' }

Write-Host ''
Write-Host '=== (2/3) 数据管线黄金快照 ===' -ForegroundColor Cyan
& python (Join-Path $here 'golden_snapshot.py')
if ($LASTEXITCODE -ne 0) { $failed += '数据管线黄金快照' }

Write-Host ''
Write-Host '=== (3/3) 门槛覆盖盘点 tripwire（大项 B） ===' -ForegroundColor Cyan
& python (Join-Path $root 'tools/esm/survey_gate_coverage.py') --check
if ($LASTEXITCODE -ne 0) { $failed += '门槛覆盖 tripwire' }

Write-Host ''
if ($failed.Count -eq 0) {
    Write-Host '离线测试全部通过。' -ForegroundColor Green
    exit 0
}
Write-Host ("离线测试有失败：{0}" -f ($failed -join '、')) -ForegroundColor Red
exit 1
