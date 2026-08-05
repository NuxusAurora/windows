# runtime

本目录由 windows 包运行时生成，不需要手工编辑：

- `.venv/`        安装依赖用的 Python 虚拟环境（setup_windows.bat 创建）
- `configs/`      由 detect_serial.py 从 exp_deb 的 servoConfig_*.yaml
                  转换出的 COM 口版本（不修改原始文件）
- `serial.json`   串口检测结果（head_port / mic_port）
- `python_path.txt` 项目 Python 路径（setup 写入：优先 conda face_servo/Python 3.10，start 据此启动服务）
- `logs/`         三个服务的 stdout/stderr 日志
- `pids.json`     启动脚本保存的进程 PID（stop 脚本据此停止服务）

删除本目录内容不会影响 exp_deb 原始文件；删除后重新运行 start_windows.bat 会重新生成。
