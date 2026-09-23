# ============================================================================
#  Show Available Quests - 打包 Nexus 上传包
#
#  用法（pwsh 7）：
#     & ".\tools\package-saq.ps1"                   # 默认按 v0.1.16 打包
#     & ".\tools\package-saq.ps1" -Version 0.2.0    # 指定版本号
#     & ".\tools\package-saq.ps1" -SkipVerify       # 跳过产物特征校验
#     & ".\tools\package-saq.ps1" -SkipBuild        # 不重新构建（用当前产物，调试用）
#
#  产物：
#     dist\SAQ-ShowAvailableQuests-<版本>.zip   ← 上传包（zip 根 = mod 根结构）
#     dist\nexus-description.md                ← Nexus 文案（不进压缩包）
#
#  说明：
#     · zip 根就是 mod 根：MO2 可直接「从压缩包安装」；
#       手动安装 = 把包内 SFSE\ / Interface\ / Scripts\ 与 esm 放进 Starfield\Data\
#     · 包内 README.txt 的 {{VERSION}} 会替换为本次版本号
#     · 打包前会跑 tools\ui\verify_saq_build.py（产物特征检查），失败即终止
#     · ★★ 第 62 轮（用户要求）：包里**不含任何测试资产**、配置**强制还原成正常玩的
#       默认值** —— 打包清单里没有 SAQ_TestPlan.txt / SAQ_testresults.json；包内 ini 的
#       [Test] 段（Mode / Harness）在组装时被强制写回 0 并校验（见第 4/5 步）。
#
#  ★★ 第 53 轮（大项 F · 发布就绪）：本脚本现在**自己完成发布构建** ——
#     ① 以 xmake `saq_harness=n` 重新编译 DLL（DLL 里彻底没有 harness/测试代码）
#        并部署到 MO2（让「部署 == 包内容」，第 50 轮的教训）；
#     ② 用 `verify_saq_build.py --release` 反向校验（DLL 里**不允许**出现任何
#        harness 特征；这一步能挡住「配置没切过去、带着测试代码打包」）；
#     ③ 然后才组装/压缩。
#     打完包后，工作区与 MO2 部署都是**发布构建**；要回到开发构建（含 harness）：
#       & ".\tools\build-saq.ps1" -SkipTable -SkipSwf -SkipPapyrus -Harness
# ============================================================================
param(
    [string]$Version = '0.1.16',
    [switch]$SkipVerify,
    # ★ 第 53 轮：跳过「发布构建 + 部署」这一步（用当前产物打包 —— 只用于调试脚本本身；
    #   正常打包必须让它跑，否则可能把含 harness 的 DLL 打进包里）。
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$root     = Split-Path -Parent $PSScriptRoot
$distDir  = Join-Path $root 'dist'
$stageDir = Join-Path $distDir 'stage'
$zipPath  = Join-Path $distDir "SAQ-ShowAvailableQuests-$Version.zip"

function Step($msg) { Write-Host "[打包] $msg" -ForegroundColor Yellow }
function Ok($msg)   { Write-Host "    OK: $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !! $msg" -ForegroundColor Red }

# --- 0. 版本一致性（只提醒，不阻断）------------------------------------------
# 版本号有三个来源：本脚本参数 / xmake.lua / main.cpp 的启动日志串。
# 升级版本时三处要一起改，这里主动点名，避免「包名 0.2.0 但 DLL 里还是 0.1.0」。
foreach ($f in @((Join-Path $root 'plugin\xmake.lua'), (Join-Path $root 'plugin\src\main.cpp'))) {
    $txt = [System.IO.File]::ReadAllText($f, [System.Text.Encoding]::UTF8)
    if ($txt -notmatch [regex]::Escape($Version)) {
        Warn "版本号不同步：$(Split-Path $f -Leaf) 里没有 $Version（打包继续，但建议先改齐）"
    }
}

# --- 1. 发布构建 + 部署（★ 第 53 轮：DLL 不含 harness）------------------------
if (-not $SkipBuild) {
    Step '1/5 发布构建 + 部署（xmake saq_harness=n —— DLL 里没有 harness）'
    & (Join-Path $root 'tools\build-saq.ps1') -Release -SkipTable -SkipSwf -SkipPapyrus
    Ok 'DLL 已按发布构建重编，并部署到 MO2（部署 == 即将打包的内容）'
} else {
    Step '1/5 跳过发布构建（-SkipBuild —— 请自行确认产物是发布构建）'
}

# --- 2. 产物清单（zip 根 = mod 根）-------------------------------------------
$items = @(
    @{ src = 'esm\SAQ_ShowAvailableQuests.esm';                                 dst = 'SAQ_ShowAvailableQuests.esm' },
    @{ src = 'plugin\build\windows\x64\releasedbg\SAQ_ShowAvailableQuests.dll'; dst = 'SFSE\Plugins\SAQ_ShowAvailableQuests.dll' },
    @{ src = 'ui\missionmenu\build\missionmenu.swf';                            dst = 'Interface\missionmenu.swf' },
    @{ src = 'ui\missionmenu_lrg\build\missionmenu_lrg.swf';                    dst = 'Interface\missionmenu_lrg.swf' },
    @{ src = 'scripts\build\SAQ_Main.pex';                                      dst = 'Scripts\SAQ_Main.pex' },
    @{ src = 'resources\SAQ_ShowAvailableQuests.ini';                           dst = 'SFSE\Plugins\SAQ_ShowAvailableQuests.ini' }
)

Step '2/5 检查产物'
$rows = @()
$missing = $false
foreach ($it in $items) {
    $src = Join-Path $root $it.src
    if (Test-Path $src) {
        $f = Get-Item $src
        $rows += [pscustomobject]@{
            包内路径 = $it.dst
            字节     = $f.Length
            修改时间 = $f.LastWriteTime.ToString('MM-dd HH:mm')
        }
    } else {
        Warn "缺少 $($it.src)"
        $missing = $true
    }
}
$rows | Format-Table -AutoSize | Out-Host
if ($missing) { throw '有产物缺失 —— 先跑 tools\build-saq.ps1 重新构建' }

# --- 2. 产物特征校验 ----------------------------------------------------------
if (-not $SkipVerify) {
    Step '3/5 产物特征校验（tools\ui\verify_saq_build.py --release）'
    # ★ 第 53 轮：--release = 按**发布构建**反向校验（DLL 里不允许出现任何 harness 特征；
    #   这一步能挡住「xmake 配置没切过去、带着测试代码打包」——最危险的失败模式）。
    & python (Join-Path $root 'tools\ui\verify_saq_build.py') --release | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "产物特征校验未全部通过（exit $LASTEXITCODE），已终止打包" }
} else {
    Step '3/5 跳过产物特征校验'
}

# --- 3. 组装 staging ----------------------------------------------------------
Step '4/5 组装 staging（zip 根 = mod 根）'
Remove-Item $stageDir -Recurse -Force -ErrorAction SilentlyContinue
foreach ($it in $items) {
    $src = Join-Path $root $it.src
    $dst = Join-Path $stageDir $it.dst
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    Copy-Item $src $dst -Force
}
# ★★ 第 62 轮（用户要求）：包里的配置必须是「正常玩」的默认值 ——
#   ini 的 [Test] 段（Mode / Harness）是**测试开关**，源文件偶尔会被调试改脏，
#   这里**强制还原**成默认值（不是只报警），并在写盘前校验（还原失败即终止打包）。
#   为什么值得写进脚本：「打包时忘了关测试开关」是最危险的失败模式之一 ——
#   玩家拿到手会看到满屏 harness 日志、任务被自动回滚（hreness 会 Reset/Start 任务）。
#   注：发布构建 DLL 已不含 harness 编译（第 53 轮），这里管的是**配置侧**双保险。
$iniSrc  = Join-Path $root 'resources\SAQ_ShowAvailableQuests.ini'
$iniDst  = Join-Path $stageDir 'SFSE\Plugins\SAQ_ShowAvailableQuests.ini'
$iniText = [System.IO.File]::ReadAllText($iniSrc, [System.Text.Encoding]::UTF8)
$iniOrig = $iniText
if ($iniText -notmatch '(?m)^\s*\[Test\]\s*$') {
    Warn '源 ini 里没有 [Test] 段 —— 已追加默认段（Mode=0 / Harness=0）'
    $iniText = $iniText.TrimEnd() + "`r`n[Test]`r`nMode=0`r`nHarness=0`r`n"
} else {
    $iniText = [regex]::Replace($iniText, '(?m)^\s*Mode\s*=.*$', 'Mode=0')
    $iniText = [regex]::Replace($iniText, '(?m)^\s*Harness\s*=.*$', 'Harness=0')
}
if ($iniText -notmatch '(?m)^\s*Mode\s*=\s*0\s*$' -or $iniText -notmatch '(?m)^\s*Harness\s*=\s*0\s*$') {
    throw 'ini 的玩家默认值还原失败（[Test] Mode=0 / Harness=0 校验不过）—— 已终止打包'
}
if ($iniText -ne $iniOrig) {
    Warn '源 ini 的 [Test] Mode/Harness 不是默认值 —— 已还原为 0 打进包（建议把源文件也改回默认）'
} else {
    Ok 'ini 玩家默认值（[Test] Mode=0 / Harness=0）'
}
[System.IO.File]::WriteAllText($iniDst, $iniText, (New-Object System.Text.UTF8Encoding $false))
# 包内 README：把 {{VERSION}} 换成实际版本号
$readmeSrc = Join-Path $root 'resources\README-mod.txt'
$readmeTxt = [System.IO.File]::ReadAllText($readmeSrc, [System.Text.Encoding]::UTF8)
if ($readmeTxt -notmatch '\{\{VERSION\}\}') { Warn 'README-mod.txt 里没有 {{VERSION}} 占位符（照常打包）' }
$readmeTxt = $readmeTxt.Replace('{{VERSION}}', $Version)
[System.IO.File]::WriteAllText((Join-Path $stageDir 'README.txt'), $readmeTxt,
    (New-Object System.Text.UTF8Encoding $false))
Ok "README.txt（v$Version）"

# Nexus 文案放到 dist（不是包内容 —— 它给你贴网页用）
Copy-Item (Join-Path $root 'resources\nexus-description.md') (Join-Path $distDir 'nexus-description.md') -Force

# --- 4. 压缩 -----------------------------------------------------------------
Step '5/5 压缩'
Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $stageDir, $zipPath,
    [System.IO.Compression.CompressionLevel]::Optimal, $false)

$zip = Get-Item $zipPath
$sha = (Get-FileHash $zipPath -Algorithm SHA256).Hash
Write-Host ''
Write-Host "上传包：$($zip.FullName)" -ForegroundColor Cyan
Write-Host ("        大小 {0:N0} 字节    SHA256 {1}" -f $zip.Length, $sha)
Write-Host '        包内 = mod 根：MO2 可直接「从压缩包安装」；手动安装解压到 Starfield\Data\' -ForegroundColor DarkGray
Write-Host "Nexus 文案：$distDir\nexus-description.md" -ForegroundColor Cyan
Write-Host '       要回到开发构建（含 harness）：& ".\tools\build-saq.ps1" -SkipTable -SkipSwf -SkipPapyrus -Harness' -ForegroundColor DarkGray
