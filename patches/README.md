# exp_deb 配套补丁

这两个文件是工具包在 Windows 上全功能运行所需的 exp_deb 服务端补丁：

- `expression_debugger/save_server.py`
  - 局域网 IP 获取增加 socket 回退（手机遥控/面捕可拿到真实局域网 IP）；
  - gRPC 服务启停跨平台（Windows 用 PowerShell/taskkill 管理，不再依赖 bash/pgrep//proc）；
  - 网页选头时优先使用 `windows/runtime/configs/` 里转换过 COM 口的配置。
- `expression_debugger/config_server.py`
  - Windows 下直接启动 `head_grpc_server.py`，并优先使用 COM 转换配置。

## 应用方式

`setup_windows.bat` 会自动把这两个文件覆盖到 `exp_deb/expression_debugger/`
（原文件先备份到 `windows/runtime/patches_backup/`，仅首次备份）。

也可以手动复制：

```bat
copy /Y patches\expression_debugger\save_server.py   ..\exp_deb\expression_debugger\save_server.py
copy /Y patches\expression_debugger\config_server.py ..\exp_deb\expression_debugger\config_server.py
```

Linux 用户不需要这些补丁（原项目脚本本身就针对 Ubuntu 编写）。
