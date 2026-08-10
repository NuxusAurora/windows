#!/usr/bin/env python3
"""Windows 原生启动器：原样加载 exp/expression_debugger/save_server.py，
只在内存里替换 Linux 专属行为。exp（以及 core/motion）任何文件都不被修改。

原理：
  1. 用 importlib 从 exp 的真实路径加载 save_server.py —— 模块内部所有
     `Path(__file__).parent` 推导的路径天然指向 exp，无需改写；
  2. 仅当 sys.platform == "win32" 时，把下面几个函数替换为 Windows 版本：
     - _get_local_ip            UDP socket 探测局域网 IP（Windows 没有 ip 命令）
     - _grpc_pids/停止/启动     PowerShell 查进程、taskkill 停止、直接起
                               head_grpc_server.py（不再依赖 bash/pgrep//proc）
     - _runtime_head_config_name COM 转换配置不再生成 .local 副本，直接同名
     - _head_profile            优先使用 windows/runtime/configs 转换过 COM 口的配置
     - HEAD_STATE_FILE          选中状态写到 windows/runtime/（不写 exp）

用法：
  python launch_save_server.py          启动 save_server（端口 9002）
  python launch_save_server.py --check  只打印解析到的路径并退出（诊断用）
"""
from __future__ import annotations

import argparse
import importlib.util
import ipaddress
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

WINDOWS_ROOT = Path(__file__).resolve().parents[1]       # windows/
PROJECT_ROOT = WINDOWS_ROOT.parent                       # core/motion/exp/windows 的上级
RUNTIME_DIR = WINDOWS_ROOT / "runtime"
CONFIG_OUT_DIR = RUNTIME_DIR / "configs"
RUNTIME_HEAD_STATE = RUNTIME_DIR / ".selected_head.json"
GRPC_PORT = 2543


def _resolve_sibling(*names: str) -> Path:
    """按新布局名字优先找兄弟项目目录，找不到回退旧名字。"""
    for name in names:
        candidate = PROJECT_ROOT / name
        if candidate.is_dir():
            return candidate
    return PROJECT_ROOT / names[0]


EXP_ROOT = _resolve_sibling("exp", "exp_deb")
EXP_DEBUGGER_DIR = EXP_ROOT / "expression_debugger"
SAVE_SERVER_PY = EXP_DEBUGGER_DIR / "save_server.py"
HEAD_SERVER_DIR = EXP_ROOT / "servo_tuning" / "head-sdk-face" / "head-server" / "src"
HEAD_GRPC_PY = HEAD_SERVER_DIR / "head_grpc_server.py"


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


# ── Windows 专属实现（仅在 win32 下生效）──────────────────────────────

def _win_get_local_ip() -> str:
    """Windows 没有 ip 命令：用 UDP 套接字探测本机局域网地址。"""
    networks = tuple(ipaddress.ip_network(n) for n in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    ))
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            address = ipaddress.ip_address(probe.getsockname()[0])
        if any(address in network for network in networks):
            return str(address)
    except (OSError, ValueError):
        pass
    return "127.0.0.1"


def _win_grpc_processes() -> list[tuple[int, str]]:
    """列出 head_grpc_server.py 进程，返回 [(pid, cmdline)]。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*head_grpc_server*' } "
             "| ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine }"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return []
    result = []
    for line in out.splitlines():
        pid, _, cmdline = line.partition("|")
        if pid.strip().isdigit():
            result.append((int(pid.strip()), cmdline or ""))
    return result


def _win_grpc_pids() -> list[int]:
    return [pid for pid, _ in _win_grpc_processes()]


def _win_grpc_config_in_use() -> str:
    """返回正在运行的 gRPC 使用的 servoConfig 文件名；没有则返回空串。"""
    for _, cmdline in _win_grpc_processes():
        for part in re.split(r"[\0\s]+", cmdline):
            if "servoConfig" in part and part.lower().endswith((".yaml", ".yml")):
                return Path(part).name
    return ""


_GRPC_PROC = None  # Windows：记录由本服务启动的 gRPC 子进程


def _win_stop_grpc(timeout: int = 10):
    """停止正在运行的 gRPC 硬件服务，等待端口 2543 释放。"""
    global _GRPC_PROC
    pids = _win_grpc_pids()
    if not pids:
        _GRPC_PROC = None
        return True, "no grpc running"
    try:
        subprocess.run(
            ["taskkill", "/F", "/PID"] + [str(p) for p in pids],
            timeout=5, capture_output=True,
        )
    except Exception as exc:
        return False, f"停止 gRPC 失败: {exc}"
    if _GRPC_PROC is not None and _GRPC_PROC.pid in pids:
        _GRPC_PROC = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _port_open(GRPC_PORT) and not _win_grpc_pids():
            return True, "stopped"
        time.sleep(0.5)
    return False, "停止 gRPC 超时"


def _win_start_grpc(head_config_path, timeout: int = 30):
    """直接启动 head_grpc_server.py（Windows 没有 bash），等待端口 2543 监听。"""
    global _GRPC_PROC
    if not HEAD_GRPC_PY.is_file():
        return False, f"找不到 head_grpc_server.py: {HEAD_GRPC_PY}"
    env = dict(os.environ)
    env["NONINTERACTIVE"] = "1"
    try:
        _GRPC_PROC = subprocess.Popen(
            [sys.executable, str(HEAD_GRPC_PY), "--config", str(head_config_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env, cwd=str(HEAD_SERVER_DIR),
        )
    except Exception as exc:
        _GRPC_PROC = None
        return False, f"启动 gRPC 失败: {exc}"
    expected = Path(head_config_path).name
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(GRPC_PORT):
            if not expected or _win_grpc_config_in_use() == expected:
                return True, "started"
            return False, f"端口2543已运行，但配置不是 {expected}"
        time.sleep(1.5)
    if _port_open(GRPC_PORT):
        return False, "端口2543已运行但配置校验失败"
    return False, "gRPC 启动超时"


def _win_runtime_head_config_name(head_config_path) -> str:
    """COM 转换配置直接同名（不生成 .local 副本），校验时用原名。"""
    return Path(head_config_path).name


def _patch_windows(mod) -> None:
    """把 exp 的 save_server 模块替换为 Windows 行为（不改任何文件）。"""
    mod._get_local_ip = _win_get_local_ip
    mod._grpc_pids = _win_grpc_pids
    mod._grpc_config_in_use = _win_grpc_config_in_use
    mod._stop_grpc = _win_stop_grpc
    mod._start_grpc = _win_start_grpc
    mod._runtime_head_config_name = _win_runtime_head_config_name
    mod.HEAD_STATE_FILE = RUNTIME_HEAD_STATE

    # _head_profile 包一层：优先使用转换过 COM 口的运行时配置
    orig_head_profile = mod._head_profile

    def _win_head_profile(mapping_file):
        label, config_path = orig_head_profile(mapping_file)
        converted = CONFIG_OUT_DIR / config_path.name
        if converted.is_file():
            config_path = converted
        return label, config_path

    mod._head_profile = _win_head_profile
    print(f"[windows] save_server 已启用 Windows 适配（COM 配置目录: {CONFIG_OUT_DIR}）")


def load_exp_module() -> object:
    """从 exp 原路径加载 save_server.py（模块内部路径自动指向 exp）。"""
    if not SAVE_SERVER_PY.is_file():
        raise RuntimeError(f"找不到 exp 的 save_server.py: {SAVE_SERVER_PY}")
    sys.path.insert(0, str(EXP_DEBUGGER_DIR))  # 供 save_server 内部 import llm_client
    spec = importlib.util.spec_from_file_location("exp_save_server", str(SAVE_SERVER_PY))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {SAVE_SERVER_PY}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["exp_save_server"] = mod
    spec.loader.exec_module(mod)
    return mod


def check_paths() -> int:
    ok = True
    print(f"平台:          {sys.platform}")
    print(f"Python:        {sys.executable}")
    print(f"项目上级:      {PROJECT_ROOT}")
    for label, path in (
        ("exp", EXP_ROOT),
        ("save_server.py", SAVE_SERVER_PY),
        ("head_grpc_server.py", HEAD_GRPC_PY),
    ):
        exists = path.is_file() if path.suffix else path.exists()
        print(f"  {'OK ' if exists else 'MISS'} {label}: {path}")
        ok = ok and exists
    print(f"  GEN COM 配置目录: {CONFIG_OUT_DIR}（start 时由 detect_serial 生成）")
    print(f"  GEN 选中状态文件: {RUNTIME_HEAD_STATE}（网页选头后生成）")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="启动 exp 的 save_server（Windows 适配版启动器）")
    parser.add_argument("--check", action="store_true", help="只打印解析到的路径并退出")
    args = parser.parse_args()

    if args.check:
        return check_paths()

    mod = load_exp_module()
    if sys.platform == "win32":
        _patch_windows(mod)
    else:
        print(f"[windows] 当前平台 {sys.platform} 非 Windows，按 exp 原始逻辑启动。")

    print(f"表情保存服务启动: http://localhost:{mod.PORT}")
    print(f"表情库目录: {mod.EXPRESSIONS_BASE_DIR}")
    print(f"面捕动作目录: {mod.CAPTURES_DIR}")
    print(f"多模态动作目录: {mod.MULTIACTIONS_DIR}")
    print(f"截取表情目录: {mod.POSES_DIR}")
    print(f"调试器页面: http://localhost:{mod.PORT}/expression_debugger/expression_debugger_v2.html")
    mod.ThreadingHTTPServer(("0.0.0.0", mod.PORT), mod.SaveHandler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
