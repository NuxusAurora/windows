#!/usr/bin/env python3
"""表情保存服务：静态模板保存 ARKit BS，面捕动作另存脖子三舵机时间序列。"""
import csv
import ipaddress
import json
import math
import os
import re
import socket
import subprocess
import sys
import time
import wave
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

try:
    import llm_client
except Exception:  # pragma: no cover - 模块缺失时仅禁用 AI 接口，不影响其他功能
    llm_client = None

EXP_DEB_ROOT = Path(__file__).resolve().parents[1]
EXPRESSIONS_BASE_DIR = EXP_DEB_ROOT / "motion_assets"

# 手机遥控指令缓存
_remote_commands: list = []
_remote_serial: int = 0

# 舵机状态代理（桌面端推送 → 手机端轮询）
_servo_state: dict = {}
_servo_state_serial: int = 0
CAPTURES_DIR = EXP_DEB_ROOT / "motion_assets" / "actions"
MULTIACTIONS_DIR = EXP_DEB_ROOT / "motion_assets" / "multiactions"
AUDIOS_DIR = EXP_DEB_ROOT / "motion_assets" / "audios"
POSES_DIR = EXP_DEB_ROOT / "motion_assets" / "poses"
CATEGORIES = {"basic", "subtle", "intense"}
PORT = int(os.environ.get("EXPRESSIONS_PORT", "9002"))

# 机器人头选择 → gRPC 硬件服务（端口2543）启停
GRPC_PORT = 2543
GRPC_SCRIPT = Path(__file__).resolve().parent / "start_grpc_hardware.sh"
# Windows 原生运行时：优先使用 windows 包转换过 COM 串口的配置（不修改原始 YAML）
WINDOWS_CONFIGS_DIR = Path(__file__).resolve().parents[2] / "windows" / "runtime" / "configs"
HEAD_STATE_FILE = Path(__file__).resolve().parent / ".selected_head.json"

ARKIT_BLENDSHAPES = (
    "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight",
    "cheekPuff", "cheekSquintLeft", "cheekSquintRight", "eyeBlinkLeft", "eyeBlinkRight",
    "eyeLookDownLeft", "eyeLookDownRight", "eyeLookInLeft", "eyeLookInRight", "eyeLookOutLeft",
    "eyeLookOutRight", "eyeLookUpLeft", "eyeLookUpRight", "eyeSquintLeft", "eyeSquintRight",
    "eyeWideLeft", "eyeWideRight", "jawForward", "jawLeft", "jawOpen", "jawRight",
    "mouthClose", "mouthDimpleLeft", "mouthDimpleRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthFunnel", "mouthLeft", "mouthLowerDownLeft", "mouthLowerDownRight", "mouthPressLeft",
    "mouthPressRight", "mouthPucker", "mouthRight", "mouthRollLower", "mouthRollUpper",
    "mouthShrugLower", "mouthShrugUpper", "mouthSmileLeft", "mouthSmileRight", "mouthStretchLeft",
    "mouthStretchRight", "mouthUpperUpLeft", "mouthUpperUpRight", "noseSneerLeft", "noseSneerRight",
    "tongueOut",
)
ARKIT_BLENDSHAPE_SET = set(ARKIT_BLENDSHAPES)
NECK_SERVOS = ("head_dian", "head_yao", "head_bai")
LEGACY_CAPTURE_COLUMNS = ("time_s", "title", "description", "tags", *ARKIT_BLENDSHAPES)
CAPTURE_COLUMNS = (*LEGACY_CAPTURE_COLUMNS, *NECK_SERVOS)
MULTIACTION_COLUMNS = (*CAPTURE_COLUMNS, "audio_filename")

# 情绪标签到VA范围的映射
EMOTION_VA_MAP = {
    "joy": {"v": [0.5, 1.0], "a": [0.0, 0.7]},
    "happy": {"v": [0.5, 1.0], "a": [0.0, 0.7]},
    "sadness": {"v": [-1.0, -0.3], "a": [-1.0, -0.2]},
    "sad": {"v": [-1.0, -0.3], "a": [-1.0, -0.2]},
    "anger": {"v": [-0.8, -0.2], "a": [0.3, 1.0]},
    "fear": {"v": [-0.8, -0.3], "a": [0.5, 1.0]},
    "disgust": {"v": [-0.7, -0.2], "a": [-0.3, 0.5]},
    "surprise": {"v": [0.0, 0.5], "a": [0.5, 1.0]},
    "trust": {"v": [0.3, 0.8], "a": [-0.5, 0.3]},
    "anticipation": {"v": [0.2, 0.7], "a": [0.2, 0.8]},
}

SHOW_EMOTIONS = (
    "joy", "trust", "fear", "surprise", "sadness", "disgust", "anger", "anticipation"
)
SHOW_CALM_TEMPLATE = {"eyeBlinkLeft": 0.045, "eyeBlinkRight": 0.042}


# 页面经 HTTP 打开后 file:// 的 fetch 限制消失，数字人 glb 才能加载。
STATIC_ROOT = EXP_DEB_ROOT

# Show → V2 桥接：Show 提交混合后的 BS，V2 轮询取走并驱动数字人/舵机
_latest_blendshapes: dict = {}
_latest_blendshapes_source: str = ""
_latest_blendshapes_serial: int = 0

# BS↔舵机映射表和底层硬件配置。启动页只传文件名，服务端在这两个目录内解析，
# 页面显示、面捕和 HeadSDK 因而使用同一颗机器人头的配置。
SERVO_TUNING_DIR = (Path(__file__).parent.parent / "servo_tuning").resolve()
MAPPING_DIR = SERVO_TUNING_DIR / "config"
HEAD_CONFIG_DIR = SERVO_TUNING_DIR / "head-sdk-face" / "head-server" / "src"
DEFAULT_MAPPING = "ULA_new.yaml"
HEAD_CONFIGS = {
    "ula": ("ULa", "servoConfig_25DV3_Ula.yaml"),
    "g01": ("G01", "servoConfig_25DV3_G01.yaml"),
    "g02": ("G02", "servoConfig_25DV3_G02.yaml"),
}


# 标准CSV格式常量（与neutral.csv/happy.csv格式对齐）
STANDARD_CSV_BLENDSHAPES = (
    "EyeBlinkLeft", "EyeLookDownLeft", "EyeLookInLeft", "EyeLookOutLeft", "EyeLookUpLeft",
    "EyeSquintLeft", "EyeWideLeft", "EyeBlinkRight", "EyeLookDownRight", "EyeLookInRight",
    "EyeLookOutRight", "EyeLookUpRight", "EyeSquintRight", "EyeWideRight", "JawForward",
    "JawRight", "JawLeft", "JawOpen", "MouthClose", "MouthFunnel", "MouthPucker",
    "MouthRight", "MouthLeft", "MouthSmileLeft", "MouthSmileRight", "MouthFrownLeft",
    "MouthFrownRight", "MouthDimpleLeft", "MouthDimpleRight", "MouthStretchLeft",
    "MouthStretchRight", "MouthRollLower", "MouthRollUpper", "MouthShrugLower",
    "MouthShrugUpper", "MouthPressLeft", "MouthPressRight", "MouthLowerDownLeft",
    "MouthLowerDownRight", "MouthUpperUpLeft", "MouthUpperUpRight", "BrowDownLeft",
    "BrowDownRight", "BrowInnerUp", "BrowOuterUpLeft", "BrowOuterUpRight", "CheekPuff",
    "CheekSquintLeft", "CheekSquintRight", "NoseSneerLeft", "NoseSneerRight", "TongueOut",
)
STANDARD_CSV_HEAD_PARAMS = (
    "HeadYaw", "HeadPitch", "HeadRoll",
    "LeftEyeYaw", "LeftEyePitch", "LeftEyeRoll",
    "RightEyeYaw", "RightEyePitch", "RightEyeRoll",
)
STANDARD_CSV_HEADER = ["Timecode", "BlendshapeCount"] + list(STANDARD_CSV_BLENDSHAPES) + list(STANDARD_CSV_HEAD_PARAMS)


def _normalize_bs_name_to_standard(name):
    """将小驼峰ARKit BS名称转换为标准CSV大驼峰格式 (eyeBlinkLeft -> EyeBlinkLeft)"""
    if not name:
        return name
    return name[0].upper() + name[1:]


def _generate_standard_csv(name, blendshapes, head_params=None, is_multi_frame=False, frames=None, fps=30):
    """
    生成标准CSV格式（与neutral.csv/happy.csv对齐）

    Args:
        name: 表情名称（单帧）或用于多帧的基础名称
        blendshapes: dict，小驼峰格式的ARKit blendshapes {eyeBlinkLeft: 0.5, ...}
        head_params: dict，可选的头部参数 {HeadYaw: 0, HeadPitch: 0, ...}
        is_multi_frame: bool，是否为多帧表情
        frames: list，多帧数据 [{time_s: 0.0, blendshapes: {...}, servos: {...}}, ...]
        fps: int，帧率（默认30fps，用于Timecode的FF计算）

    Returns:
        str: CSV格式文本
    """
    from io import StringIO
    output = StringIO()
    writer = csv.writer(output)

    # 写入header
    writer.writerow(STANDARD_CSV_HEADER)

    if is_multi_frame and frames:
        # 多帧格式：每帧一行，Timecode为HH:MM:SS:FF.MMM格式
        for frame in frames:
            time_s = frame.get("time_s", 0.0)
            frame_bs = frame.get("blendshapes", blendshapes)

            # 转换time_s为Timecode格式 (HH:MM:SS:FR.AME)
            # 使用简化格式：将小数秒直接编码为两段数字
            hours = int(time_s // 3600)
            minutes = int((time_s % 3600) // 60)
            seconds = int(time_s % 60)
            fractional = time_s % 1
            # 将小数秒转换为5位数字表示 (00.000 到 99.999)
            fractional_int = int(round(fractional * 100000))
            frame_part = fractional_int // 1000  # 前2位
            subframe_part = fractional_int % 1000  # 后3位
            timecode = f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frame_part:02d}.{subframe_part:03d}"

            row = [timecode, "61"]

            # 添加52个blendshapes（转换为PascalCase并保持10位小数）
            for std_name in STANDARD_CSV_BLENDSHAPES:
                # 将标准名称转换回小驼峰查找原始数据
                orig_name = std_name[0].lower() + std_name[1:]
                value = frame_bs.get(orig_name, 0.0)
                row.append(f"{float(value):.10f}")

            # 添加9个head/eye参数（从servos映射或使用默认值0）
            frame_servos = frame.get("servos", {})
            frame_head = frame.get("head_params", head_params or {})

            # 映射neck servos到head rotation参数
            # head_dian -> HeadPitch, head_yao -> HeadYaw, head_bai -> HeadRoll
            # 将0-1舵机值转换为-90到90度的角度范围
            head_mapping = {
                "HeadYaw": (frame_servos.get("head_yao", 0.5) - 0.5) * 180,
                "HeadPitch": (frame_servos.get("head_dian", 0.5) - 0.5) * 180,
                "HeadRoll": (frame_servos.get("head_bai", 0.5) - 0.5) * 180,
            }

            for param in STANDARD_CSV_HEAD_PARAMS:
                # 优先使用frame_head，其次使用head_mapping，最后默认0
                if param in frame_head:
                    value = frame_head[param]
                elif param in head_mapping:
                    value = head_mapping[param]
                else:
                    value = 0.0
                row.append(f"{float(value):.10f}")

            writer.writerow(row)
    else:
        # 单帧格式：Timecode为表情名称
        row = [name, "61"]

        # 添加52个blendshapes
        for std_name in STANDARD_CSV_BLENDSHAPES:
            orig_name = std_name[0].lower() + std_name[1:]
            value = blendshapes.get(orig_name, 0.0)
            row.append(f"{float(value):.10f}")

        # 添加9个head/eye参数
        head_params = head_params or {}
        for param in STANDARD_CSV_HEAD_PARAMS:
            value = head_params.get(param, 0.0)
            row.append(f"{float(value):.10f}")

        writer.writerow(row)

    return output.getvalue()


def _get_local_ip():
    """返回手机可访问的局域网 IP，忽略代理和容器虚拟网卡。"""
    networks = tuple(map(ipaddress.ip_network, (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    )))
    try:
        output = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show", "up", "scope", "global"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        for line in output.splitlines():
            _, interface, _, cidr, *_ = line.split()
            interface = interface.split("@", 1)[0]
            address = ipaddress.ip_address(cidr.split("/", 1)[0])
            if interface.startswith(("docker", "veth", "virbr", "br-", "tun", "tap", "wg", "tailscale")):
                continue
            if any(address in network for network in networks):
                return str(address)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    # Windows 等没有 ip 命令的平台：用 UDP 套接字探测本机局域网地址（与 servo_server 同款回退）
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            address = ipaddress.ip_address(probe.getsockname()[0])
        if any(address in network for network in networks):
            return str(address)
    except (OSError, ValueError):
        pass
    return "127.0.0.1"


def _head_numbers(prefix):
    """扫描 config 目录里 <PREFIX>_<n>.yaml 面捕映射的编号，按数值升序。"""
    numbers = []
    if not MAPPING_DIR.is_dir():
        return numbers
    try:
        for path in MAPPING_DIR.glob(f"{prefix}_*.yaml"):
            match = re.fullmatch(rf"{prefix}_(\d+)", path.stem, re.IGNORECASE)
            if match:
                numbers.append(int(match.group(1)))
    except OSError:
        pass
    return sorted(numbers)


def _head_choices():
    """网页机器人头选择的可选项。"""
    choices = []
    for key, (label, config_name) in HEAD_CONFIGS.items():
        entry = {
            "id": key,
            "label": label,
            "config": config_name,
            "config_path": str(HEAD_CONFIG_DIR / config_name),
            "available": (HEAD_CONFIG_DIR / config_name).is_file(),
        }
        if key in ("g01", "g02"):
            entry["numbers"] = _head_numbers(key.upper())
        else:
            entry["mapping"] = DEFAULT_MAPPING
        choices.append(entry)
    return choices


def _mapping_name_for_selection(head, number):
    """按 {head, number} 得到合法的 mapping 文件名（不存在的文件会抛错）。"""
    head = str(head).strip().lower()
    if head not in HEAD_CONFIGS:
        raise ValueError(f"不支持的机器人头: {head}")
    label = HEAD_CONFIGS[head][0]
    if label == "ULa":
        if not (MAPPING_DIR / DEFAULT_MAPPING).is_file():
            raise ValueError(f"缺少 ULa 面捕映射配置文件: {DEFAULT_MAPPING}")
        return DEFAULT_MAPPING
    text = str(number or "").strip()
    if not re.fullmatch(r"\d+", text):
        raise ValueError("编号只能包含数字")
    name = f"{label}_{int(text)}.yaml"
    path = (MAPPING_DIR / name).resolve()
    if path.parent != MAPPING_DIR or not path.is_file():
        raise ValueError(f"缺少 {label} {int(text)} 号的面捕映射配置文件: {name}")
    return name


def _port_open(port, host="127.0.0.1"):
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def _grpc_processes():
    """跨平台列出 head_grpc_server.py 进程，返回 [(pid, cmdline)]。"""
    if sys.platform == "win32":
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
    try:
        out = subprocess.run(
            ["pgrep", "-f", r"[h]ead_grpc_server\.py"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except Exception:
        return []
    result = []
    for p in out.split():
        if p.strip().isdigit():
            try:
                with open(f"/proc/{p.strip()}/cmdline", "rb") as stream:
                    cmdline = stream.read().decode("utf-8", "replace")
            except OSError:
                cmdline = ""
            result.append((int(p.strip()), cmdline))
    return result


def _grpc_pids():
    return [pid for pid, _ in _grpc_processes()]


def _grpc_config_in_use():
    """返回正在运行的 gRPC 使用的 servoConfig 文件名；没有则返回空串。"""
    for _, cmdline in _grpc_processes():
        for part in re.split(r"[\0\s]+", cmdline):
            if "servoConfig" in part and part.lower().endswith((".yaml", ".yml")):
                return Path(part).name
    return ""


_GRPC_PROC = None  # Windows：记录由本进程启动的 gRPC 子进程


def _stop_grpc(timeout=10):
    """停止正在运行的 gRPC 硬件服务，等待端口2543释放。"""
    global _GRPC_PROC
    pids = _grpc_pids()
    if not pids:
        _GRPC_PROC = None
        return True, "no grpc running"
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/PID"] + [str(p) for p in pids],
                timeout=5, capture_output=True,
            )
        else:
            subprocess.run(["kill"] + [str(p) for p in pids], timeout=5)
    except Exception as exc:
        return False, f"停止 gRPC 失败: {exc}"
    if _GRPC_PROC is not None and _GRPC_PROC.pid in pids:
        _GRPC_PROC = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _port_open(GRPC_PORT) and not _grpc_pids():
            return True, "stopped"
        time.sleep(0.5)
    return False, "停止 gRPC 超时"


def _start_grpc(head_config_path, timeout=30):
    """后台启动 gRPC 硬件服务（Linux 走 start_grpc_hardware.sh，Windows 直接起 head_grpc_server.py），等待端口2543监听。"""
    global _GRPC_PROC
    env = dict(os.environ)
    env["NONINTERACTIVE"] = "1"
    if sys.platform == "win32":
        grpc_src = HEAD_CONFIG_DIR
        server_py = grpc_src / "head_grpc_server.py"
        if not server_py.is_file():
            return False, f"找不到 head_grpc_server.py: {server_py}"
        try:
            _GRPC_PROC = subprocess.Popen(
                [sys.executable, str(server_py), "--config", str(head_config_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=env, cwd=str(grpc_src),
            )
        except Exception as exc:
            _GRPC_PROC = None
            return False, f"启动 gRPC 失败: {exc}"
    else:
        if not GRPC_SCRIPT.is_file():
            return False, "start_grpc_hardware.sh 不存在"
        try:
            subprocess.Popen(
                ["bash", str(GRPC_SCRIPT), str(head_config_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=env, cwd=str(Path(__file__).resolve().parent),
            )
        except Exception as exc:
            return False, f"启动 gRPC 失败: {exc}"
    expected = Path(head_config_path).name
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(GRPC_PORT):
            if not expected or _grpc_config_in_use() == expected:
                return True, "started"
            return False, f"端口2543已运行，但配置不是 {expected}"
        time.sleep(1.5)
    if _port_open(GRPC_PORT):
        return False, "端口2543已运行但配置校验失败"
    return False, "gRPC 启动超时"


def _load_head_state():
    try:
        return json.loads(HEAD_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_head_state(state):
    try:
        HEAD_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def _mapping_file(requested):
    name = requested or DEFAULT_MAPPING
    if Path(name).name != name or not re.fullmatch(r"[\w-]+\.ya?ml", name, re.IGNORECASE):
        raise ValueError(f"Invalid mapping filename: {name}")
    path = (MAPPING_DIR / name).resolve()
    if path.parent != MAPPING_DIR or not path.is_file():
        raise ValueError(f"Mapping file not found: {name}")
    return path


def _head_profile(mapping_file):
    prefix = mapping_file.stem.split("_", 1)[0].lower()
    if prefix not in HEAD_CONFIGS:
        raise ValueError(f"Unsupported robot head mapping: {mapping_file.name}")
    label, config_name = HEAD_CONFIGS[prefix]
    config_path = HEAD_CONFIG_DIR / config_name
    if not config_path.is_file():
        raise ValueError(f"Head config not found: {config_path}")
    # Windows：优先使用 windows 包转换过 COM 串口的运行时配置（不修改原始 YAML）
    if sys.platform == "win32":
        windows_config = WINDOWS_CONFIGS_DIR / config_name
        if windows_config.is_file():
            config_path = windows_config
    return label, config_path


def _default_pose(config_path):
    """读取 HeadSDK 的断电初始位置；保持 save_server 仅依赖标准库。"""
    number = r"-?\d+(?:\.\d+)?"
    pattern = re.compile(
        rf"name:\s*['\"](?P<name>\w+)['\"].*?"
        rf"jdStart:\s*(?P<start>{number}).*?jdMax:\s*(?P<max>{number}).*?"
        rf"jdMin:\s*(?P<min>{number}).*?dir:\s*(?P<dir>[01])"
    )
    pose = {}
    for match in pattern.finditer(config_path.read_text(encoding="utf-8")):
        start, maximum, minimum = map(
            float, (match["start"], match["max"], match["min"])
        )
        value = abs((start - minimum) / (maximum - minimum))
        if match["dir"] == "1":
            value = 1 - value
        pose[match["name"]] = round(value, 2)
    if not pose:
        raise ValueError(f"No servo defaults found in: {config_path}")
    return pose


def _validate_blendshapes(blendshapes):
    if not isinstance(blendshapes, dict) or not blendshapes:
        return "No ARKit blendshape data"
    for name, value in blendshapes.items():
        if name not in ARKIT_BLENDSHAPE_SET:
            return f"Invalid ARKit blendshape name: {name}"
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            return f"Invalid blendshape value: {name}: {value}"
    return None


def _first_blendshape_frame(path):
    """读取表情 YAML 的第一帧；固定格式无需引入 PyYAML。"""
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"(?m)^[ \t]+blendshapes:\s*\n((?:[ \t]+\w+:[ \t]*-?\d+(?:\.\d+)?[ \t]*\n?)+)",
        text,
    )
    if not match:
        return None
    frame = {
        name: float(value)
        for name, value in re.findall(r"(\w+):\s*(-?\d+(?:\.\d+)?)", match.group(1))
    }
    return frame if not _validate_blendshapes(frame) else None


def _show_templates():
    templates = {}
    for index, name in enumerate(SHOW_EMOTIONS):
        for tier in sorted(CATEGORIES):
            path = EXPRESSIONS_BASE_DIR / tier / f"{name}.yaml"
            if path.is_file() and (frame := _first_blendshape_frame(path)):
                templates.setdefault(index, {})[tier] = frame
    return {"templates": templates, "calm": SHOW_CALM_TEMPLATE}


def _oneline(value):
    return " ".join(str(value).split())


def _expression_yaml(data):
    """生成与现有 24 个表情模板相同的 YAML 结构。"""
    if not isinstance(data, dict):
        raise TypeError("Expression payload must be an object")
    eid = str(data.get("id", ""))
    if not re.fullmatch(r"[\w-]+", eid):
        raise ValueError("Invalid id: only letters, digits, _ and - allowed")
    blendshapes = data.get("blendshapes") or {}
    error = _validate_blendshapes(blendshapes)
    if error:
        raise ValueError(error)
    tags = ", ".join(
        str(tag) for tag in data.get("tags", [])
        if re.fullmatch(r"[\w-]+", str(tag))
    )
    bs_lines = "\n      ".join(
        f"{name}: {float(blendshapes.get(name, 0)):.3f}"
        for name in ARKIT_BLENDSHAPES
    )
    return eid, f"""# 表情文件: {eid}
id: {eid}
type: face_only
description: {_oneline(data.get('description', ''))}
intent: emote
tags: [{tags}]
ready: true
data_format: arkit_blendshapes

commands:
  - at: 0.0
    transition: 0.3
    blendshapes:
      {bs_lines}
  - at: 2.0
    transition: 0.5
    blendshapes:
      {bs_lines}

created_at: {datetime.now().isoformat()}
created_by: expression_debugger_v2
notes: {_oneline(data.get('notes', ''))}
"""


def _expression_overwrite_path(category, filename):
    if not re.fullmatch(r"[\w-]+\.ya?ml", filename):
        raise ValueError("Invalid filename")
    if category == "截取表情":
        return POSES_DIR / filename
    if category not in CATEGORIES:
        raise ValueError("Invalid category. Must be basic, subtle, intense, or 截取表情")
    return EXPRESSIONS_BASE_DIR / category / filename


def _normalize_capture(data):
    if not isinstance(data, dict):
        raise TypeError("Capture payload must be an object")
    title = _oneline(data.get("title", ""))
    description = _oneline(data.get("description", ""))
    if not title or len(title) > 80:
        raise ValueError("Title is required and must be at most 80 characters")
    if len(description) > 500:
        raise ValueError("Description must be at most 500 characters")

    raw_tags = data.get("tags", [])
    if not isinstance(raw_tags, list):
        raise ValueError("Tags must be a list")
    tags = []
    for raw in raw_tags:
        tag = _oneline(raw)
        if tag and len(tag) <= 20 and tag not in tags:
            tags.append(tag)
    if len(tags) > 20:
        raise ValueError("At most 20 tags are allowed")

    raw_frames = data.get("frames")
    if not isinstance(raw_frames, list) or not 1 <= len(raw_frames) <= 100_000:
        raise ValueError("Capture must contain 1-100000 frames")

    frames = []
    previous_time = -1.0
    for index, raw_frame in enumerate(raw_frames):
        try:
            time_s = float(raw_frame["time_s"])
            blendshapes = raw_frame["blendshapes"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid frame {index}") from exc
        if not math.isfinite(time_s) or time_s < 0 or time_s < previous_time:
            raise ValueError(f"Frame time must be finite and nondecreasing: {index}")
        error = _validate_blendshapes(blendshapes)
        if error:
            raise ValueError(f"Invalid frame {index}: {error}")
        raw_servos = raw_frame.get("servos")
        servos = {}
        if raw_servos is not None:
            if not isinstance(raw_servos, dict) or set(raw_servos) != set(NECK_SERVOS):
                raise ValueError(f"Frame {index} must contain all three neck servos")
            for name in NECK_SERVOS:
                value = raw_servos[name]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"Invalid neck servo value: {name}: {value}")
                value = float(value)
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError(f"Invalid neck servo value: {name}: {value}")
                servos[name] = round(value, 6)
        previous_time = time_s
        frames.append({
            "time_s": round(time_s, 6),
            "blendshapes": {
                name: round(float(blendshapes.get(name, 0)), 6)
                for name in ARKIT_BLENDSHAPES
            },
            "servos": servos,
        })

    return {
        "title": title,
        "description": description,
        "tags": tags,
        "duration_s": frames[-1]["time_s"],
        "frame_count": len(frames),
        "has_neck": all(len(frame["servos"]) == len(NECK_SERVOS) for frame in frames),
        "frames": frames,
    }


def _write_capture(data, directory=CAPTURES_DIR, filename=None, audio_filename=None, overwrite=True):
    capture = _normalize_capture(data)
    if not capture["has_neck"]:
        raise ValueError("Every recorded frame must contain all three neck servos")
    directory.mkdir(parents=True, exist_ok=True)
    if filename:
        if Path(filename).name != filename or not filename.lower().endswith(".csv"):
            raise ValueError("Invalid multimodal action filename")
        path = directory / filename
    else:
        stem = re.sub(r"[^\w-]+", "_", capture["title"], flags=re.UNICODE).strip("_")[:50] or "capture"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = directory / f"{stamp}_{stem}.csv"
        suffix = 2
        while path.exists():
            path = directory / f"{stamp}_{stem}_{suffix}.csv"
            suffix += 1

    # 生成标准CSV格式（使用_generate_standard_csv）
    csv_content = _generate_standard_csv(
        name=capture["title"],
        blendshapes={},  # 由frames提供
        head_params=None,
        is_multi_frame=True,
        frames=capture["frames"],
        fps=30
    )

    # 直接使用CSV内容，不添加元数据注释
    final_content = csv_content

    with path.open("w" if overwrite else "x", encoding="utf-8-sig") as stream:
        stream.write(final_content)

    if audio_filename:
        capture["audio_filename"] = audio_filename
    return path, capture


def _wav_duration(path):
    with wave.open(str(path), "rb") as stream:
        rate = stream.getframerate()
        if rate <= 0:
            raise ValueError("WAV sample rate must be positive")
        return stream.getnframes() / rate


def _matching_audio(stem):
    if AUDIOS_DIR.is_dir():
        for path in AUDIOS_DIR.iterdir():
            if path.is_file() and path.stem == stem and path.suffix.lower() == ".wav":
                return path
    return AUDIOS_DIR / f"{stem}.wav"


def _capture_audio(capture, fallback_stem):
    filename = capture.get("audio_filename")
    if not filename:
        return _matching_audio(fallback_stem)
    if Path(filename).name != filename or not filename.lower().endswith(".wav"):
        raise ValueError("Invalid audio filename in multimodal CSV")
    return AUDIOS_DIR / filename


def _write_multiaction(data):
    audio_filename = str(data.get("audio_filename", ""))
    if Path(audio_filename).name != audio_filename or not audio_filename.lower().endswith(".wav"):
        raise ValueError("Please select a valid WAV audio file")
    audio_path = AUDIOS_DIR / audio_filename
    if not audio_path.is_file():
        raise ValueError(f"Audio file not found: {audio_filename}")
    duration = round(_wav_duration(audio_path), 6)
    if duration <= 0:
        raise ValueError("Audio duration must be positive")
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        raise ValueError("Tags must be a list")
    stem = _oneline(data.get("filename", "")) or audio_path.stem
    if stem.lower().endswith(".csv"):
        stem = stem[:-4]
    if not 1 <= len(stem) <= 80 or not re.fullmatch(r"[\w -]+", stem, re.UNICODE):
        raise ValueError("Action filename may only contain letters, numbers, spaces, _ and -")

    capture = _normalize_capture({
        **data,
        "title": stem,
        "description": data.get("description") or f"多模态动作：{audio_filename}",
        "tags": list(dict.fromkeys([*tags, "多模态"])),
    })
    frames = [frame for frame in capture["frames"] if frame["time_s"] <= duration]
    if not frames:
        frames = [{**capture["frames"][0], "time_s": 0.0}]
    elif frames[0]["time_s"] > 0:
        frames.insert(0, {**frames[0], "time_s": 0.0})
    if frames[-1]["time_s"] < duration:
        frames.append({**frames[-1], "time_s": duration})
    else:
        frames[-1] = {**frames[-1], "time_s": duration}

    path, fitted = _write_capture(
        {**capture, "frames": frames},
        MULTIACTIONS_DIR,
        f"{stem}.csv",
        audio_filename=audio_filename,
        overwrite=data.get("overwrite") is True,
    )
    return path, fitted


def _read_capture(path):
    """读取capture CSV文件，支持旧格式和新标准格式"""
    # 读取文件，先提取元数据注释（如果有）
    metadata = {}
    csv_lines = []

    with path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if line.startswith("#"):
                # 解析元数据注释: # key: value
                if ":" in line:
                    key, value = line[1:].split(":", 1)
                    metadata[key.strip()] = value.strip()
            else:
                csv_lines.append(line)

    # 解析CSV内容
    from io import StringIO
    csv_content = "".join(csv_lines)
    stream = StringIO(csv_content)
    reader = csv.DictReader(stream)
    columns = tuple(reader.fieldnames or ())
    rows = list(reader)

    if not rows:
        raise ValueError("CSV contains no frames")

    # 判断格式：标准格式 vs 旧格式
    is_standard_format = columns == tuple(STANDARD_CSV_HEADER)
    is_old_format = columns in (LEGACY_CAPTURE_COLUMNS, CAPTURE_COLUMNS, MULTIACTION_COLUMNS)

    if not (is_standard_format or is_old_format):
        raise ValueError("CSV columns do not match any known capture format")

    # 提取元数据
    if is_standard_format:
        # 新格式：从注释或使用默认值
        title = metadata.get("title", path.stem)
        description = metadata.get("description", "") or f"Captured motion: {path.stem}"
        try:
            tags = json.loads(metadata.get("tags", "[]"))
        except json.JSONDecodeError:
            tags = []
        audio_filename = metadata.get("audio_filename")
    else:
        # 旧格式：从第一行读取
        title = rows[0]["title"]
        description = rows[0]["description"]
        try:
            tags = json.loads(rows[0]["tags"] or "[]")
        except json.JSONDecodeError as exc:
            raise ValueError("CSV tags metadata is invalid") from exc
        audio_filename = rows[0].get("audio_filename")

    # 解析帧数据
    frames = []
    if is_standard_format:
        # 新标准格式：Timecode, BlendshapeCount, 52 PascalCase BS, 9 head/eye params
        for row in rows:
            # Timecode转换为time_s（解析HH:MM:SS:FF.MMM格式）
            # 格式说明：fractional_int = fractional * 100000
            #          FF = fractional_int // 1000 (前2位)
            #          MMM = fractional_int % 1000 (后3位)
            timecode = row["Timecode"]
            if ":" in timecode:
                parts = timecode.split(":")
                if len(parts) == 4:
                    # 标准格式: HH:MM:SS:FF.MMM
                    hours = int(parts[0])
                    minutes = int(parts[1])
                    seconds = int(parts[2])
                    frame_ms_parts = parts[3].split(".")
                    frame_part = int(frame_ms_parts[0])  # FF (前2位)
                    subframe_part = int(frame_ms_parts[1]) if len(frame_ms_parts) > 1 else 0  # MMM (后3位)
                    # 重建小数秒: fractional = (FF * 1000 + MMM) / 100000
                    fractional_s = (frame_part * 1000 + subframe_part) / 100000.0
                    time_s = hours * 3600 + minutes * 60 + seconds + fractional_s
                else:
                    # 旧格式兼容: 尝试其他解析方式
                    hours = int(parts[0]) if len(parts) > 0 else 0
                    minutes = int(parts[1]) if len(parts) > 1 else 0
                    sec_parts = parts[2].split(".") if len(parts) > 2 else ["0"]
                    seconds = int(sec_parts[0])
                    milliseconds = int(sec_parts[1]) if len(sec_parts) > 1 else 0
                    time_s = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
            else:
                time_s = 0.0

            # 转换PascalCase blendshapes回camelCase
            blendshapes = {}
            for std_name in STANDARD_CSV_BLENDSHAPES:
                orig_name = std_name[0].lower() + std_name[1:]
                blendshapes[orig_name] = float(row[std_name])

            # 提取head rotation参数并映射回servos
            # HeadYaw/Pitch/Roll (-90~90度) -> head_yao/dian/bai (0~1舵机值)
            head_yaw = float(row.get("HeadYaw", 0))
            head_pitch = float(row.get("HeadPitch", 0))
            head_roll = float(row.get("HeadRoll", 0))

            servos = {
                "head_yao": (head_yaw / 180.0) + 0.5,
                "head_dian": (head_pitch / 180.0) + 0.5,
                "head_bai": (head_roll / 180.0) + 0.5,
            }

            frames.append({
                "time_s": time_s,
                "blendshapes": blendshapes,
                "servos": servos,
            })
    else:
        # 旧格式：time_s, camelCase blendshapes, head_dian/yao/bai
        has_neck = columns in (CAPTURE_COLUMNS, MULTIACTION_COLUMNS)
        for row in rows:
            frame = {
                "time_s": float(row["time_s"]),
                "blendshapes": {name: float(row[name]) for name in ARKIT_BLENDSHAPES},
            }
            if has_neck:
                frame["servos"] = {name: float(row[name]) for name in NECK_SERVOS}
            frames.append(frame)

    data = {
        "title": title,
        "description": description,
        "tags": tags,
        "frames": frames,
    }
    capture = _normalize_capture(data)

    if audio_filename:
        if Path(audio_filename).name != audio_filename or not audio_filename.lower().endswith(".wav"):
            raise ValueError("CSV audio filename is invalid")
        capture["audio_filename"] = audio_filename

    return capture


def _read_servo_trace(path):
    """读取每行一个 JSON 帧的舵机轨迹。"""
    frames = []
    servo_names = None
    elapsed = 0.0
    metadata = None
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Line {line_number} is not valid JSON") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("servo_command"), dict) or not raw["servo_command"]:
            raise ValueError(f"Frame {line_number} has no servo_command")
        dt = raw.get("dt")
        if isinstance(dt, bool) or not isinstance(dt, (int, float)) or not math.isfinite(dt) or dt < 0:
            raise ValueError(f"Frame {line_number} has invalid dt")
        names = tuple(raw["servo_command"])
        if servo_names is None:
            servo_names = names
            metadata = raw
        elif set(names) != set(servo_names):
            raise ValueError(f"Frame {line_number} servo channels do not match the first frame")
        servos = {}
        for name in servo_names:
            value = raw["servo_command"][name]
            if not re.fullmatch(r"\w+", name) or isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Frame {line_number} has invalid servo: {name}")
            value = float(value)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"Frame {line_number} servo is outside [0,1]: {name}")
            servos[name] = value
        elapsed += float(dt)
        frames.append({"time_s": round(elapsed, 6), "servos": servos})
    if not frames:
        raise ValueError("Servo trace contains no frames")
    return {
        "title": str(metadata.get("label") or path.stem),
        "description": f"舵机轨迹：{path.name}",
        "tags": [str(value) for value in (metadata.get("stage"), metadata.get("trajectory")) if value],
        "duration_s": frames[-1]["time_s"],
        "frame_count": len(frames),
        "has_neck": all(name in servo_names for name in NECK_SERVOS),
        "frames": frames,
    }


class SaveHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def guess_type(self, path):
        content_type = super().guess_type(path)
        if content_type.startswith("text/") or content_type in {
            "application/javascript", "application/json"
        }:
            return f"{content_type}; charset=utf-8"
        return content_type

    def log_request(self, code="-", size="-"):
        if int(code) >= 400:
            super().log_request(code, size)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, code, content_type, body):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(200, {})

    def _overwrite(self):
        """覆盖表情库中已存在的文件: {category, filename, yaml}"""
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))

            category = str(data.get("category", "")).lower()
            filename = str(data.get("filename", ""))
            try:
                target = _expression_overwrite_path(category, filename)
            except ValueError as exc:
                return self._send(400, {"detail": str(exc)})
            if not target.is_file():
                return self._send(404, {"detail": f"File not found: {category}/{filename}"})

            yaml_text = str(data.get("yaml", ""))
            # 覆盖接口同样只接受标准 ARKit BS，拒绝旧舵机键名。
            blocks = re.findall(r"(?m)^[ \t]+blendshapes:\n((?:[ \t]+\w+:[ \t]*-?\d+(?:\.\d+)?[ \t]*\n)+)", yaml_text)
            if not blocks:
                return self._send(400, {"detail": "No valid commands/blendshapes block in yaml"})
            for block in blocks:
                values = {name: float(value) for name, value in re.findall(r"(\w+):\s*(-?\d+(?:\.\d+)?)", block)}
                error = _validate_blendshapes(values)
                if error:
                    return self._send(400, {"detail": error})

            target.write_text(yaml_text, encoding="utf-8")
            rel = (
                str(target.relative_to(EXP_DEB_ROOT))
                if category == "截取表情" else f"{category}/{filename}"
            )
            print(f" Overwrote expression {target}")
            self._send(200, {"success": True, "path": rel, "message": "Expression overwritten"})
        except Exception as e:
            self._send(500, {"detail": str(e)})

    def _save_capture(self):
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            path, capture = _write_capture(data)
            self._send(200, {
                "success": True,
                "filename": path.name,
                "path": str(path.relative_to(EXP_DEB_ROOT)),
                "duration_s": capture["duration_s"],
                "frame_count": capture["frame_count"],
            })
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._send(400, {"detail": str(exc)})

    def _save_multiaction(self):
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            path, capture = _write_multiaction(data)
            self._send(200, {
                "success": True,
                "filename": path.name,
                "path": str(path.relative_to(EXP_DEB_ROOT)),
                "duration_s": capture["duration_s"],
                "frame_count": capture["frame_count"],
            })
        except FileExistsError as exc:
            filename = Path(exc.filename).name if exc.filename else ""
            self._send(409, {"detail": f"Multimodal action already exists: {filename}", "filename": filename})
        except (OSError, TypeError, ValueError, wave.Error, json.JSONDecodeError) as exc:
            self._send(400, {"detail": str(exc)})

    def do_GET(self):
        request = urlsplit(self.path)
        if request.path == "/api/templates":
            return self._send(200, _show_templates())
        if request.path == "/api/llm/status":
            if llm_client is None:
                return self._send(500, {"configured": False, "detail": "llm_client 模块不可用"})
            provider = parse_qs(request.query).get("provider", [None])[0]
            return self._send(200, llm_client.status(provider))
        if request.path == "/api/heads":
            # 机器人头可视化选择的可选项 + 当前选择状态
            state = _load_head_state()
            current = None
            mapping_name = state.get("mapping")
            if mapping_name:
                try:
                    mapping_file = _mapping_file(mapping_name)
                    label, config_path = _head_profile(mapping_file)
                    current = {
                        "robot_head": label,
                        "mapping_file": mapping_file.name,
                        "head_config": config_path.name,
                        "number": state.get("number"),
                    }
                except (OSError, ValueError):
                    current = None
            if not current:
                in_use = _grpc_config_in_use()
                if in_use:
                    current = {
                        "robot_head": in_use,
                        "mapping_file": "",
                        "head_config": in_use,
                        "number": None,
                        "note": "gRPC 正在使用该配置，但本服务无选择记录",
                    }
            return self._send(200, {
                "success": True,
                "heads": _head_choices(),
                "current": current,
                "grpc_running": _port_open(GRPC_PORT),
                "grpc_config": _grpc_config_in_use(),
            })
        if request.path == "/api/mapping":
            # 返回映射表原文 + 绝对路径（路径要转给9001的load_mapping，浏览器自己拿不到）
            try:
                requested = parse_qs(request.query).get("file", [None])[0]
                mapping_file = _mapping_file(requested)
                robot_head, head_config = _head_profile(mapping_file)
                return self._send(200, {
                    "success": True,
                    "robot_head": robot_head,
                    "path": str(mapping_file),
                    "text": mapping_file.read_text(encoding="utf-8"),
                    "head_config": str(head_config),
                    "default_pose": _default_pose(head_config),
                })
            except (OSError, ValueError, ZeroDivisionError) as exc:
                return self._send(400, {"detail": str(exc)})
        if request.path == "/api/servo/state":
            # 手机端轮询舵机状态
            global _servo_state, _servo_state_serial
            return self._send(200, {
                "success": True,
                "servos": _servo_state,
                "serial": _servo_state_serial,
            })
        if request.path == "/api/server/ip":
            return self._send(200, {"success": True, "ip": _get_local_ip()})
        if request.path == "/api/remote/ping":
            return self._send(200, {"success": True, "server": "expression_debugger_v2"})
        if request.path == "/api/remote/commands":
            # 调试器轮询：取走所有积压的遥控指令
            global _remote_commands
            commands = list(_remote_commands)
            _remote_commands.clear()
            return self._send(200, {"success": True, "commands": commands, "serial": _remote_serial})
        if request.path == "/api/latest_blendshapes":
            return self._send(200, {
                "success": True,
                "blendshapes": _latest_blendshapes,
                "source": _latest_blendshapes_source,
                "serial": _latest_blendshapes_serial,
            })
        if request.path == "/api/audios/list":
            try:
                items = []
                if AUDIOS_DIR.is_dir():
                    for path in sorted(AUDIOS_DIR.iterdir()):
                        if path.is_file() and path.suffix.lower() == ".wav":
                            items.append({"filename": path.name, "duration_s": round(_wav_duration(path), 6)})
                return self._send(200, {"success": True, "audios": items})
            except (OSError, ValueError, wave.Error) as exc:
                return self._send(400, {"detail": str(exc)})
        if request.path == "/api/captures/get":
            try:
                query = parse_qs(request.query)
                filename = query.get("file", [""])[0]
                multimodal = query.get("kind", [""])[0] == "multiaction"
                directory = MULTIACTIONS_DIR if multimodal else CAPTURES_DIR
                if Path(filename).name != filename or not filename.lower().endswith(".csv"):
                    raise ValueError("Invalid capture filename")
                path = (directory / filename).resolve()
                if path.parent != directory.resolve() or not path.is_file():
                    raise ValueError(f"Capture file not found: {filename}")
                payload = {"success": True, "kind": "multiaction" if multimodal else "capture", **_read_capture(path)}
                if multimodal:
                    audio = _capture_audio(payload, path.stem)
                    payload.update({"audio_filename": audio.name, "audio_exists": audio.is_file()})
                return self._send(200, payload)
            except (OSError, TypeError, ValueError) as exc:
                return self._send(400, {"detail": str(exc)})
        if request.path != "/api/expressions/list":
            return super().do_GET()  # 非API路径走静态文件服务
        try:
            items = []
            # 动态扫描motion_assets下的所有子目录（排除有特殊处理逻辑的目录）
            excluded = {"audios", "actions", "multiactions", "poses"}
            all_subdirs = [d for d in EXPRESSIONS_BASE_DIR.iterdir()
                          if d.is_dir() and d.name not in excluded]
            for subdir in sorted(all_subdirs, key=lambda x: x.name):
                cat = subdir.name
                # 读取YAML格式表情
                for f in sorted(list(subdir.glob("*.yaml")) + list(subdir.glob("*.yml"))):
                    items.append({
                        "category": cat,
                        "filename": f.name,
                        "format": "yaml",
                        "yaml": f.read_text(encoding="utf-8"),
                    })
                # 读取CSV格式表情
                for f in sorted(subdir.glob("*.csv")):
                    try:
                        csv_text = f.read_text(encoding="utf-8")
                        lines = csv_text.strip().split('\n')
                        if len(lines) < 2:
                            continue
                        # 第一行是header，第二行是数据
                        data_line = lines[1].split(',')
                        expr_id = data_line[0] if data_line else f.stem
                        items.append({
                            "category": cat,
                            "filename": f.name,
                            "format": "csv",
                            "kind": "expression",
                            "id": expr_id,
                            "valid": True,
                            "csv": csv_text,
                        })
                    except (OSError, IndexError, ValueError):
                        continue
            if POSES_DIR.is_dir():
                # 扫描 YAML 格式的截取表情
                for path in sorted(list(POSES_DIR.glob("*.yaml")) + list(POSES_DIR.glob("*.yml"))):
                    items.append({
                        "category": "截取表情",
                        "filename": path.name,
                        "format": "yaml",
                        "yaml": path.read_text(encoding="utf-8"),
                    })
                # 扫描 CSV 格式的截取表情
                for path in sorted(POSES_DIR.glob("*.csv")):
                    try:
                        csv_text = path.read_text(encoding="utf-8")
                        lines = csv_text.strip().split('\n')
                        if len(lines) < 2:
                            continue
                        # 第一行是header，第二行是数据
                        data_line = lines[1].split(',')
                        expr_id = data_line[0] if data_line else path.stem
                        items.append({
                            "category": "截取表情",
                            "filename": path.name,
                            "format": "csv",
                            "kind": "expression",
                            "id": expr_id,
                            "valid": True,
                            "csv": csv_text,
                        })
                    except (OSError, IndexError, ValueError):
                        continue
            for path in sorted(list((EXP_DEB_ROOT / "motion_assets").glob("*.yaml")) + list((EXP_DEB_ROOT / "motion_assets").glob("*.yml"))):
                try:
                    capture = _read_servo_trace(path)
                except (OSError, TypeError, ValueError):
                    continue
                items.append({
                    "category": "舵机动作",
                    "filename": path.name,
                    "format": "yaml",
                    "kind": "servo_capture",
                    "yaml": path.read_text(encoding="utf-8"),
                    **{key: capture[key] for key in ("title", "description", "tags", "duration_s", "frame_count", "has_neck")},
                })
            if CAPTURES_DIR.is_dir():
                for path in sorted(CAPTURES_DIR.glob("*.csv"), reverse=True):
                    try:
                        capture = _read_capture(path)
                        items.append({
                            "category": "录制动作",
                            "filename": path.name,
                            "format": "csv",
                            "valid": True,
                            # 录制动作不添加 csv 字段，让前端通过 selectCapture() 处理
                            **{key: capture[key] for key in ("title", "description", "tags", "duration_s", "frame_count", "has_neck")},
                        })
                    except (OSError, TypeError, ValueError) as exc:
                        items.append({
                            "category": "录制动作",
                            "filename": path.name,
                            "format": "csv",
                            "valid": False,
                            "error": str(exc),
                        })
            if MULTIACTIONS_DIR.is_dir():
                for path in sorted(MULTIACTIONS_DIR.glob("*.csv"), reverse=True):
                    try:
                        capture = _read_capture(path)
                        audio = _capture_audio(capture, path.stem)
                        items.append({
                            "category": "多模态动作",
                            "filename": path.name,
                            "format": "csv",
                            "kind": "multiaction",
                            "valid": True,
                            # 多模态动作不添加 csv 字段，让前端通过 selectCapture() 处理
                            "audio_filename": audio.name,
                            "audio_exists": audio.is_file(),
                            **{key: capture[key] for key in ("title", "description", "tags", "duration_s", "frame_count", "has_neck")},
                        })
                    except (OSError, TypeError, ValueError) as exc:
                        items.append({
                            "category": "多模态动作",
                            "filename": path.name,
                            "format": "csv",
                            "kind": "multiaction",
                            "valid": False,
                            "error": str(exc),
                        })
            self._send(200, {"success": True, "expressions": items})
        except Exception as e:
            self._send(500, {"detail": str(e)})

    def do_POST(self):
        global _latest_blendshapes, _latest_blendshapes_source, _latest_blendshapes_serial, _remote_commands, _remote_serial, _servo_state, _servo_state_serial
        if urlsplit(self.path).path == "/api/llm/tts":
            # 文字转语音：{text, provider} → 音频字节
            if llm_client is None:
                return self._send(500, {"detail": "llm_client 模块不可用"})
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                text = str(data.get("text") or "").strip()
                if not text:
                    return self._send(400, {"detail": "Missing text"})
                if len(text) > 200:
                    return self._send(400, {"detail": "text too long"})
                content_type, audio = llm_client.tts(text, data.get("provider"))
                return self._send_bytes(200, content_type or "audio/wav", audio)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                return self._send(400, {"detail": str(exc)})
            except Exception as exc:
                return self._send(502, {"detail": str(exc)})
        if self.path == "/api/llm/chat":
            # AI 情绪对话：message → (reply, emotions)
            if llm_client is None:
                return self._send(500, {"detail": "llm_client 模块不可用"})
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                message = str(data.get("message") or "").strip()
                if not message:
                    return self._send(400, {"detail": "Missing message"})
                if len(message) > 2000:
                    return self._send(400, {"detail": "message too long"})
                history = data.get("history")
                mode = str(data.get("mode") or "auto")
                history = history if isinstance(history, list) else None
                provider = data.get("provider")
                if mode == "direct":
                    result = llm_client.chat_direct(message, history, provider)
                elif mode == "ask":
                    result = llm_client.chat_ask(message, history, provider)
                else:
                    result = llm_client.chat_cached(message, history, provider)
                return self._send(200, result)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                return self._send(400, {"detail": str(exc)})
            except Exception as exc:
                return self._send(502, {"detail": str(exc)})
        if urlsplit(self.path).path == "/api/llm/transcribe":
            # 语音转文字：请求体为原始音频字节（Content-Type: audio/wav）
            if llm_client is None:
                return self._send(500, {"detail": "llm_client 模块不可用"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 1 <= length <= 25 * 1024 * 1024:
                    return self._send(400, {"detail": "Invalid audio size"})
                audio = self.rfile.read(length)
                content_type = self.headers.get("Content-Type", "audio/wav")
                provider = parse_qs(urlsplit(self.path).query).get("provider", [None])[0]
                text = llm_client.transcribe(audio, content_type=content_type, provider=provider)
                return self._send(200, {"success": True, "text": text})
            except (ValueError, TypeError) as exc:
                return self._send(400, {"detail": str(exc)})
            except Exception as exc:
                return self._send(502, {"detail": str(exc)})
        if self.path == "/api/select_head":
            # 网页可视化选择机器人头：校验配置 → 切换/启动 gRPC → 持久化选择
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                head = str(data.get("head") or "").lower()
                if head not in HEAD_CONFIGS:
                    return self._send(400, {"detail": f"不支持的机器人头: {head}"})
                mapping_name = _mapping_name_for_selection(head, data.get("number"))
                mapping_file = _mapping_file(mapping_name)
                label, config_path = _head_profile(mapping_file)

                in_use = _grpc_config_in_use()
                if _port_open(GRPC_PORT) and in_use and in_use != config_path.name:
                    ok, msg = _stop_grpc()
                    if not ok:
                        return self._send(500, {"detail": f"停止旧 gRPC 服务失败: {msg}"})
                if not _port_open(GRPC_PORT):
                    started, grpc_msg = _start_grpc(config_path)
                else:
                    started, grpc_msg = True, "already running"

                _save_head_state({
                    "head": label,
                    "number": int(data.get("number")) if head in ("g01", "g02") else None,
                    "mapping": mapping_file.name,
                    "head_config": config_path.name,
                    "selected_at": datetime.now().isoformat(),
                })
                return self._send(200, {
                    "success": True,
                    "robot_head": label,
                    "mapping_file": mapping_file.name,
                    "head_config": config_path.name,
                    "path": str(mapping_file),
                    "text": mapping_file.read_text(encoding="utf-8"),
                    "default_pose": _default_pose(config_path),
                    "grpc_started": started,
                    "grpc_status": grpc_msg,
                })
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                return self._send(400, {"detail": str(exc)})
        if self.path == "/api/servo/state":
            # 桌面端推舵机状态 → 手机端轮询
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                servos = data.get("servos", {})
                if isinstance(servos, dict):
                    _servo_state_serial += 1
                    _servo_state = servos
                return self._send(200, {"success": True, "serial": _servo_state_serial})
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                return self._send(400, {"detail": str(exc)})
        if self.path == "/api/remote/click":
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                button_id = str(data.get("buttonId", ""))
                timestamp = data.get("timestamp", 0)
                if not button_id:
                    return self._send(400, {"detail": "Missing buttonId"})
                _remote_serial += 1
                _remote_commands.append({"buttonId": button_id, "timestamp": timestamp, "serial": _remote_serial})
                print(f"📱 遥控指令: {button_id} (#{_remote_serial})")
                return self._send(200, {"success": True, "serial": _remote_serial})
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                return self._send(400, {"detail": str(exc)})
        if self.path == "/api/expressions/overwrite":
            return self._overwrite()
        if self.path == "/api/captures/save":
            return self._save_capture()
        if self.path == "/api/multiactions/save":
            return self._save_multiaction()
        if self.path == "/api/submit_blendshapes":
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                bs = data.get("blendshapes", {})
                if not isinstance(bs, dict):
                    return self._send(400, {"detail": "blendshapes must be an object"})
                validated = {}
                for name, value in bs.items():
                    if name not in ARKIT_BLENDSHAPE_SET:
                        return self._send(400, {"detail": f"Invalid blendshape name: {name}"})
                    v = float(value)
                    if not math.isfinite(v) or not 0 <= v <= 1:
                        return self._send(400, {"detail": f"Invalid blendshape value: {name}: {value}"})
                    validated[name] = round(v, 6)
                _latest_blendshapes = validated
                _latest_blendshapes_source = str(data.get("source", "show"))
                _latest_blendshapes_serial += 1
                self._send(200, {"success": True, "serial": _latest_blendshapes_serial})
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                return self._send(400, {"detail": str(exc)})
        is_pose = self.path == "/api/poses/save"
        if self.path != "/api/expressions/save" and not is_pose:
            return self._send(404, {"detail": "not found"})
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))

            # 验证表情ID
            eid = str(data.get("id", ""))
            if not re.fullmatch(r"[\w-]+", eid):
                return self._send(400, {"detail": "Invalid id: only letters, digits, _ and - allowed"})

            # 验证blendshapes
            blendshapes = data.get("blendshapes") or {}
            error = _validate_blendshapes(blendshapes)
            if error:
                return self._send(400, {"detail": error})

            # 确定保存目录和格式
            if is_pose:
                target_dir = POSES_DIR
                category = "poses"
            else:
                category = str(data.get("category", "basic")).lower()
                if category not in CATEGORIES:
                    return self._send(400, {"detail": f"Invalid category. Must be one of: {', '.join(sorted(CATEGORIES))}"})
                # 保存到motion_assets目录以与列表API对齐
                target_dir = EXPRESSIONS_BASE_DIR / category

            # 获取头部参数和多帧数据
            head_params = data.get("head_params", {})
            frames = data.get("frames")
            is_multi_frame = bool(frames) and category == "clips"

            # 生成标准CSV格式
            csv_text = _generate_standard_csv(
                name=eid,
                blendshapes=blendshapes,
                head_params=head_params,
                is_multi_frame=is_multi_frame,
                frames=frames
            )

            target_dir.mkdir(parents=True, exist_ok=True)
            file_path = target_dir / f"{eid}.csv"
            if is_pose and file_path.exists():
                return self._send(409, {"detail": f"Expression already exists: {eid}.csv"})
            file_path.write_text(csv_text, encoding="utf-8")

            rel = f"motion_assets/{category}/{eid}.csv"
            print(f" Saved expression to {file_path}")
            self._send(200, {"success": True, "path": rel, "message": "Expression saved successfully"})
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._send(400, {"detail": str(exc)})
        except Exception as e:
            self._send(500, {"detail": str(e)})


if __name__ == "__main__":
    print(f"表情保存服务启动: http://localhost:{PORT}")
    print(f"表情库目录: {EXPRESSIONS_BASE_DIR}")
    print(f"面捕动作目录: {CAPTURES_DIR}")
    print(f"多模态动作目录: {MULTIACTIONS_DIR}")
    print(f"截取表情目录: {POSES_DIR}")
    print(f"调试器页面: http://localhost:{PORT}/expression_debugger/expression_debugger_v2.html")
    ThreadingHTTPServer(("0.0.0.0", PORT), SaveHandler).serve_forever()
