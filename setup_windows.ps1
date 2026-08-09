param([switch]$SkipOptional)
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Runtime = Join-Path $Root "runtime"

function Write-Step([string]$Msg) { Write-Host "==> $Msg" -ForegroundColor Cyan }

# 兄弟项目目录：新布局 core/motion/exp，旧布局回退 droidcore-temp/droidmotion/exp_deb
function Resolve-Sibling([string[]]$Names) {
    foreach ($name in $Names) {
        $candidate = Join-Path (Split-Path $Root -Parent) $name
        if (Test-Path $candidate) { return $candidate }
    }
    return Join-Path (Split-Path $Root -Parent) $Names[0]
}

function Find-ProjectSrc([string]$ProjectRoot) {
    # 兼容“仓库根里又套了一层同名目录”的布局，如 droidmotion/droidmotion/src
    $direct = Join-Path $ProjectRoot "src"
    if (Test-Path $direct) { return $direct }
    $nested = Join-Path $ProjectRoot (Join-Path (Split-Path $ProjectRoot -Leaf) "src")
    if (Test-Path $nested) { return $nested }
    return $null
}

$ExpDeb = Resolve-Sibling @("exp", "exp_deb")
$Motion = Resolve-Sibling @("motion", "droidmotion")
$Core = Resolve-Sibling @("core", "droidcore-temp")

if (-not (Test-Path (Join-Path $ExpDeb "expression_debugger\save_server.py"))) {
    Write-Host "找不到 exp 项目: $ExpDeb" -ForegroundColor Red
    Write-Host "请把 windows 包放在 core / motion / exp 的同级目录下。" -ForegroundColor Yellow
    exit 1
}

# 0) 自检：启动器存在 + 三个项目目录可读（本包绝不写入 core/motion/exp）
foreach ($launcher in @("launchers\launch_save_server.py", "launchers\launch_config_server.py")) {
    if (-not (Test-Path (Join-Path $Root $launcher))) {
        Write-Host "缺少启动器: $launcher" -ForegroundColor Red
        exit 1
    }
}
Write-Step "项目目录：exp=$ExpDeb"
if (Test-Path (Join-Path $ExpDeb "servo_tuning\head-sdk-face\head-server\src\head_grpc_server.py")) {
    Write-Host "  ✓ head_grpc_server.py 存在"
} else {
    Write-Host "  ✗ 找不到 head_grpc_server.py，舵机 gRPC 无法启动" -ForegroundColor Red
    exit 1
}
$motionSrc = Find-ProjectSrc $Motion
if ($motionSrc) {
    Write-Host "  ✓ motion=$Motion（自然状态运动源: $motionSrc）"
} else {
    Write-Host "  ! 未找到 motion 项目，自然状态将被禁用（其余功能不受影响）" -ForegroundColor Yellow
}
$coreSrc = Find-ProjectSrc $Core
if ($coreSrc) {
    Write-Host "  ✓ core=$Core（人脸/注视跟踪: $coreSrc）"
} else {
    Write-Host "  ! 未找到 core 项目，人脸/注视跟踪将被禁用（其余功能不受影响）" -ForegroundColor Yellow
}

# 1) 项目要求 conda 环境 face_servo（Python 3.10），优先使用/创建它
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
$envPy = ""

$condaExe = ""
$condaCmd = Get-Command conda -ErrorAction SilentlyContinue
if ($condaCmd) { $condaExe = $condaCmd.Source }
if (-not $condaExe) {
    # conda 不在 PATH 时，去常见安装目录找
    foreach ($candidate in @(
        "$env:USERPROFILE\miniconda3\Scripts\conda.exe",
        "$env:USERPROFILE\anaconda3\Scripts\conda.exe",
        "$env:USERPROFILE\Miniconda3\Scripts\conda.exe",
        "$env:USERPROFILE\Anaconda3\Scripts\conda.exe",
        "C:\ProgramData\miniconda3\Scripts\conda.exe",
        "C:\ProgramData\anaconda3\Scripts\conda.exe"
    )) {
        if (Test-Path $candidate) { $condaExe = $candidate; break }
    }
}
if ($condaExe) {
    Write-Step "检测到 conda，使用项目要求的 face_servo 环境（Python 3.10）"
    $condaBase = (& $condaExe info --base 2>$null | Select-Object -Last 1).Trim()
    if (-not $condaBase -or -not (Test-Path $condaBase)) {
        Write-Host "conda info --base 返回异常: '$condaBase'" -ForegroundColor Red
        exit 1
    }
    $envPy = Join-Path $condaBase "envs\face_servo\python.exe"
    if (-not (Test-Path $envPy)) {
        Write-Step "创建 conda 环境 face_servo（python=3.10）"
        & $condaExe create -n face_servo python=3.10 -y
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $envPy)) {
            Write-Host "conda 环境 face_servo 创建失败" -ForegroundColor Red
            exit 1
        }
    }
    $ver = (& $envPy -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    Write-Step "使用 Python: $envPy（版本 $ver）"
    if ($ver -notmatch "^3\.(10|11|12)$") {
        Write-Host "face_servo 当前是 Python $ver，项目要求 3.10。" -ForegroundColor Yellow
        Write-Host "建议先执行 conda remove -n face_servo --all 再重新运行本脚本重建。" -ForegroundColor Yellow
    } elseif ($ver -ne "3.10") {
        Write-Host "注意：face_servo 是 Python $ver（项目要求 3.10）；3.10~3.12 均可安装固定依赖版本。" -ForegroundColor Yellow
    }
} else {
    Write-Host "未检测到 conda。项目要求 conda Python 3.10（face_servo 环境），" -ForegroundColor Yellow
    Write-Host "本脚本降级使用普通 venv，可能不符合项目环境要求；建议先安装 Miniconda/Anaconda 后重试。" -ForegroundColor Yellow
    $pyCmd = $null
    if (Get-Command py -ErrorAction SilentlyContinue) { $pyCmd = "py" }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { $pyCmd = "python" }
    if (-not $pyCmd) {
        Write-Host "未找到 Python（conda 和 PATH 中都没有）。" -ForegroundColor Red
        exit 1
    }
    $ver = (& $pyCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $ver) {
        Write-Host "Python 不可用，请检查安装。" -ForegroundColor Red
        exit 1
    }
    $parts = $ver.Split(".")
    $majorVer = [int]$parts[0]
    $minorVer = [int]$parts[1]
    if ($majorVer -ne 3 -or $minorVer -lt 10 -or $minorVer -gt 12) {
        Write-Host "当前 Python $ver 不在 3.10~3.12 范围内，固定版本的 numpy/grpcio 可能装不上。" -ForegroundColor Yellow
    }
    $venvDir = Join-Path $Runtime ".venv"
    $venvPy = Join-Path $venvDir "Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        Write-Step "创建虚拟环境: $venvDir"
        & $pyCmd -m venv $venvDir
        if ($LASTEXITCODE -ne 0) {
            Write-Host "虚拟环境创建失败" -ForegroundColor Red
            exit 1
        }
    }
    $envPy = $venvPy
}

# 2) 持久化 Python 路径，供 start 脚本使用
$envPy | Set-Content (Join-Path $Runtime "python_path.txt") -Encoding ASCII
Write-Step "项目 Python: $envPy"
Write-Step "升级 pip / setuptools / wheel"
& $envPy -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { exit 1 }

# 3) 安装依赖
$wheel = Join-Path $ExpDeb "servo_tuning\head-sdk-face\head-sdk\rena2_sdk_api-0.1.0-py3-none-any.whl"
$sdkDir = Join-Path $ExpDeb "servo_tuning\head-sdk-face\head-sdk"
if (-not (Test-Path $wheel)) {
    Write-Host "缺少仓库内协议包: $wheel" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $sdkDir "setup.py"))) {
    Write-Host "缺少 Head SDK: $sdkDir" -ForegroundColor Red
    exit 1
}

Write-Step "安装 exp 运行依赖（含 Head SDK）"
& $envPy -m pip install "$wheel" "$sdkDir" `
    "pyserial==3.5" `
    "websockets==15.0.1" `
    "pylivelinkface==0.1" `
    "numpy==1.26.4" `
    "matplotlib==3.10.8" `
    "fastapi==0.141.1" `
    "uvicorn==0.52.1" `
    "opencv-contrib-python==4.11.0.86" `
    "scipy==1.15.3"
if ($LASTEXITCODE -ne 0) {
    Write-Host "核心依赖安装失败" -ForegroundColor Red
    exit 1
}

if (-not $SkipOptional) {
    Write-Step "安装可选依赖（标定/训练：torch、mediapipe，体积较大，失败不影响运行）"
    & $envPy -m pip install "torch>=2,<3" "mediapipe==0.10.21"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "可选依赖安装失败（可忽略），继续..." -ForegroundColor Yellow
    }
}

# protobuf 锁定为 4.25.9：
#   - mediapipe==0.10.21 要求 protobuf<5（protobuf 5.x 下 mediapipe 导入会失败）；
#   - head-sdk / rena2-sdk-api / grpcio-tools 的依赖声明要求 protobuf 5.26+，
#     与 mediapipe 的要求互斥，因此 pip 安装时**必然**会打印
#     “dependency conflicts / protobuf ... incompatible” 之类的警告。
#   - 这是正常现象，不影响运行：实测 head-sdk 的 pb2 导入、序列化、gRPC stub
#     在 protobuf 4.25.9 下均正常；grpcio-tools 仅为代码生成工具，运行时不使用。
& $envPy -m pip install "protobuf==4.25.9" 2>&1 | Out-Null
Write-Host "（提示：如安装过程中出现 protobuf 相关依赖冲突警告，属正常现象，"
Write-Host "  mediapipe 与 head-sdk 对 protobuf 版本要求互斥，运行已验证正常，可忽略。）" -ForegroundColor DarkGray

# 5) 验证导入
Write-Step "验证依赖导入"
& $envPy -c "import cv2, fastapi, grpc, matplotlib, numpy, scipy, serial, uvicorn, websockets, yaml, head_sdk, rena2_sdk_api; print('Python 依赖导入正常')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "依赖验证失败" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "安装完成。接下来：插好 USB 串口设备 → 双击 start_windows.bat 启动。" -ForegroundColor Green
