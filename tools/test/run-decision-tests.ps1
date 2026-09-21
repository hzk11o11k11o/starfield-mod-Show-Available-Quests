# ============================================================================
#  run-decision-tests.ps1 —— 一键跑「离线层单元测试」（第 64 轮 · 大项 K）
#
#  毫秒级、零游戏：编译 plugin\tests 的 SAQ_Tests（纯 C++，**不链接 commonlibsf**）
#  并运行；退出码 = 测试结果（0 = 全过）—— 可直接接进任何 CI/脚本。
#
#  用法：
#      & ".\tools\test\run-decision-tests.ps1"             # 构建 + 跑（推荐）
#      & ".\tools\test\run-decision-tests.ps1" -SkipBuild  # 只跑（用已构建的产物）
#
#  与 harness 的分工：
#    · 本脚本（离线层）：过滤 / 门槛 / 候选池 / 引导复算的**决策组合**（毫秒级）；
#    · harness（engine 内用例）：真实**引擎时序**（要开游戏，见 docs\09）。
# ============================================================================
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # tools\test → 项目根

# 测试程序按 UTF-8 输出（MiniTest 的中文用例名）—— 让 PowerShell 按 UTF-8 解码，
# 否则中文在管道里会按 GBK 解读成乱码。
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Push-Location (Join-Path $root 'plugin')
try {
    if (-not $SkipBuild) {
        Write-Host '[离线层] 构建 SAQ_Tests（纯 C++，不链接 commonlibsf）' -ForegroundColor Yellow
        & xmake build -y SAQ_Tests 2>&1 | Select-Object -Last 2 | Write-Host
        if ($LASTEXITCODE -ne 0) { throw "SAQ_Tests 构建失败（exit $LASTEXITCODE）" }
    }
} finally {
    Pop-Location
}

# 直接运行 exe（不走 `xmake run`：它会把子进程退出码折成 -1，中文也过一层管道）。
$exe = Get-ChildItem -Path (Join-Path $root 'plugin\build') -Recurse -Filter 'SAQ_Tests.exe' `
        -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $exe) { throw '找不到 SAQ_Tests.exe —— 先去掉 -SkipBuild 构建一次' }

Write-Host '[离线层] 运行决策单元测试' -ForegroundColor Yellow
& $exe.FullName
$code = $LASTEXITCODE

if ($code -eq 0) {
    Write-Host '[离线层] 全部通过。' -ForegroundColor Green
} else {
    Write-Host "[离线层] 有失败（exit $code）—— 看上面的 [FAIL] 行。" -ForegroundColor Red
}
exit $code
