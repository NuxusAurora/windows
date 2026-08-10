# exp Windows 原生工具包

在 Windows 10/11 上原生运行 exp 表情调试平台的配套工具包：一键安装 conda 环境
（`face_servo` + Python 3.10）、自动检测 COM 串口并转换舵机配置、一键启动/停止
`save_server` / `servo_server`（`head_grpc_server` 由调试器网页端选头时按需启动）。

## 布局要求

`windows` 包与三个项目**同级**（新布局）：

```text
<项目根目录>/
├── core/       # 旧布局名：droidcore-temp（人脸/注视跟踪，可选）
├── motion/     # 旧布局名：droidmotion（自然状态运动源，可选）
├── exp/        # 旧布局名：exp_deb（表情调试平台）
└── windows/    # 本包
```

找不到新名字时自动回退旧目录名，两种布局都可用。

## 不修改三个项目

- setup **不覆盖、不打补丁** exp 的任何文件（不再有 v0.1 的「补丁覆盖」步骤）；
- exp 的 `save_server.py` / `config_server.py` 由 `launchers/` 里的薄启动器**原样加载**，
  仅在内存中替换 Windows 专属行为（局域网 IP、gRPC 启停、COM 配置优先）；
- 转换过 COM 口的舵机配置、日志、PID、串口信息、选中状态全部落在 `windows/runtime/`；
- core / motion 仅被**只读**使用：启动 servo_server 时通过 `PYTHONPATH` 注入
  `motion/src` 和 `core/src`，桥接 exp 内部硬编码的旧目录名 import。

## 使用

1. 把 `windows` 文件夹放在与 `exp`（或 `exp_deb`）同级的目录下；
2. 双击 `setup_windows.bat`（自动创建/复用 conda `face_servo` 环境、安装依赖）；
3. 插好 USB 串口设备，双击 `start_windows.bat`（自动检测 COM 口、转换配置、起服务、开浏览器）；
4. 停止服务：双击 `stop_windows.bat`。

详细说明见 [README_windows.md](README_windows.md)。
