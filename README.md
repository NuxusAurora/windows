# exp_deb Windows 工具包

在 Windows 10/11 上原生使用 exp_deb 表情调试平台的配套工具包：一键安装 conda 环境
（`face_servo` + Python 3.10）、自动检测 COM 串口并转换舵机配置、一键启动/停止
`save_server` / `servo_server` / `head_grpc_server`，并自动应用 exp_deb 的 Windows 兼容补丁。

## 使用

1. 把 `windows` 文件夹放在 `exp_deb` 的上一级（`exp/windows`，与 `exp_deb` 同级）；
2. 双击 `setup_windows.bat`（自动创建/复用 conda `face_servo` 环境、安装依赖、应用补丁）；
3. 插好 USB 串口设备，双击 `start_windows.bat`（自动检测 COM 口、转换配置、起服务、开浏览器）；
4. 停止服务：双击 `stop_windows.bat`。

详细说明见 [README_windows.md](README_windows.md)。
