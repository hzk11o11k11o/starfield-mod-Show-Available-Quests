# ============================================================================
#  Show Available Quests - 打包**源代码包**（与 Nexus 上传包 package-saq.ps1 分开）
#
#  用法（pwsh 7）：
#     & ".\tools\package-source.ps1"                   # 版本号自动从 plugin\xmake.lua 读
#     & ".\tools\package-source.ps1" -Version 0.2.0    # 指定版本号
#     & ".\tools\package-source.ps1" -IncludeAssets    # 连发布素材（截图 / N 网文案草稿）一起进包
#
#  产物：
#     dist\SAQ-ShowAvailableQuests-<版本>-source.zip
#       └ 包内顶层 = SAQ-ShowAvailableQuests-<版本>-source\（解压不污染当前目录）
#
#  内容 = git 跟踪的全部文件（**工作区当前状态**，含未提交改动）：
#     plugin\  ui\  scripts\  esm\  tools\  resources\  docs\  ref\extra_quests.json
#     AGENTS.md  .gitignore
#  不含：
#     · 构建产物（gitignore 的那些 build\ / patch\ / dist\ 等）—— 拿到源包请按
#       docs\01-构建与环境.md 自行构建；第三方依赖（commonlibsf / FFDec / Champollion /
#       xEdit）也不在包内（获取方式见 docs\01）
#     · .git 历史（这是「一个版本快照」，不是仓库克隆）
#     · 发布素材：Nexus 截图 2 张（合计约 5.4MB）、N 网文案草稿、0 字节的「临时要求」
#       —— 它们不是源代码/构建输入；要一起打包加 -IncludeAssets
#
#  ★ 与 package-saq.ps1 的区别：那个打的是**给玩家用的产物包**（会先做发布构建），
#    这个纯拷贝入库文件、不构建、不改任何产物 —— 可以在任何时候跑，无副作用。
# ============================================================================
param(
    [string]$Version = '',
    [switch]$IncludeAssets
)

$ErrorActionPreference = 'Stop'
$root     = Split-Path -Parent $PSScriptRoot
$distDir  = Join-Path $root 'dist'
$stageDir = Join-Path $distDir 'source-stage'   # 压缩前的中转目录（打完即删）

function Step($msg) { Write-Host "[源包] $msg" -ForegroundColor Yellow }
function Ok($msg)   { Write-Host "    OK: $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !! $msg" -ForegroundColor Red }

# --- 0. 版本号（-Version 优先；否则从 plugin\xmake.lua 的 set_version 读）------
if (-not $Version) {
    $xmakeTxt = [System.IO.File]::ReadAllText((Join-Path $root 'plugin\xmake.lua'), [System.Text.Encoding]::UTF8)
    if ($xmakeTxt -match 'set_version\("([^"]+)"\)') { $Version = $Matches[1] } else { $Version = 'dev' }
    Step "版本号（plugin\xmake.lua）：$Version"
}
$pkgName = "SAQ-ShowAvailableQuests-$Version-source"
$zipPath = Join-Path $distDir "$pkgName.zip"

# --- 1. 入库文件清单（git 跟踪 = 源码 / 工具 / 数据 / 文档）---------------------
# 中文文件名：core.quotepath=false + 控制台按 UTF-8 解码
# （否则中文名会输出成 \346\226\207 转义形式，拷文件时找不到）。
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$all = @(& git -C $root -c core.quotepath=false ls-files)
if ($LASTEXITCODE -ne 0) { throw 'git ls-files 失败（本脚本要求项目是一个 git 仓库）' }
if ($all.Count -lt 100) { throw "git ls-files 结果异常（只有 $($all.Count) 个文件）" }

# 发布素材（非源码）：默认不进源包；-IncludeAssets 一起打
$assetExclude = @('中文版截图.png', '英文版N网图.png', 'N网介绍草稿.txt', '临时要求')
$excluded = @()
$files = @(foreach ($f in $all) {
    if ((-not $IncludeAssets) -and ($assetExclude -contains $f)) { $excluded += $f; continue }
    $f
})

# --- 2. 工作区状态（打的是工作区当前内容 —— 提示但不阻断）-----------------------
$dirty = @(& git -C $root status --porcelain)
if ($dirty.Count -gt 0) {
    Warn "工作区有 $($dirty.Count) 处未提交改动 —— 源包按**当前工作区内容**打包（含这些改动）"
} else {
    Ok '工作区干净（源包 = 当前提交内容）'
}

# --- 3. 组装 staging（保留目录结构）--------------------------------------------
Step "组装 staging（$($files.Count) 个文件）"
Remove-Item $stageDir -Recurse -Force -ErrorAction SilentlyContinue
$stageRoot = Join-Path $stageDir $pkgName
$missing = 0
foreach ($f in $files) {
    $rel = $f -replace '/', '\'
    $src = Join-Path $root $rel
    if (-not (Test-Path -LiteralPath $src)) { Warn "文件不存在（已入库但工作区缺失）：$rel"; $missing++; continue }
    $dst = Join-Path $stageRoot $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    Copy-Item -LiteralPath $src $dst -Force
}

# --- 4. 关键文件校验（防止打出残包）--------------------------------------------
$mustHave = @(
    'plugin\xmake.lua', 'plugin\src\SAQ.cpp', 'plugin\src\SAQ_QuestTable.h',
    'ui\missionmenu\src\MissionMenu.as', 'ui\missionmenu_lrg\src\MissionMenu.as',
    'scripts\SAQ_Main.psc', 'esm\SAQ_ShowAvailableQuests.esm',
    'tools\build-saq.ps1', 'tools\package-saq.ps1',
    'resources\SAQ_ShowAvailableQuests.ini',
    'docs\00-项目总览与技术方案.md', 'docs\99-当前项目进度.md', 'AGENTS.md'
)
$bad = $false
foreach ($m in $mustHave) {
    if (-not (Test-Path -LiteralPath (Join-Path $stageRoot $m))) { Warn "关键文件缺失：$m"; $bad = $true }
}
if ($bad) { throw '源包关键文件缺失 —— 已终止打包' }
Ok "关键文件齐全（$($mustHave.Count) 项）"

$stageFiles = @(Get-ChildItem $stageRoot -Recurse -File)
$totalBytes = ($stageFiles | Measure-Object Length -Sum).Sum
Step ("包内：{0} 个文件，{1:N1} MB（压缩前）" -f $stageFiles.Count, ($totalBytes / 1MB))
Get-ChildItem $stageRoot | ForEach-Object {
    $n = if ($_.PSIsContainer) { @(Get-ChildItem $_.FullName -Recurse -File).Count } else { 1 }
    [pscustomobject]@{ 顶层 = $_.Name; 文件数 = $n }
} | Format-Table -AutoSize | Out-Host

# --- 5. 压缩 -------------------------------------------------------------------
Step '压缩'
New-Item -ItemType Directory -Force -Path $distDir | Out-Null
Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $stageDir, $zipPath,
    [System.IO.Compression.CompressionLevel]::Optimal, $false)
Remove-Item $stageDir -Recurse -Force -ErrorAction SilentlyContinue

$zip = Get-Item $zipPath
$sha = (Get-FileHash $zipPath -Algorithm SHA256).Hash
Write-Host ''
Write-Host "源代码包：$($zip.FullName)" -ForegroundColor Cyan
Write-Host ("          大小 {0:N0} 字节（{1:N2} MB）  SHA256 {2}" -f $zip.Length, ($zip.Length / 1MB), $sha)
if ($excluded.Count -gt 0) {
    Write-Host ("          已排除发布素材：{0}" -f ($excluded -join '、')) -ForegroundColor DarkGray
    Write-Host '          （要一起打包：& ".\tools\package-source.ps1" -IncludeAssets）' -ForegroundColor DarkGray
}
