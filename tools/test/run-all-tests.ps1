# ============================================================================
#  run-all-tests.ps1 —— 离线测试一键（第 64 轮 · 大项 K）
#
#  跑五件事（都不需要游戏、秒级）：
#    ① 决策单元测试（plugin/tests，纯 C++，不链接 commonlibsf）；
#    ② CTDA 运算符折叠内核自检（tools/esm/ctda_ops.py --self-test）——
#       ★ 第 128 轮（operator 二期）：真值表（!= / > / >= / < / <= 折叠成
#       want / 恒真 / 恒假）+ OR 组边界 + 组装（含常量处置）逐条钉死；
#    ③ 数据管线黄金快照（tools/test/golden_snapshot.py）；
#    ④ 门槛覆盖盘点 tripwire（tools/esm/survey_gate_coverage.py --check）——
#       ★ 第 128 轮（operator 二期落地后）报红条件换成两类：
#         ① 表内出现「折叠已覆盖」形态（应已被收进门槛）⇒ 扫描没重跑 / 折叠退化；
#         ② 表内出现「折叠管不到」形态（flags 非 OR / cmp∉{0,1}）⇒ 后续阶段对象。
#       ★ 只读、不写报告（完整报告用 `--record-scan` 手动跑）。
#    ⑤ P2 计划 `assert.log` 正则自检（tools/test/p2_plan_regex_check.py）——
#       ★ 第 130 轮：p2 计划的断言正则在**解析期**由 DLL 编译（非法 ⇒ 用例 FAIL，
#       第 68 轮）；这一步在离线阶段就把「正则合法 + 能匹配预期产品行」验一遍
#       （补 verify 只查存在性、不查正则语义的缺口）。
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

Write-Host '=== (1/5) 决策单元测试（离线层） ===' -ForegroundColor Cyan
& (Join-Path $here 'run-decision-tests.ps1')
if ($LASTEXITCODE -ne 0) { $failed += '决策单元测试' }

Write-Host ''
Write-Host '=== (2/5) CTDA 运算符折叠内核自检（operator 二期） ===' -ForegroundColor Cyan
& python (Join-Path $root 'tools/esm/ctda_ops.py') --self-test
if ($LASTEXITCODE -ne 0) { $failed += '折叠内核自检' }

Write-Host ''
Write-Host '=== (3/5) 数据管线黄金快照 ===' -ForegroundColor Cyan
& python (Join-Path $here 'golden_snapshot.py')
if ($LASTEXITCODE -ne 0) { $failed += '数据管线黄金快照' }

Write-Host ''
Write-Host '=== (4/5) 门槛覆盖盘点 tripwire（大项 B / operator 二期） ===' -ForegroundColor Cyan
& python (Join-Path $root 'tools/esm/survey_gate_coverage.py') --check
if ($LASTEXITCODE -ne 0) { $failed += '门槛覆盖 tripwire' }

Write-Host ''
Write-Host '=== (5/5) P2 计划断言正则自检（第 130 轮） ===' -ForegroundColor Cyan
& python (Join-Path $here 'p2_plan_regex_check.py')
if ($LASTEXITCODE -ne 0) { $failed += 'P2 计划正则自检' }

Write-Host ''
if ($failed.Count -eq 0) {
    Write-Host '离线测试全部通过。' -ForegroundColor Green
    exit 0
}
Write-Host ("离线测试有失败：{0}" -f ($failed -join '、')) -ForegroundColor Red
exit 1
