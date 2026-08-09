# stop_windows.ps1 — 停止 windows 包启动的所有服务
param([switch]$Quiet)
$ErrorActionPreference = "SilentlyContinue"

$Runtime = Join-Path $PSScriptRoot "runtime"
$pidsFile = Join-Path $Runtime "pids.json"

if (Test-Path $pidsFile) {
    $pids = Get-Content $pidsFile -Raw | ConvertFrom-Json
    foreach ($prop in $pids.PSObject.Properties) {
        $proc = Get-Process -Id $prop.Value -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-Process -Id $prop.Value -Force -ErrorAction SilentlyContinue
            if (-not $Quiet) { Write-Host "已停止 $($prop.Name) (PID $($prop.Value))" }
        }
    }
    Remove-Item $pidsFile -Force -ErrorAction SilentlyContinue
} elseif (-not $Quiet) {
    Write-Host "没有 pids.json，尝试按进程命令行清理..."
}

# 兜底：清理残留的 head_grpc_server / servo_server / save_server 进程
$leftovers = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -like "*head_grpc_server*" -or
        $_.CommandLine -like "*servo_server.py*" -or
        $_.CommandLine -like "*launch_save_server*" -or
        $_.CommandLine -like "*launch_config_server*" -or
        $_.CommandLine -like "*save_server.py*"
    }
foreach ($p in $leftovers) {
    if ($p.ProcessId -gt 0) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        if (-not $Quiet) { Write-Host "已清理残留进程 PID $($p.ProcessId)" }
    }
}

if (-not $Quiet) { Write-Host "服务已全部停止" }
