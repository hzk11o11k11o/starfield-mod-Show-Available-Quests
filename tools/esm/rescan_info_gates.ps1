# rescan_info_gates.ps1 - 手动重扫 4 个 master 的对话条件（INFO 门槛数据链第一步）
#
# 为什么需要：build-saq.ps1 只在 ref\info_gates*.json **缺失时**才扫（每次构建都扫太慢）。
# 改了 scan_info_gates.py 的提取逻辑、或游戏/DLC 更新后要刷新数据时，跑这个脚本。
#
# 用法：
#   pwsh -File tools\esm\rescan_info_gates.ps1            # 重扫 4 个 master + 合并
#   pwsh -File tools\esm\rescan_info_gates.ps1 -SkipMerge # 只重扫（不跑 analyze_info_gates)
param(
    [switch]$SkipMerge
)
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'

$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $root
$dataDir = 'D:\SteamLibrary\steamapps\common\Starfield\Data'

$scans = @(
    @{ esm = 'Starfield.esm';      master = 'Starfield.esm';      out = 'info_gates.json';                  log = '_scan_base.log' },
    @{ esm = 'SFBGS00D.esm';       master = 'SFBGS00D.esm';       out = 'info_gates_sfbgs00d.json';         log = '_scan_sfbgs00d.log' },
    @{ esm = 'SFBGS050.esm';       master = 'SFBGS050.esm';       out = 'info_gates_sfbgs050.json';         log = '_scan_sfbgs050.log' },
    @{ esm = 'ShatteredSpace.esm'; master = 'ShatteredSpace.esm'; out = 'info_gates_shatteredspace.json';   log = '_scan_ss.log' }
)

foreach ($s in $scans) {
    $esm = Join-Path $dataDir $s.esm
    Write-Host ("扫 " + $s.master + " …") -ForegroundColor Yellow
    python tools/esm/scan_info_gates.py --esm $esm --self-master $s.master --out $s.out *> (Join-Path 'ref' $s.log)
    if ($LASTEXITCODE -ne 0) { throw "scan_info_gates.py（$($s.master)）失败（exit $LASTEXITCODE）" }
    Write-Host ("    exit 0 → ref\" + $s.out) -ForegroundColor Green
}

if (-not $SkipMerge) {
    Write-Host '合并 INFO 门槛（analyze_info_gates.py）…' -ForegroundColor Yellow
    python tools/esm/analyze_info_gates.py
    if ($LASTEXITCODE -ne 0) { throw "analyze_info_gates.py 失败（exit $LASTEXITCODE）" }
}

Write-Host '=== 汇总 ===' -ForegroundColor Cyan
python -c @"
import json
tot_g = tot_o = 0
for fn in ['info_gates.json','info_gates_sfbgs00d.json','info_gates_sfbgs050.json','info_gates_shatteredspace.json']:
    d = json.load(open('ref/' + fn, encoding='utf-8'))
    p = json.load(open('ref/' + fn.replace('info_gates','info_gates_pending'), encoding='utf-8'))
    n_or = sum(1 for g in d['gates'] if g.get('orBit'))
    tot_g += d['gateCount']; tot_o += n_or
    print(fn, '| gates', d['gateCount'], '| orBit', n_or, '| dropGroups', p['dropGroups'], '| pending', len(p['pending']), '| kind', d['kindHist'])
print('TOTAL gates', tot_g, 'orBit', tot_o)
"@
