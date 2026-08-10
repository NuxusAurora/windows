# exp Windows 原生运行包

把整个 `windows` 文件夹放在 `core` / `motion` / `exp` 的同级目录下（旧布局回退
`droidcore-temp` / `droidmotion` / `exp_deb`），即可在 Windows 10/11 上原生使用
表情调试平台的全部功能：硬件舵机控制、面捕/录制、表情库、情绪演示、音源追踪、
手机遥控。不需要 WSL，不需要 Git Bash。

## 目录结构

```text
<项目根目录>/
├── core/                      # 可选：人脸/注视跟踪（旧名 droidcore-temp）
├── motion/                    # 可选：自然状态运动源（旧名 droidmotion）
├── exp/                       # 原项目（旧名 exp_deb），Windows 下同样零修改
└── windows/                   # 本包
    ├── setup_windows.bat      # ① 一键安装依赖（无 face_servo 时自动创建 conda 环境）
    ├── start_windows.bat      # ② 一键启动（检测 COM 口 → 转换配置 → 起服务 → 开浏览器）
    ├── stop_windows.bat       # ③ 一键停止全部服务
    ├── setup_windows.ps1 / start_windows.ps1 / stop_windows.ps1
    ├── launchers/             # 薄启动器：原样加载 exp 服务端，内存里做 Windows 适配
    │   ├── launch_save_server.py
    │   └── launch_config_server.py
    ├── win_tools/detect_serial.py  # 串口检测 + 舵机配置 COM 转换
    └── runtime/               # 运行时生成（日志、转换后配置、PID、串口信息等，不入库）
```

## 为什么不打补丁（v0.2 设计变更）

v0.1 会把补丁文件覆盖到 exp 的 `save_server.py` / `config_server.py`。新要求是
**不允许改动 core / motion / exp 三个文件夹**，因此 v0.2 改为：

1. 启动器用 importlib 从 exp 的**真实路径**加载服务端脚本——模块内部所有
   `Path(__file__).parent` 推导的路径天然指向 exp，无需复制或改写；
2. 仅在 `sys.platform == "win32"` 时替换少量函数：
   - 局域网 IP：UDP 套接字探测（Windows 没有 `ip` 命令），手机遥控/面捕可用；
   - gRPC 进程：PowerShell 查进程、`taskkill` 停止、直接
     `python head_grpc_server.py --config ...` 启动（不再依赖 bash/pgrep//proc）；
   - 选头时优先使用 `runtime/configs/` 里转换过 COM 口的配置；
   - `.selected_head.json` 写到 `runtime/`（不写 exp）。
3. exp 之后更新代码时，启动器自动加载新版，只要求这几个函数名不变；
   改名会明确报错而不是悄悄退化。

## 使用步骤

1. **前置条件**
   - Windows 10/11 64 位；
   - Miniconda / Anaconda（项目要求 conda 环境，Python 3.10）；
   - 机器人头、J7034G4 麦克风阵列的 USB 转串口驱动（CH340/FTDI/CDC 等）；
   - 建议整个路径不要包含空格（PowerShell 5.1 兼容性）。

2. **安装依赖**：双击 `setup_windows.bat`。
   - 检测到 conda 时，自动创建/复用 `face_servo` 环境（`conda create -n face_servo python=3.10`），
     依赖全部装进该环境；
   - 没有 conda 时会降级用普通 venv 并给出警告（此时可能不完全符合项目要求）；
   - 自检 exp / motion / core 目录与 `head_grpc_server.py` 是否存在（只读检查）。

3. **启动**：插好 USB 串口设备，双击 `start_windows.bat`。
   - 自动检测 COM 口 → 把 `servoConfig_25DV3_*.yaml` 的 `/dev/ttyACM*` 转成 `COMx`
     写入 `runtime/configs/`（**不修改 exp 原始文件**）；
   - 依次启动 `save_server`（:9002，走启动器）、`servo_server`（:9001，
     经 PYTHONPATH 桥接 motion/core）；`head_grpc_server`（:2543）不在脚本里
     启动——连好机器人头后，在调试器页面选择机器人头，由网页端按需启动
     （launcher 提供 Windows 下的 gRPC 启停适配）；
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
- `-Head`：仅影响启动时的提示信息（默认读取上次选择
  `runtime\.selected_head.json`）；实际选头在调试器网页里进行，结果同样写入
  `runtime\.selected_head.json`。

## 已知边界（与 Ubuntu 版本行为一致或不可避免）

- **Python 环境**：项目要求 conda `face_servo` + Python 3.10。setup 会自动创建
  （已有则复用）；若已有 `face_servo` 但不是 3.10，会警告，建议
  `conda remove -n face_servo --all` 后重跑 setup。
- **自然状态 / 人脸跟踪**：需要 `motion`（或 `droidmotion`）和 `core`
  （或 `droidcore-temp`）在旁。启动时用 `PYTHONPATH` 注入它们的 `src`，
  缺任一项目时对应功能自动禁用，其余功能不受影响。
- **LiveLink Face 手机面捕**：手机和电脑需同一局域网，并允许 Windows 防火墙放行
  `9001/9002/2543/8008` 端口（首次启动会弹防火墙授权，全部勾选允许）。
- **音源追踪**：J7034G4 麦克风阵列需要插上；若与机器人头都是 CH340，自动区分
  可能不准，用 `-MicPort` / `-HeadPort` 指定。
- **robot_config.html（端口 9004）**：主调试页不依赖它。需要时手动启动：
  `python launchers\launch_config_server.py`。
- **标定/训练依赖**（torch、mediapipe）体积较大，setup 默认尝试安装，失败不影响
  运行；可用 `setup_windows.bat -SkipOptional` 跳过。
- 固定版本的 numpy/grpcio 支持 Python 3.10~3.12；超出范围可能装不上，请按项目
  要求使用 3.10。
- 硬件接线、舵机量程、断电默认姿态等仍以 `servoConfig_25DV3_*.yaml` 为准，
  Windows 只改串口名。

## 常见问题

- **“未找到项目 Python”**：先运行 `setup_windows.bat`（需要 conda 且能访问网络
  以创建 face_servo）。
- **启动后硬件没动**：看 `runtime/logs/grpc.err.log`（gRPC 由网页端启动时，
  launcher 会把输出写到该文件），确认串口号是否正确（`runtime/configs/` 里的
  yaml 顶部 `port: COMx`），必要时用
  `-HeadPort COMx` 重新生成。
- **手机连不上**：确认防火墙放行端口、页面左下角显示的 IP 是否为电脑局域网 IP。
- **端口被占用**：start 脚本检测到 9001/9002/2543 被占用会自动先停止旧服务。
- **路径诊断**：`python launchers\launch_save_server.py --check` 会打印解析到的
  exp / head_grpc / COM 配置目录是否存在，方便排查目录布局问题。
