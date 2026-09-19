# ============================================================================
#  用 xEdit 无头生成 SAQ_ShowAvailableQuests.esm
#
#  注意：所有路径必须是绝对路径 —— xEdit 会把相对路径解析成「相对它自己的 exe 目录」，
#        传相对路径会导致它弹「Select a script to execute」文件选择框（已踩）。
#
#  用法：& ".\tools\run-esm-build.ps1"
# ============================================================================
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$outDir = Join-Path $root 'ref\xedit-out'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
Remove-Item (Join-Path $outDir 'h_99_done.txt') -ErrorAction SilentlyContinue

& (Join-Path $root 'tools\run-xedit-build.ps1') `
    -Exe        (Join-Path $root 'tools\vendor\xEdit\xSFEdit64.exe') `
    -ScriptPath (Join-Path $root 'tools\xedit-scripts\build_saq.pas') `
    -PluginList (Join-Path $root 'tools\plugins.txt') `
    -DoneFile   (Join-Path $outDir 'h_99_done.txt') `
    -LogPath    (Join-Path $root 'ref\xedit-build.log')
