#!/usr/bin/env python3
"""Windows 原生启动器：原样加载 exp/expression_debugger/config_server.py，
只在内存里替换 Linux 专属行为（不修改 exp 任何文件）。

config_server（端口 9004）是「机器人型号选择」备用页（robot_config.html）用的
HTTP 服务；主调试器（expression_debugger_v2.html）不依赖它。需要时用本启动器
手动启动即可。

用法：
  python launch_config_server.py          启动 config_server（端口 9004）
  python launch_config_server.py --check  只打印解析到的路径并退出（诊断用）
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

WINDOWS_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WINDOWS_ROOT.parent
RUNTIME_DIR = WINDOWS_ROOT / "runtime"
CONFIG_OUT_DIR = RUNTIME_DIR / "configs"
GRPC_PORT = 2543


def _resolve_sibling(*names: str) -> Path:
    for name in names:
        candidate = PROJECT_ROOT / name
        if candidate.is_dir():
            return candidate
    return PROJECT_ROOT / names[0]


EXP_ROOT = _resolve_sibling("exp", "exp_deb")
EXP_DEBUGGER_DIR = EXP_ROOT / "expression_debugger"
CONFIG_SERVER_PY = EXP_DEBUGGER_DIR / "config_server.py"


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def _win_start_grpc_service(mod, robot_head: str, robot_number=None):
    """Windows 版：直接启动 head_grpc_server.py，优先用 COM 转换配置。"""
    if robot_head not in ["ULa", "G01", "G02"]:
        return {"success": False, "error": "无效的机器人头型号"}

    if robot_head == "ULa":
        config_file = mod.GRPC_DIR / "servoConfig_25DV3_Ula.yaml"
        mapping_file = mod.MAPPING_DIR / "ULA_new.yaml"
    else:
        if not robot_number:
            return {"success": False, "error": f"{robot_head}需要指定编号"}
        config_file = mod.GRPC_DIR / f"servoConfig_25DV3_{robot_head}.yaml"
        mapping_file = mod.MAPPING_DIR / f"{robot_head}_{robot_number}.yaml"

    if not config_file.exists():
        return {"success": False, "error": f"找不到配置文件: {config_file.name}"}
    if not mapping_file.exists():
        return {"success": False, "error": f"找不到映射文件: {mapping_file.name}"}

    # 优先使用转换过 COM 口的运行时配置（不修改 exp 原始 YAML）
    converted = CONFIG_OUT_DIR / config_file.name
    if converted.is_file():
        config_file = converted

    if mod.grpc_process is not None and mod.grpc_process.poll() is None:
        mod.stop_grpc_service()
        time.sleep(2)

    server_py = mod.GRPC_DIR / "head_grpc_server.py"
    if not server_py.is_file():
        return {"success": False, "error": f"找不到 head_grpc_server.py: {server_py}"}
    try:
        mod.grpc_process = subprocess.Popen(
            [sys.executable, str(server_py), "--config", str(config_file)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(mod.GRPC_DIR),
        )
        for _ in range(15):
            time.sleep(2)
            if _port_open(GRPC_PORT):
                mod.grpc_config = {
                    "robot_head": robot_head,
                    "robot_number": robot_number,
                    "config_file": config_file.name,
                    "mapping_file": mapping_file.name,
                }
                return {
                    "success": True,
                    "message": f"gRPC服务已启动: {robot_head}" + (f" #{robot_number}" if robot_number else ""),
                    "config": mod.grpc_config,
                }
        return {"success": False, "error": "gRPC服务启动超时"}
    except Exception as exc:
        return {"success": False, "error": f"启动失败: {str(exc)}"}


def _patch_windows(mod) -> None:
    mod.start_grpc_service = _win_start_grpc_service
    print(f"[windows] config_server 已启用 Windows 适配（COM 配置目录: {CONFIG_OUT_DIR}）")


def load_exp_module() -> object:
    if not CONFIG_SERVER_PY.is_file():
        raise RuntimeError(f"找不到 exp 的 config_server.py: {CONFIG_SERVER_PY}")
    spec = importlib.util.spec_from_file_location("exp_config_server", str(CONFIG_SERVER_PY))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {CONFIG_SERVER_PY}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["exp_config_server"] = mod
    spec.loader.exec_module(mod)
    return mod


def check_paths() -> int:
    ok = True
    print(f"平台:          {sys.platform}")
    print(f"Python:        {sys.executable}")
    print(f"项目上级:      {PROJECT_ROOT}")
    for label, path in (
        ("exp", EXP_ROOT),
        ("config_server.py", CONFIG_SERVER_PY),
    ):
        exists = path.is_file() if path.suffix else path.exists()
        print(f"  {'OK ' if exists else 'MISS'} {label}: {path}")
        ok = ok and exists
    print(f"  GEN COM 配置目录: {CONFIG_OUT_DIR}（start 时由 detect_serial 生成）")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="启动 exp 的 config_server（Windows 适配版启动器）")
    parser.add_argument("--check", action="store_true", help="只打印解析到的路径并退出")
    args = parser.parse_args()

    if args.check:
        return check_paths()

    mod = load_exp_module()
    if sys.platform == "win32":
        _patch_windows(mod)
    else:
        print(f"[windows] 当前平台 {sys.platform} 非 Windows，按 exp 原始逻辑启动。")
    mod.run_server()
    return 0


if __name__ == "__main__":
    sys.exit(main())
