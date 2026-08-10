# runtime

本目录由 windows 包运行时生成，不需要手工编辑：

- `.venv/`            安装依赖用的 Python 虚拟环境（无 conda 时降级创建）
- `configs/`          由 detect_serial.py 从 exp 的 servoConfig_*.yaml
                      转换出的 COM 口版本（不修改原始文件）
- `serial.json`       串口检测结果（head_port / mic_port）
- `python_path.txt`   项目 Python 路径（setup 写入：优先 conda face_servo/Python 3.10）
- `logs/`             服务 stdout/stderr 日志
- `pids.json`         启动脚本保存的进程 PID（stop 脚本据此停止服务）
- `.selected_head.json` 网页选择的机器人头状态（save_server 启动器写入，
                      不写 exp 目录）

删除本目录内容不影响 core / motion / exp 任何文件；删除后重新运行
start_windows.bat 会自动重新生成。

`launchers/` 不在本目录：它是随包发布的启动器源码，位于 `windows/launchers/`。
