# exp_deb Windows 原生运行包

把整个 `windows` 文件夹放在 `exp_deb` 的上一级（即 `exp/windows`，与 `exp_deb` 同级，不入 exp 仓库，
本地保留即可），即可在 Windows 10/11 上原生使用表情调试平台的全部功能：硬件舵机控制、面捕/录制、
表情库、情绪演示、音源追踪、手机遥控。不需要 WSL，不需要 Git Bash。

## 目录结构

```text
exp/
├── exp_deb/                      # 原项目（Ubuntu/Linux 启动方式不变）
└── windows/                      # 本包（本地保留，不入库）
    ├── setup_windows.bat         # ① 一键安装依赖（无 face_servo 时自动创建 conda 环境）
    ├── start_windows.bat         # ② 一键启动（检测 COM 口 → 转换配置 → 起服务 → 开浏览器）
    ├── stop_windows.bat          # ③ 一键停止全部服务
    ├── setup_windows.ps1 / start_windows.ps1 / stop_windows.ps1
    ├── win_tools/detect_serial.py# 串口检测 + 舵机配置 COM 转换
    └── runtime/                  # 运行时生成（虚拟环境、转换后配置、日志、PID）
```

## 使用步骤

1. **前置条件**
   - Windows 10/11 64 位；
   - **Miniconda / Anaconda**（项目要求 conda 环境，Python 3.10）；
   - 机器人头、J7034G4 麦克风阵列的 USB 转串口驱动（CH340/FTDI/CDC 等）；
   - 建议整个路径不要包含空格（PowerShell 5.1 兼容性）。

2. **安装依赖**：双击 `setup_windows.bat`。
   - 检测到 conda 时，自动创建/复用 `face_servo` 环境（`conda create -n face_servo python=3.10`），
     依赖全部装进该环境，与项目 Ubuntu 侧的环境约定一致；
   - 自动把 `patches/` 里的两个 exp_deb 服务端补丁覆盖到 `exp_deb/expression_debugger/`
     （原文件首次备份到 `windows/runtime/patches_backup/`）；
   - 没有 conda 时会降级用普通 venv 并给出警告（此时可能不完全符合项目要求）。

3. **启动**：插好 USB 串口设备，双击 `start_windows.bat`。
   - 自动检测 COM 口 → 把 `servoConfig_25DV3_*.yaml` 的 `/dev/ttyACM*` 转成 `COMx`
     写入 `windows/runtime/configs/`（**不修改 exp_deb 原始文件**）；
   - 依次启动 `save_server`(:9002)、`servo_server`(:9001)、`head_grpc_server`(:2543)；
   - 自动打开 `http://localhost:9002/expression_debugger/expression_debugger_v2.html`。

4. **停止**：双击 `stop_windows.bat`。

## 可选参数（start_windows.bat 后追加）

```bat
start_windows.bat -HeadPort COM5 -MicPort COM6 -Head g02
start_windows.bat -HeadPort COM5 -NoBrowser
start_windows.bat -SkipSerial     :: 跳过串口检测，沿用已有配置
```

- `-HeadPort`：机器人头 COM 口（两个 CH340 设备无法自动区分时用这个手动指定）；
- `-MicPort`：麦克风阵列 COM 口（不指定时音源追踪自动查找）；
- `-Head`：机器人头型号 `ula` / `g01` / `g02`（默认读取上次选择 `.selected_head.json`，再默认 G02）。

## 已做的 Windows 兼容处理

- `expression_debugger/save_server.py`
  - 局域网 IP 获取增加 socket 回退（原来只调 Linux 的 `ip` 命令），手机遥控/面捕可拿到真实局域网 IP；
  - gRPC 服务启停跨平台：Windows 下用 `powershell` 查进程、`taskkill` 停止、直接
    `python head_grpc_server.py --config ...` 启动，不再依赖 `bash`/`pgrep`/`/proc`；
  - 网页选头时优先使用 `windows/runtime/configs/` 里转换过 COM 口的配置。
- `expression_debugger/config_server.py`
  - Windows 下同样直接启动 `head_grpc_server.py` 并优先使用 COM 转换配置。

## 已知边界（与 Ubuntu 版本行为一致或不可避免）

- **Python 环境**：项目要求 conda `face_servo` + Python 3.10。setup 会自动创建（已有则复用）；
  若已有 `face_servo` 但不是 3.10，会警告，建议 `conda remove -n face_servo --all` 后重跑 setup。
- **自然状态**：需要 `exp/droidmotion` 仓库在旁（servo_server 会自动从同级目录引入），依赖
  numpy/pyyaml（安装脚本已带）。droidmotion 缺失时该功能自动禁用，其余功能不受影响。
- **LiveLink Face 手机面捕**：手机和电脑需同一局域网，并允许 Windows 防火墙放行
  `9001/9002/2543/8008` 端口（首次启动会弹防火墙授权，全部勾选允许）。
- **音源追踪**：J7034G4 麦克风阵列需要插上；若与机器人头都是 CH340，自动区分可能不准，
  用 `-MicPort` / `-HeadPort` 指定。
- **标定/训练依赖**（torch、mediapipe）体积较大，setup 默认尝试安装，失败不影响运行；
  可用 `setup_windows.bat -SkipOptional` 跳过。
- 固定版本的 numpy/grpcio 支持 Python 3.10~3.12；超出范围可能装不上，请按项目要求使用 3.10。
- 硬件接线、舵机量程、断电默认姿态等仍以 `servoConfig_25DV3_*.yaml` 为准，Windows 只改串口名。

## 常见问题

- **“未找到项目 Python”**：先运行 `setup_windows.bat`（需要 conda 且能访问网络以创建 face_servo）。
- **启动后硬件没动**：看 `windows/runtime/logs/head_grpc_server.err.log`，确认串口号是否正确
  （`runtime/configs/` 里的 yaml 顶部 `port: COMx`），必要时用 `-HeadPort COMx` 重新生成。
- **手机连不上**：确认防火墙放行端口、页面左下角显示的 IP 是否为电脑局域网 IP。
- **端口被占用**：start 脚本检测到 9001/9002/2543 占用会自动先停止旧服务再启动。
