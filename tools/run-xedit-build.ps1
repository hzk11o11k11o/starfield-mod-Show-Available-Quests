param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string]$ScriptPath,
    [string]$DataPath = 'D:\SteamLibrary\steamapps\common\Starfield\Data',
    [string]$IniPath  = 'D:\SteamLibrary\steamapps\common\Starfield\Starfield.ini',
    [string]$PluginList = "$PSScriptRoot\plugins.txt",
    [string]$DoneFile,
    [string]$LogPath,
    [int]$TimeoutSec = 1800,
    [int]$IdleCloseSec = 30,
    [string[]]$ExtraArgs = @()
)

$ErrorActionPreference = 'Continue'
$sw = [System.Diagnostics.Stopwatch]::StartNew()

if (-not (Test-Path -LiteralPath $Exe)) { throw "xEdit exe not found: $Exe" }
if (-not (Test-Path -LiteralPath $ScriptPath)) { throw "Script not found: $ScriptPath" }
if (-not (Test-Path -LiteralPath $DataPath)) { throw "Data path not found: $DataPath" }
if ($DoneFile) { Remove-Item -LiteralPath $DoneFile -ErrorAction SilentlyContinue }
if ($LogPath)  { Remove-Item -LiteralPath $LogPath -ErrorAction SilentlyContinue }

Add-Type -Namespace W32 -Name Win -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, System.IntPtr lParam);
public delegate bool EnumWindowsProc(System.IntPtr hWnd, System.IntPtr lParam);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool EnumChildWindows(System.IntPtr hWndParent, EnumWindowsProc lpEnumFunc, System.IntPtr lParam);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(System.IntPtr hWnd, out uint lpdwProcessId);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool IsWindowVisible(System.IntPtr hWnd);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool IsWindowEnabled(System.IntPtr hWnd);
[System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Auto)] public static extern int GetClassName(System.IntPtr hWnd, System.Text.StringBuilder lpClassName, int nMaxCount);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern System.IntPtr SendMessage(System.IntPtr hWnd, uint msg, System.IntPtr wParam, System.IntPtr lParam);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern System.IntPtr GetDlgItem(System.IntPtr hDlg, int nIDDlgItem);
[System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Auto)] public static extern int GetWindowText(System.IntPtr hWnd, System.Text.StringBuilder lpString, int nMaxCount);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr hWnd, int nCmdShow);
'@

$script:windowBuffer = New-Object System.Collections.ArrayList
function Get-Windows([int]$pid_) {
    $script:windowBuffer.Clear()
    $script:targetPid = $pid_
    $cb = [W32.Win+EnumWindowsProc]{
        param($hWnd, $lParam)
        $wpid = 0
        [W32.Win]::GetWindowThreadProcessId($hWnd, [ref]$wpid) | Out-Null
        if ($wpid -ne $script:targetPid) { return $true }
        if (-not [W32.Win]::IsWindowVisible($hWnd)) { return $true }
        $sb = New-Object System.Text.StringBuilder 256
        [W32.Win]::GetClassName($hWnd, $sb, 256) | Out-Null
        $tb = New-Object System.Text.StringBuilder 512
        [W32.Win]::GetWindowText($hWnd, $tb, 512) | Out-Null
        $script:windowBuffer.Add(@{ Handle = $hWnd; Class = $sb.ToString(); Title = $tb.ToString() }) | Out-Null
        return $true
    }
    [W32.Win]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
    return $script:windowBuffer.ToArray()
}

$script:childBuffer = New-Object System.Collections.ArrayList
function Get-Children([IntPtr]$parent) {
    $script:childBuffer.Clear()
    $cb = [W32.Win+EnumWindowsProc]{
        param($hWnd, $lParam)
        $sb = New-Object System.Text.StringBuilder 256
        [W32.Win]::GetClassName($hWnd, $sb, 256) | Out-Null
        $tb = New-Object System.Text.StringBuilder 512
        [W32.Win]::GetWindowText($hWnd, $tb, 512) | Out-Null
        $script:childBuffer.Add(@{ Handle = $hWnd; Class = $sb.ToString(); Title = $tb.ToString() }) | Out-Null
        return $true
    }
    [W32.Win]::EnumChildWindows($parent, $cb, [IntPtr]::Zero) | Out-Null
    return $script:childBuffer.ToArray()
}

$argsList = @('-SF1', "-script:`"$ScriptPath`"", "-D:`"$DataPath`"", "-I:`"$IniPath`"")
if ($LogPath)    { $argsList += "-R:`"$LogPath`"" }
if ($PluginList) { $argsList += "-P:`"$PluginList`"" }
$argsList += @('-autoexit', '-skipbsa', '-IKnowWhatImDoing')
$argsList += $ExtraArgs

Write-Host "Launch: $Exe $($argsList -join ' ')"
$p = Start-Process -FilePath $Exe -ArgumentList $argsList -PassThru -WindowStyle Minimized

$handled        = @{}
$dialogTries    = @{}
$minimized      = $false
$closeSentAt    = $null
$lastCpu        = 0
$lastCpuAt      = $sw.Elapsed.TotalSeconds
$idleSince      = $sw.Elapsed.TotalSeconds
$lastDiagAt     = 0

while (-not $p.HasExited) {
    Start-Sleep -Milliseconds 400
    try { $p.Refresh() } catch {}
    if ($p.HasExited) { break }

    foreach ($w in (Get-Windows $p.Id)) {
        # 只最小化主窗口本身；对话框保持可见以便点击其按钮
        if (-not $minimized -and $w.Class -eq 'TfrmMain') {
            Write-Host "[minimize] $($w.Class) '$($w.Title)'"
            [W32.Win]::ShowWindow($w.Handle, 6) | Out-Null  # SW_MINIMIZE
            $minimized = $true
        }

        # 只处理真正的模态对话框；主窗口 TfrmMain 绝不触碰（除非收尾请求关闭）
        $isDialog = ($w.Class -eq '#32770') -or
                    ($w.Class -match '^Tfrm(ModuleSelect|FileSelect|SaveSelect|RichEdit|Input|Message|Question|Password|Conflict|Error|About)$')
        if (-not $isDialog) { continue }

        $key = "dlg:$($w.Handle)"
        $tries = 0
        if ($dialogTries.ContainsKey($key)) { $tries = $dialogTries[$key] }

        if (-not $handled.ContainsKey($key)) {
            $handled[$key] = $true
            $texts = @((Get-Children $w.Handle) | ForEach-Object {
                if ($_.Title) { $_.Title }
            }) -join ' | '
            Write-Host "[dialog] $($w.Class) '$($w.Title)' text: $texts"
        }

        # 按钮必须处于启用状态才点击；轮询重试，直到对话框消失或超限
        if ($tries -lt 100) {
            $dialogTries[$key] = $tries + 1
            $clicked = $false
            foreach ($b in (Get-Children $w.Handle)) {
                if ($b.Class -match 'Button' -and $b.Title -match '^(OK|&OK|Yes|&Yes|Continue|确定|是)$' -and [W32.Win]::IsWindowEnabled($b.Handle)) {
                    if ($tries -eq 0) { Write-Host "  clicking '$($b.Title)'" }
                    [W32.Win]::SendMessage($b.Handle, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null  # BM_CLICK
                    $clicked = $true
                    break
                }
            }
            if (-not $clicked -and $tries -eq 99) {
                # 兜底：标准对话框用控件 ID 1，再不行就 WM_CLOSE
                $ok = [W32.Win]::GetDlgItem($w.Handle, 1)
                if (($ok -ne [IntPtr]::Zero) -and [W32.Win]::IsWindowEnabled($ok)) {
                    [W32.Win]::SendMessage($ok, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
                } else {
                    Write-Host "  no clickable OK button; sending WM_CLOSE"
                    [W32.Win]::SendMessage($w.Handle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null  # WM_CLOSE
                }
            }
        }
    }

    # 完成检测：标记文件出现即关闭；否则用 CPU 活动判定（6 秒采样窗口，避免加载期误判空闲）
    if (-not $closeSentAt) {
        $now = $sw.Elapsed.TotalSeconds
        try {
            $cpu = $p.TotalProcessorTime.TotalSeconds
            if (($now - $lastCpuAt) -ge 6) {
                $cpuDelta = $cpu - $lastCpu
                if ($cpuDelta -lt 0.3) {
                    # idle continues
                } else {
                    $idleSince = $now
                }
                if (($now - $lastDiagAt) -ge 30) {
                    Write-Host ("[diag] t={0:N0}s cpuDelta={1:N2}s idleFor={2:N0}s" -f $now, $cpuDelta, ($now - $idleSince))
                    $lastDiagAt = $now
                }
                $lastCpu   = $cpu
                $lastCpuAt = $now
            }
        } catch {}

        $doneByIdle = (($now - $idleSince) -gt $IdleCloseSec)
        $doneByFile = $DoneFile -and (Test-Path -LiteralPath $DoneFile)
        if ($doneByFile -or $doneByIdle) {
            if ($doneByFile) {
                Write-Host "[done] marker file detected: $DoneFile"
            } else {
                Write-Host "[done] process idle for $([math]::Round($now - $idleSince,1))s -> closing"
            }
            foreach ($w in (Get-Windows $p.Id)) {
                if ($w.Class -eq 'TfrmMain') {
                    Write-Host "[close] sending WM_CLOSE to TfrmMain"
                    [W32.Win]::SendMessage($w.Handle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
                }
            }
            $closeSentAt = $now
        }
    } else {
        # 等待优雅退出，10 秒后强杀
        if (($sw.Elapsed.TotalSeconds - $closeSentAt) -gt 10) {
            Write-Host "[close] graceful close timed out, killing process $($p.Id)"
            try { $p.Kill() } catch {}
            break
        }
    }

    if ($sw.Elapsed.TotalSeconds -gt $TimeoutSec) {
        Write-Host "Timeout after $TimeoutSec s, killing process $($p.Id)"
        try { $p.Kill() } catch {}
        exit 2
    }
}

Write-Host "Exited with code $($p.ExitCode) after $([math]::Round($sw.Elapsed.TotalSeconds,1))s"
exit $p.ExitCode
