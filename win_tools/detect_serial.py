#!/usr/bin/env python3
"""Windows 串口检测 + 舵机配置 COM 转换工具（windows 包专用）。

行为：
  1. 用 pyserial 列出本机串口；
  2. 自动识别“机器人头”和“J7034G4 麦克风阵列”的 COM 口
     （可用 --head-port / --mic-port 手动覆盖）；
  3. 把 exp_deb 里 servoConfig_25DV3_*.yaml 的 /dev/ttyACM* 端口替换为 COMx，
     写入 windows/runtime/configs/（不修改原始文件）；
  4. 把结果写到 windows/runtime/serial.json，供启动脚本读取。

用法：
  python win_tools/detect_serial.py --list
  python win_tools/detect_serial.py
  python win_tools/detect_serial.py --head-port COM5 --mic-port COM6
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]          # windows/
RUNTIME_DIR = PACKAGE_ROOT / "runtime"
CONFIG_OUT_DIR = RUNTIME_DIR / "configs"
EXP_DEB_ROOT = PACKAGE_ROOT.parent / "exp_deb"
HEAD_CONFIG_DIR = EXP_DEB_ROOT / "servo_tuning" / "head-sdk-face" / "head-server" / "src"

MIC_VIDS = {0x1A86}  # CH340/CH341（J7034G4 麦克风阵列常用）


def iter_ports():
    from serial.tools import list_ports
    return list(list_ports.comports())


def port_text(port) -> str:
    return " ".join(str(v or "") for v in (
        port.device, port.description, port.manufacturer, port.product,
        getattr(port, "hwid", None),
    )).lower()


def score_mic(port) -> int:
    text = port_text(port)
    score = 0
    if "j7034" in text:
        score += 100
    if any(k in text for k in ("ch340", "ch341", "usb-serial", "usb serial")):
        score += 80
    if getattr(port, "vid", None) in MIC_VIDS:
        score += 80
    if str(port.device).upper().startswith("COM"):
        score += 20
    return score


def is_usb_serial(port) -> bool:
    text = port_text(port)
    return (
        getattr(port, "vid", None) is not None
        or any(k in text for k in ("usb", "serial", "ch340", "ch341", "ftdi", "cp210", "cdc", "acm"))
    )


def classify(ports):
    """返回 (head_port, mic_port)。机器人头默认选第一个非麦克风的 USB 串口。"""
    mic_candidates = [p for p in ports if score_mic(p) > 0]
    mic_candidates.sort(key=score_mic, reverse=True)
    mic = mic_candidates[0] if mic_candidates else None
    rest = [p for p in ports if p is not mic]
    usb_rest = [p for p in rest if is_usb_serial(p)]
    head = (usb_rest or rest)[0] if rest else None
    return (head.device if head else None, mic.device if mic else None)


def convert_configs(head_port: str) -> int:
    """把 servoConfig_25DV3_*.yaml 的串口替换为 COMx，写入 runtime/configs。"""
    CONFIG_OUT_DIR.mkdir(parents=True, exist_ok=True)
    converted = 0
    for yaml_path in sorted(HEAD_CONFIG_DIR.glob("servoConfig_25DV3_*.yaml")):
        text = yaml_path.read_text(encoding="utf-8")
        if not re.search(r"(?m)^\s*(?:-\s*)?port:\s*", text):
            continue
        new_text = re.sub(
            r"(?m)^(\s*(?:-\s*)?port:\s*).*$",
            lambda m: m.group(1) + head_port,
            text,
        )
        (CONFIG_OUT_DIR / yaml_path.name).write_text(new_text, encoding="utf-8")
        converted += 1
    return converted


def write_serial_info(head_port: str, mic_port: str, ports) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    info = {
        "head_port": head_port,
        "mic_port": mic_port,
        "detected_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "ports": [
            {
                "device": p.device,
                "description": p.description,
                "manufacturer": p.manufacturer,
                "product": p.product,
                "vid": getattr(p, "vid", None),
                "pid": getattr(p, "pid", None),
            }
            for p in ports
        ],
    }
    (RUNTIME_DIR / "serial.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def normalize_port(value: str) -> str:
    return value.strip().upper().replace("\\\\.\\", "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Windows 串口检测与舵机配置 COM 转换")
    parser.add_argument("--list", action="store_true", help="只列出串口，不做转换")
    parser.add_argument("--head-port", help="指定机器人头 COM 口（如 COM5）")
    parser.add_argument("--mic-port", help="指定麦克风阵列 COM 口（如 COM6）")
    parser.add_argument("--skip-write", action="store_true", help="只检测不写配置文件")
    args = parser.parse_args()

    try:
        ports = iter_ports()
    except Exception as exc:
        print(f"无法枚举串口（请确认已安装 pyserial 并连接设备）: {exc}", file=sys.stderr)
        return 2

    if args.list:
        if not ports:
            print("未检测到任何串口")
            return 0
        for p in ports:
            print(f"{p.device}\t{p.description or ''}\t{p.manufacturer or ''} {p.product or ''}\t"
                  f"vid={getattr(p, 'vid', None)} pid={getattr(p, 'pid', None)}")
        return 0

    head_port = args.head_port
    mic_port = args.mic_port
    if not head_port:
        auto_head, auto_mic = classify(ports)
        head_port = auto_head
        mic_port = mic_port or auto_mic
    if not head_port:
        print("未检测到可用的机器人头串口。", file=sys.stderr)
        print("请确认 USB 转串口已连接并安装驱动，或用 --head-port COMx 手动指定。", file=sys.stderr)
        return 1

    head_port = normalize_port(head_port)
    mic_port = normalize_port(mic_port) if mic_port else ""
    print(f"机器人头串口: {head_port}")
    print(f"麦克风阵列串口: {mic_port or '未指定（音源追踪将自动查找）'}")

    if not args.skip_write:
        converted = convert_configs(head_port)
        write_serial_info(head_port, mic_port, ports)
        print(f"已生成 {converted} 个运行时舵机配置 -> {CONFIG_OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
