#!/usr/bin/env python3
"""
配置服务器 - 处理机器人型号选择和硬件服务启动
端口: 9004
"""

import http.server
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = Path(__file__).parent
GRPC_DIR = SCRIPT_DIR / "../servo_tuning/head-sdk-face/head-server/src"
MAPPING_DIR = SCRIPT_DIR / "../servo_tuning/config"

# 全局状态
grpc_process = None
grpc_config = {}


class ConfigHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        """自定义日志格式"""
        print(f"[ConfigServer] {format % args}")

    def do_GET(self):
        """处理GET请求 - 查询状态"""
        parsed = urlparse(self.path)

        if parsed.path == "/api/status":
            self.send_json_response(get_status())

        elif parsed.path == "/api/configs":
            self.send_json_response(get_available_configs())

        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        """处理POST请求 - 启动/停止服务"""
        parsed = urlparse(self.path)

        if parsed.path == "/api/start_grpc":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))

            result = start_grpc_service(
                data.get('robot_head'),
                data.get('robot_number')
            )
            self.send_json_response(result)

        elif parsed.path == "/api/stop_grpc":
            result = stop_grpc_service()
            self.send_json_response(result)

        else:
            self.send_error(404, "Not Found")

    def send_json_response(self, data):
        """发送JSON响应"""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def do_OPTIONS(self):
        """处理CORS预检请求"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()


def get_status():
    """获取当前服务状态"""
    grpc_running = grpc_process is not None and grpc_process.poll() is None
    servotuning_running = check_port(9001)

    return {
        "grpc_running": grpc_running,
        "grpc_config": grpc_config if grpc_running else {},
        "servotuning_running": servotuning_running,
        "grpc_port": 2543 if grpc_running else None
    }


def get_available_configs():
    """获取可用的配置列表"""
    configs = {
        "heads": ["ULa", "G01", "G02"],
        "mappings": {}
    }

    # 扫描映射文件
    if MAPPING_DIR.exists():
        # ULa
        ula_mapping = MAPPING_DIR / "ULA_new.yaml"
        if ula_mapping.exists():
            configs["mappings"]["ULa"] = ["default"]

        # G01
        g01_mappings = sorted(MAPPING_DIR.glob("G01_*.yaml"))
        configs["mappings"]["G01"] = [
            f.stem.replace("G01_", "") for f in g01_mappings
        ]

        # G02
        g02_mappings = sorted(MAPPING_DIR.glob("G02_*.yaml"))
        configs["mappings"]["G02"] = [
            f.stem.replace("G02_", "") for f in g02_mappings
        ]

    return configs


def check_port(port):
    """检查端口是否被监听"""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    return result == 0


def start_grpc_service(robot_head, robot_number=None):
    """启动gRPC硬件服务"""
    global grpc_process, grpc_config

    # 验证输入
    if robot_head not in ["ULa", "G01", "G02"]:
        return {"success": False, "error": "无效的机器人头型号"}

    # 确定配置文件
    if robot_head == "ULa":
        config_file = GRPC_DIR / "servoConfig_25DV3_Ula.yaml"
        mapping_file = MAPPING_DIR / "ULA_new.yaml"
    else:
        if not robot_number:
            return {"success": False, "error": f"{robot_head}需要指定编号"}

        config_file = GRPC_DIR / f"servoConfig_25DV3_{robot_head}.yaml"
        mapping_file = MAPPING_DIR / f"{robot_head}_{robot_number}.yaml"

    # 检查文件存在
    if not config_file.exists():
        return {"success": False, "error": f"找不到配置文件: {config_file.name}"}

    if not mapping_file.exists():
        return {"success": False, "error": f"找不到映射文件: {mapping_file.name}"}

    # 停止旧服务
    if grpc_process and grpc_process.poll() is None:
        stop_grpc_service()
        time.sleep(2)

    # 启动新服务
    try:
        if sys.platform == "win32":
            # Windows 直接启动 head_grpc_server.py；优先使用转换过 COM 串口的运行时配置
            windows_config = Path(__file__).resolve().parents[2] / "windows" / "runtime" / "configs" / config_file.name
            if windows_config.is_file():
                config_file = windows_config
            grpc_process = subprocess.Popen(
                [sys.executable, str(GRPC_DIR / "head_grpc_server.py"), "--config", str(config_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(GRPC_DIR),
            )
        else:
            start_script = SCRIPT_DIR / "start_grpc_hardware.sh"
            grpc_process = subprocess.Popen(
                ["bash", str(start_script), str(config_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

        # 等待服务启动
        for _ in range(15):
            time.sleep(2)
            if check_port(2543):
                grpc_config = {
                    "robot_head": robot_head,
                    "robot_number": robot_number,
                    "config_file": config_file.name,
                    "mapping_file": mapping_file.name
                }
                return {
                    "success": True,
                    "message": f"gRPC服务已启动: {robot_head}" + (f" #{robot_number}" if robot_number else ""),
                    "config": grpc_config
                }

        return {"success": False, "error": "gRPC服务启动超时"}

    except Exception as e:
        return {"success": False, "error": f"启动失败: {str(e)}"}


def stop_grpc_service():
    """停止gRPC硬件服务"""
    global grpc_process, grpc_config

    if grpc_process and grpc_process.poll() is None:
        grpc_process.terminate()
        try:
            grpc_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            grpc_process.kill()

        grpc_config = {}
        return {"success": True, "message": "gRPC服务已停止"}

    return {"success": True, "message": "gRPC服务未运行"}


def run_server(port=9004):
    """启动HTTP服务器"""
    server_address = ('', port)
    httpd = http.server.HTTPServer(server_address, ConfigHandler)
    print(f"✅ 配置服务器已启动在端口 {port}")
    print(f"   API端点:")
    print(f"     GET  /api/status  - 查询服务状态")
    print(f"     GET  /api/configs - 获取可用配置")
    print(f"     POST /api/start_grpc - 启动硬件服务")
    print(f"     POST /api/stop_grpc  - 停止硬件服务")
    httpd.serve_forever()


if __name__ == "__main__":
    run_server()
