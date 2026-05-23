#!/usr/bin/env python3
"""Pull a camera-frame snapshot from K230 and decode locally.

Workflow:
  1. Patch /sdcard/main.py (--install) to write a stride-subsampled raw RGB
     buffer (~700KB) to /sdcard/snap.rgb every 3 seconds.
  2. On --pull (default): break main loop, copy /sdcard/snap.rgb back, delete
     it on the device, decode CHW → HWC and save JPEG locally. No long-lived
     SD-card artifact.
  3. --uninstall removes the patch and main.py is back to baseline.

Why SD at all? The K230 main loop deinits on Ctrl-C, so once we can talk to
mpremote, the in-RAM `fr` instance is already gone. Using /sdcard as a 700KB
ring buffer that gets deleted immediately after each pull is the simplest
working compromise.

Usage:
  python3 scripts/k230/screenshot.py --install        # one-time setup
  python3 scripts/k230/screenshot.py                  # pull a snap → snaps/snap-<ts>.jpg
  python3 scripts/k230/screenshot.py --out X.jpg      # pull to explicit path
  python3 scripts/k230/screenshot.py --open           # also open in default viewer (macOS)
  python3 scripts/k230/screenshot.py --uninstall      # remove the patch
"""
import argparse
import datetime as dt
import os
import subprocess
import sys
import time

import serial


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(SCRIPT_DIR, "snaps")
DEFAULT_PORT = "/dev/cu.usbmodem0010000001"
DEFAULT_MPREMOTE = os.path.expanduser("~/Library/Python/3.9/bin/mpremote")
REMOTE_SNAP = "/sdcard/snap.rgb"
REMOTE_MAIN = "/sdcard/main.py"

ANCHOR = "img=pl.get_frame()                      # 获取当前帧"

# Injected verbatim after ANCHOR in /sdcard/main.py.
# Indent MUST match ANCHOR's 20-space indent (it sits inside the outer
# try-except for pl.get_frame).
SNAP_BLOCK = '''
                    # === K230_SNAP_BEGIN (debug screenshot helper) ===
                    try:
                        _now_snap = time.time()
                        if not hasattr(fr, '_last_snap') or _now_snap - fr._last_snap > 3.0:
                            fr._last_snap = _now_snap
                            # img shape is (C=3, H=1080, W=1920) CHW from AI channel.
                            # Stride-subsample CHW → (3, 360, 640) ≈ 691 KB.
                            # int() coerces ulab shape scalar; .flatten() ensures
                            # contiguous buffer for bytes().
                            _small = img[:, ::3, ::3]
                            _ch = int(_small.shape[0])
                            _hh = int(_small.shape[1])
                            _ww = int(_small.shape[2])
                            with open('/sdcard/snap.rgb', 'wb') as _sf:
                                _sf.write(_ch.to_bytes(4, 'little'))
                                _sf.write(_hh.to_bytes(4, 'little'))
                                _sf.write(_ww.to_bytes(4, 'little'))
                                _sf.write(bytes(_small.flatten()))
                            if not hasattr(fr, '_snap_ok_printed'):
                                fr._snap_ok_printed = True
                                print('🖼  snap.rgb:', _ch, _hh, _ww)
                    except Exception as _e:
                        if not hasattr(fr, '_snap_err_printed'):
                            fr._snap_err_printed = True
                            print('🖼  snap err:', _e)
                    # === K230_SNAP_END ===
'''.strip("\n")


def run(cmd, check=True):
    print("$", " ".join(cmd))
    return subprocess.run(cmd, check=check)


def break_main_loop(port):
    """Send Ctrl-C burst to stop running main.py so mpremote can take REPL."""
    p = serial.Serial(port, 115200, timeout=0.3)
    p.read(p.in_waiting or 1)
    for _ in range(10):
        p.write(b"\x03")
        time.sleep(0.15)
    time.sleep(0.8)
    p.read(p.in_waiting or 1)
    p.close()


def soft_reset(port):
    """Send Ctrl-D so main.py re-launches."""
    p = serial.Serial(port, 115200, timeout=0.3)
    p.read(p.in_waiting or 1)
    p.write(b"\x04")
    time.sleep(0.3)
    p.close()


def install(mpremote, port):
    import tempfile
    break_main_loop(port)
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
        tmp_path = tmp.name
    run([mpremote, "connect", port, "resume", "cp", f":{REMOTE_MAIN}", tmp_path])
    with open(tmp_path) as f:
        src = f.read()
    if "K230_SNAP_BEGIN" in src:
        print("(snap block already installed)")
        return
    if ANCHOR not in src:
        sys.exit(f"could not find anchor in main.py:\n  {ANCHOR!r}")
    patched = src.replace(ANCHOR, ANCHOR + "\n" + SNAP_BLOCK, 1)
    with open(tmp_path, "w") as f:
        f.write(patched)
    run([mpremote, "connect", port, "resume", "cp", tmp_path, f":{REMOTE_MAIN}"])
    print("snap block installed. Soft-reset K230 to pick it up.")


def uninstall(mpremote, port):
    import re
    import tempfile
    break_main_loop(port)
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
        tmp_path = tmp.name
    run([mpremote, "connect", port, "resume", "cp", f":{REMOTE_MAIN}", tmp_path])
    with open(tmp_path) as f:
        src = f.read()
    if "K230_SNAP_BEGIN" not in src:
        print("(no snap block to remove)")
        return
    stripped = re.sub(
        r"\n[ \t]*# === K230_SNAP_BEGIN.*?# === K230_SNAP_END ===",
        "",
        src,
        flags=re.DOTALL,
    )
    with open(tmp_path, "w") as f:
        f.write(stripped)
    run([mpremote, "connect", port, "resume", "cp", tmp_path, f":{REMOTE_MAIN}"])
    print("snap block removed. Soft-reset K230 to pick it up.")


def pull(mpremote, port, out_path):
    """Break loop, pull /sdcard/snap.rgb, delete it on device, decode locally."""
    import tempfile
    break_main_loop(port)

    with tempfile.NamedTemporaryFile(suffix=".rgb", delete=False) as tmp:
        rgb_path = tmp.name
    try:
        run([mpremote, "connect", port, "resume", "cp", f":{REMOTE_SNAP}", rgb_path])
        run([mpremote, "connect", port, "resume", "exec",
             f"import os; os.remove('{REMOTE_SNAP}')"], check=False)
    finally:
        # Resume the K230 main loop regardless of pull success
        print("(soft-reset to resume main.py)")
        soft_reset(port)

    with open(rgb_path, "rb") as f:
        hdr = f.read(12)
        if len(hdr) != 12:
            sys.exit(f"snap.rgb header truncated ({len(hdr)} bytes)")
        d0 = int.from_bytes(hdr[0:4], "little")
        d1 = int.from_bytes(hdr[4:8], "little")
        d2 = int.from_bytes(hdr[8:12], "little")
        body = f.read()
    os.unlink(rgb_path)

    if len(body) != d0 * d1 * d2:
        sys.exit(f"snap.rgb body size {len(body)} != {d0}*{d1}*{d2}={d0*d1*d2}")

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        sys.exit("install Pillow + numpy: pip3 install --user Pillow numpy")

    # K230 AI channel is CHW. Detect by C∈{1,3,4} and small dim first.
    if d0 in (1, 3, 4) and d2 > d0:
        arr = np.frombuffer(body, dtype=np.uint8).reshape((d0, d1, d2)).transpose(1, 2, 0)
        h, w, c = d1, d2, d0
    else:
        arr = np.frombuffer(body, dtype=np.uint8).reshape((d0, d1, d2))
        h, w, c = d0, d1, d2

    Image.fromarray(arr).save(out_path, quality=85)
    print(f"decoded {h}x{w}x{c} → {out_path} ({os.path.getsize(out_path)} bytes JPEG)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=DEFAULT_PORT)
    ap.add_argument("--mpremote", default=DEFAULT_MPREMOTE)
    ap.add_argument("--out", default=None, help="local output path")
    ap.add_argument("--install", action="store_true",
                    help="patch main.py to dump /sdcard/snap.rgb every ~3s")
    ap.add_argument("--uninstall", action="store_true",
                    help="remove the snap block from main.py")
    ap.add_argument("--open", action="store_true",
                    help="open the snap in default viewer (macOS only)")
    args = ap.parse_args()

    if args.install:
        install(args.mpremote, args.port)
        return
    if args.uninstall:
        uninstall(args.mpremote, args.port)
        return

    os.makedirs(SNAP_DIR, exist_ok=True)
    if args.out is None:
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        args.out = os.path.join(SNAP_DIR, f"snap-{ts}.jpg")
    pull(args.mpremote, args.port, args.out)

    if args.open and sys.platform == "darwin":
        subprocess.run(["open", args.out])


if __name__ == "__main__":
    main()
