# start_windows.ps1 — Windows 一键启动 exp 调试平台
#
# 布局要求：本包（windows/）与 core、motion、exp 同级（旧布局回退
# droidcore-temp / droidmotion / exp_deb）。本包只读这三个项目，
# 绝不修改它们的内容；所有运行时产物都落在 windows\runtime\。
#
# 可选参数：
#   -HeadPort COM5   指定机器人头 COM 口（不指定则自动检测）
#   -MicPort COM6    指定麦克风阵列 COM 口（音源追踪）
#   -Head g02        指定机器人头型号 ula/g01/g02（默认读 .selected_head.json，再默认 G02）
#   -NoBrowser       不自动打开浏览器
#   -SkipSerial      跳过串口检测，直接使用 runtime\configs 已有配置
param(
    [string]$HeadPort = "",
    [string]$MicPort = "",
    [string]$Head = "",
    [switch]$NoBrowser,
    [switch]$SkipSerial
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Runtime = Join-Path $Root "runtime"
$Logs = Join-Path $Runtime "logs"
$Configs = Join-Path $Runtime "configs"

function Write-Step([string]$Msg) { Write-Host "==> $Msg" -ForegroundColor Cyan }
function Resolve-Sibling([string[]]$Names) {
    foreach ($name in $Names) {
        $candidate = Join-Path (Split-Path $Root -Parent) $name
        if (Test-Path $candidate) { return $candidate }
    }
    return Join-Path (Split-Path $Root -Parent) $Names[0]
}

# 兄弟项目目录：新布局 core/motion/exp，旧布局回退
$ExpDeb = Resolve-Sibling @("exp", "exp_deb")
$Motion = Resolve-Sibling @("motion", "droidmotion")
$Core = Resolve-Sibling @("core", "droidcore-temp")

function Test-PortOpen([int]$Port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $Port)
        $client.Close()
        return $true
    } catch { return $false }
}

# 项目 Python（由 setup_windows.ps1 写入：优先 conda face_servo / Python 3.10）
$envPy = ""
$pythonPathFile = Join-Path $Runtime "python_path.txt"
if (Test-Path $pythonPathFile) { $envPy = (Get-Content $pythonPathFile -Raw).Trim() }
if (-not $envPy -or -not (Test-Path $envPy)) {
    Write-Host "未找到项目 Python（runtime\python_path.txt 缺失或路径失效）。" -ForegroundColor Red
    Write-Host "请先双击运行 setup_windows.bat 安装依赖（要求 conda face_servo 环境 / Python 3.10）。" -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path (Join-Path $ExpDeb "expression_debugger\save_server.py"))) {
    Write-Host "找不到 exp 目录: $ExpDeb" -ForegroundColor Red
    Write-Host "请把 windows 包放在 core / motion / exp 的同级目录下。" -ForegroundColor Yellow
    exit 1
}
New-Item -ItemType Directory -Force -Path $Logs, $Configs | Out-Null

# 1) 串口检测 + 舵机配置 COM 转换
if (-not $SkipSerial) {
    Write-Step "检测串口并转换舵机配置为 COM 口"
    $detectArgs = @()
    if ($HeadPort) { $detectArgs += @("--head-port", $HeadPort) }
    if ($MicPort) { $detectArgs += @("--mic-port", $MicPort) }
    & $envPy (Join-Path $Root "win_tools\detect_serial.py") @detectArgs
    if ($LASTEXITCODE -ne 0) { exit 1 }
} else {
    Write-Step "跳过串口检测（-SkipSerial），使用 runtime\configs 已有配置"
}

# 2) 读取串口信息（音源追踪用）
$micPortEnv = ""
$serialFile = Join-Path $Runtime "serial.json"
if (Test-Path $serialFile) {
    try {
        $serial = Get-Content $serialFile -Raw | ConvertFrom-Json
        if ($serial.mic_port) { $micPortEnv = [string]$serial.mic_port }
    } catch { }
}

# 3) 选择机器人头配置
$headConfigName = "servoConfig_25DV3_G02.yaml"
$selectedFile = Join-Path $Runtime ".selected_head.json"
if (-not (Test-Path $selectedFile)) {
    $selectedFile = Join-Path $ExpDeb "expression_debugger\.selected_head.json"
}
if (Test-Path $selectedFile) {
    try {
        $sel = Get-Content $selectedFile -Raw | ConvertFrom-Json
        if ($sel.head_config) { $headConfigName = [string]$sel.head_config }
    } catch { }
}
if ($Head) {
    $headMap = @{
        "ula" = "servoConfig_25DV3_Ula.yaml"
        "g01" = "servoConfig_25DV3_G01.yaml"
        "g02" = "servoConfig_25DV3_G02.yaml"
    }
    $key = $Head.ToLower()
    if (-not $headMap.ContainsKey($key)) {
        Write-Host "不支持的 -Head: $Head（可选 ula/g01/g02）" -ForegroundColor Red
        exit 1
    }
    $headConfigName = $headMap[$key]
}
$headConfig = Join-Path $Configs $headConfigName
if (-not (Test-Path $headConfig)) {
    $headConfig = Join-Path $ExpDeb "servo_tuning\head-sdk-face\head-server\src\$headConfigName"
}
if (-not (Test-Path $headConfig)) {
    Write-Host "找不到头部舵机配置: $headConfigName" -ForegroundColor Red
    exit 1
}
$portLine = Select-String -Path $headConfig -Pattern "^\s*-\s*port:\s*(.+)$" | Select-Object -First 1
if ($portLine) {
    Write-Step "使用机器人头配置: $headConfigName（串口 $($portLine.Matches[0].Groups[1].Value.Trim())）"
} else {
    Write-Step "使用机器人头配置: $headConfigName"
}

# 4) 端口被占用则先停止旧服务
if ((Test-PortOpen 9002) -or (Test-PortOpen 9001) -or (Test-PortOpen 2543)) {
    Write-Step "检测到端口占用，先停止旧服务"
    & (Join-Path $Root "stop_windows.ps1")
}

# 5) 启动三个服务（save_server 走 windows 包启动器，exp 代码零修改）
function Start-ExpService([string]$Name, [string]$PyFile, [string]$WorkDir, [string[]]$ArgList) {
    $outLog = Join-Path $Logs "$Name.out.log"
    $errLog = Join-Path $Logs "$Name.err.log"
    $proc = Start-Process -FilePath $envPy -ArgumentList $ArgList -WorkingDirectory $WorkDir `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru -WindowStyle Hidden
    Write-Host "已启动 $Name (PID $($proc.Id)) -> $outLog"
    return $proc.Id
}

# 中文日志统一 UTF-8，避免 Windows 控制台编码乱码
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

# save_server：launcher 原样加载 exp/expression_debugger/save_server.py，
# 仅在内存里替换 Windows 专属行为（局域网 IP、gRPC 启停、COM 配置优先）。
$saveLauncher = Join-Path $Root "launchers\launch_save_server.py"
$saveId = Start-ExpService "save_server" $saveLauncher $Root @("`"$saveLauncher`"")

# servo_server：直接跑 exp 的脚本。exp 内部按旧目录名硬编码 import 路径，
# 新布局（core/motion）下用 PYTHONPATH 注入 motion/src + core/src 桥接。
$servoPy = Join-Path $ExpDeb "servo_tuning\servo_server.py"
$servoWorkDir = Join-Path $ExpDeb "servo_tuning"
$envBackupPath = $env:PYTHONPATH
$pythonPathParts = @()
foreach ($proj in @($Motion, $Core)) {
    $projSrc = Join-Path $proj "src"
    if (Test-Path $projSrc) { $pythonPathParts += $projSrc }
}
if ($pythonPathParts.Count -gt 0) {
    if ($envBackupPath) {
        $env:PYTHONPATH = ($pythonPathParts -join ";") + ";" + $envBackupPath
    } else {
        $env:PYTHONPATH = $pythonPathParts -join ";"
    }
}
$envBackupSound = $env:SOUND_TRACKING_PORT
if ($micPortEnv) { $env:SOUND_TRACKING_PORT = $micPortEnv }
$servoId = Start-ExpService "servo_server" $servoPy $servoWorkDir @("`"$servoPy`"", "--port", "9001")
$env:SOUND_TRACKING_PORT = $envBackupSound
$env:PYTHONPATH = $envBackupPath

# gRPC 硬件服务：直接用转换过 COM 口的配置启动 head_grpc_server.py
$grpcSrc = Join-Path $ExpDeb "servo_tuning\head-sdk-face\head-server\src"
$grpcPy = Join-Path $grpcSrc "head_grpc_server.py"

$grpcId = $null
if (-not (Test-PortOpen 2543)) {
    $grpcId = Start-ExpService "head_grpc_server" $grpcPy $grpcSrc @("`"$grpcPy`"", "--config", "`"$headConfig`"")
} else {
    Write-Host "端口 2543 已有 gRPC 服务在运行，跳过启动" -ForegroundColor Yellow
}

# 6) 等待端口就绪
function Wait-Port([int]$Port, [int]$TimeoutSec = 40) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortOpen $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

$okSave = Wait-Port 9002
$okServo = Wait-Port 9001
$okGrpc = $true
if ($grpcId) { $okGrpc = Wait-Port 2543 }

if ($okSave)  { Write-Host "OK  save_server     :9002" -ForegroundColor Green } else { Write-Host "FAIL save_server     :9002（见 $Logs\save_server.err.log）" -ForegroundColor Red }
if ($okServo) { Write-Host "OK  servo_server    :9001" -ForegroundColor Green } else { Write-Host "FAIL servo_server    :9001（见 $Logs\servo_server.err.log）" -ForegroundColor Red }
if ($okGrpc)  { Write-Host "OK  head_grpc_server:2543" -ForegroundColor Green } else { Write-Host "FAIL head_grpc_server:2543（见 $Logs\head_grpc_server.err.log）" -ForegroundColor Red }

# 7) 保存 PID 供 stop 脚本使用
$pids = [ordered]@{ save_server = $saveId; servo_server = $servoId }
if ($grpcId) { $pids.head_grpc_server = $grpcId }
$pids | ConvertTo-Json | Set-Content (Join-Path $Runtime "pids.json") -Encoding UTF8

# 8) 打开浏览器
if (-not $NoBrowser) {
    $url = "http://localhost:9002/expression_debugger/expression_debugger_v2.html"
    Start-Process $url
    Write-Step "已在浏览器打开: $url"
}
Write-Host ""
Write-Host "全部完成。停止服务请运行 stop_windows.bat；日志在 windows\runtime\logs。" -ForegroundColor Yellow
