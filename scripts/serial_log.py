#!/usr/bin/env python3
"""Capture K230 (lckfb 庐山派 CanMV) USB-CDC serial output to a file.

K230 boots running /sdcard/main.py in an infinite loop, sharing the only
USB-CDC port with the REPL. This script grabs whatever the firmware prints
to stdout/stderr and tee's it to a timestamped log file, with optional
soft-reset / Ctrl-C burst before capture begins.

Usage:
  python3 serial_log.py                         # 30s, default port, auto-named log
  python3 serial_log.py --duration 60           # 60s
  python3 serial_log.py --reset                 # soft-reset K230 first (Ctrl-D)
  python3 serial_log.py --break-first           # send Ctrl-C burst to stop main.py
  python3 serial_log.py --port /dev/cu.usbmodem...
  python3 serial_log.py --dedup-pattern "NO_FACE"   # collapse repeated noisy lines
  python3 serial_log.py --log-dir ~/k230-logs   # default: ./logs

Requires: pyserial (pip3 install pyserial)
"""
import argparse
import datetime as dt
import os
import sys
import time

import serial


DEFAULT_PORT = os.environ.get("PORT", "/dev/cu.usbmodem0010000001")
DEFAULT_LOG_DIR = os.environ.get("K230_LOG_DIR", "./logs")


def capture(port, duration, reset, break_first, dedup_pattern, out_path):
    print(f"capturing {duration}s from {port} → {out_path}")
    p = serial.Serial(port, 115200, timeout=0.1)
    try:
        if break_first:
            print("(sending Ctrl-C burst to interrupt running main.py)")
            for _ in range(10):
                p.write(b"\x03")
                p.flush()
                time.sleep(0.15)
            p.read(4096)  # drain
        if reset:
            print("(sending Ctrl-D for soft-reset, expect full boot trace)")
            p.write(b"\x04")
            p.flush()

        deadline = time.time() + duration
        buf = b""
        while time.time() < deadline:
            chunk = p.read(4096)
            if chunk:
                buf += chunk
    finally:
        p.close()

    text = buf.decode("utf-8", errors="replace")
    if dedup_pattern:
        text = dedup_noise(text, dedup_pattern)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        f.write(text)
    print(f"wrote {len(text)} bytes to {out_path}")
    return out_path


def dedup_noise(text, pattern):
    """Collapse long runs of lines matching `pattern` substring to a single marker."""
    lines = text.split("\n")
    out = []
    streak = 0
    for ln in lines:
        if pattern in ln:
            streak += 1
            if streak <= 2:
                out.append(ln)
            elif streak == 3:
                out.append(f"... ({pattern} × N) ...")
            # otherwise drop
        else:
            streak = 0
            out.append(ln)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default=DEFAULT_PORT,
                    help=f"USB-CDC port (default: {DEFAULT_PORT})")
    ap.add_argument("--duration", type=int, default=30,
                    help="seconds to capture (default: 30)")
    ap.add_argument("--reset", action="store_true",
                    help="soft-reset K230 (Ctrl-D) before capture, to see full boot trace")
    ap.add_argument("--break-first", action="store_true",
                    help="send Ctrl-C burst before capture (stops running main.py)")
    ap.add_argument("--dedup-pattern", default="",
                    help="collapse repeated lines containing this substring "
                         "(e.g. 'NO_FACE' for face-recognition firmware)")
    ap.add_argument("--log-dir", default=DEFAULT_LOG_DIR,
                    help=f"directory for log files (default: {DEFAULT_LOG_DIR})")
    args = ap.parse_args()

    if not os.path.exists(args.port):
        raise SystemExit(
            f"port {args.port} not present; is the K230 plugged in?\n"
            "  macOS: ls /dev/cu.usbmodem*   Linux: ls /dev/ttyACM*")

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(args.log_dir, f"k230-{stamp}.log")
    capture(args.port, args.duration, args.reset, args.break_first,
            args.dedup_pattern, out_path)


if __name__ == "__main__":
    main()
