#!/usr/bin/env python3
"""Push K230 (lckfb 庐山派 CanMV) firmware to /sdcard/ and reset.

K230 quirk: 设备上 /sdcard/main.py 一上电就跑死循环, 占着唯一的 USB-CDC
串口, mpremote 的 raw-paste 进入序列经常被卡。本脚本步骤:
  1. 裸 pyserial 砸 10×Ctrl-C burst 打停 main.py
  2. `mpremote ... resume fs cp` 把本地 *.py 推到 :/sdcard/
  3. `mpremote ... resume reset` 重启 (失败时 fallback 走 Ctrl-D soft reset)

Usage:
  python push_k230.py                       # push all *.py from cwd
  python push_k230.py main.py mod.py        # push 指定几个 (bare name 或 path)
  python push_k230.py --src-dir firmware/   # 从子目录找 *.py

  --port /dev/cu.usbmodem...                # 默认 /dev/cu.usbmodem0010000001
  --mpremote /usr/local/bin/mpremote        # 默认 ~/Library/Python/3.9/bin/mpremote
  --no-reset                                # 推完不 reset (连续推多次)
  --dry-run                                 # 只打印命令, 不真推

Env vars: PORT, MPREMOTE, K230_SRC_DIR (跟 flag 等价)

Requires: mpremote (pip3 install --user mpremote), pyserial (pip3 install pyserial)
"""
import argparse
import glob
import os
import subprocess
import sys
import time


# 默认源目录 = 当前工作目录; 也可以 --src-dir 指定 (典型: 你的 K230 firmware
# 项目布局把 *.py 放在某个子目录, 比如 firmware/ 或 k230/)。
DEFAULT_SRC_DIR = os.environ.get("K230_SRC_DIR", os.getcwd())

DEFAULT_PORT = os.environ.get("PORT", "/dev/cu.usbmodem0010000001")
DEFAULT_MPREMOTE = os.environ.get(
    "MPREMOTE", os.path.expanduser("~/Library/Python/3.9/bin/mpremote"))


def log(msg):
    print(f"\033[1;36m[push-k230]\033[0m {msg}")


def resolve_mpremote():
    if os.access(DEFAULT_MPREMOTE, os.X_OK):
        return DEFAULT_MPREMOTE
    # fallback: 系统 PATH
    found = subprocess.run(["which", "mpremote"], capture_output=True, text=True)
    if found.returncode == 0 and found.stdout.strip():
        return found.stdout.strip()
    raise SystemExit(
        "mpremote not found. Install: pip3 install --user mpremote\n"
        f"  or set MPREMOTE=/path/to/mpremote (tried {DEFAULT_MPREMOTE})")


def collect_files(args_files, src_dir):
    """Either explicit list (bare names or paths) or auto-discover all *.py in src_dir."""
    if args_files:
        files = []
        for f in args_files:
            # accept bare name (main.py) or path (firmware/main.py)
            if os.path.isfile(f):
                src = f
            else:
                src = os.path.join(src_dir, os.path.basename(f))
            if not os.path.isfile(src):
                raise SystemExit(f"{f} not found (checked direct + {src_dir}/)")
            files.append(src)
        return files
    found = sorted(glob.glob(os.path.join(src_dir, "*.py")))
    if not found:
        raise SystemExit(f"no *.py files in {src_dir}; use --src-dir or pass filenames explicitly")
    return found


def break_main_loop(mpremote, port):
    """Interrupt running main.py so subsequent `mpremote resume cp ...` can land.

    K230 主循环嵌得深 + 有 try/except 兜底, mpremote 自己的 raw-paste 进入序列
    经常被卡 (exec 命令 10s 都拿不到 prompt)。改用裸 pyserial 砸 Ctrl-C burst
    把 main loop 打停, 后续用 `mpremote ... resume cp` 直接 attach (不重新
    soft-reset), 跳过验证。如果 device 真的没停, 后面 fs cp 自然会超时报错。"""
    log("    sending raw 10×Ctrl-C burst via pyserial")
    try:
        import serial
        with serial.Serial(port, 115200, timeout=0.3) as p:
            for _ in range(10):
                p.write(b"\x03")
                p.flush()
                time.sleep(0.15)
            # 多读一下把 buffer 清掉, 防止后续 mpremote 看到 stale bytes
            p.read(4096)
    except Exception as e:
        raise SystemExit(
            f"pyserial Ctrl-C burst failed: {e}\n"
            "Install: pip3 install --user pyserial\n"
            "Or yank USB + replug to force boot into REPL.")


def push_file(mpremote, port, src, dry_run):
    name = os.path.basename(src)
    remote = f":/sdcard/{name}"
    size = os.path.getsize(src)
    log(f"    {src} ({size}B) → {remote}")
    if dry_run:
        return
    # `resume` 让 mpremote 复用现有 REPL session, 不再 soft-reset / 不重新
    # 走 raw-paste 进入序列 — 跟 SKILL.md manual fallback 同。
    subprocess.run(
        [mpremote, "connect", port, "resume", "fs", "cp", src, remote],
        check=True,
    )


def reset_device(mpremote, port, dry_run):
    log("3/3 reset")
    if dry_run:
        return
    # 跟 push_file 一样要 resume; mpremote 这版 reset 也要先 acquire REPL,
    # 否则跑 enter_raw_repl 又会被 main.py 抢着不让进。
    try:
        subprocess.run(
            [mpremote, "connect", port, "resume", "reset"],
            check=True, timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # fallback: 裸 serial 发 Ctrl-D (soft reset)
        log("    mpremote reset failed, fallback: raw Ctrl-D via pyserial")
        try:
            import serial
            with serial.Serial(port, 115200, timeout=0.3) as p:
                p.write(b"\x04")
                p.flush()
        except Exception as e:
            log(f"    raw reset also failed: {e} (device may already be booting from auto-run after fs cp)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*",
                    help="filenames (bare or path; defaults: all *.py in src-dir)")
    ap.add_argument("--port", default=DEFAULT_PORT,
                    help=f"USB-CDC port (default: {DEFAULT_PORT})")
    ap.add_argument("--mpremote", default=None,
                    help="path to mpremote (default: $MPREMOTE or "
                         "~/Library/Python/3.9/bin/mpremote, then $PATH)")
    ap.add_argument("--src-dir", default=DEFAULT_SRC_DIR,
                    help=f"source dir for *.py auto-discover (default: {DEFAULT_SRC_DIR})")
    ap.add_argument("--no-reset", action="store_true",
                    help="skip reset (useful for chained pushes during debug)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print steps without actually pushing")
    args = ap.parse_args()

    mpremote = args.mpremote or resolve_mpremote()
    if not os.path.exists(args.port):
        raise SystemExit(
            f"port {args.port} not present; is the K230 plugged in?\n"
            "  Try: ls /dev/cu.usbmodem*  (macOS)  or  ls /dev/ttyACM*  (Linux)")

    files = collect_files(args.files, args.src_dir)

    log(f"using mpremote: {mpremote}")
    log(f"port: {args.port}")
    log(f"files: {' '.join(os.path.basename(f) for f in files)}")
    if args.dry_run:
        log("(dry-run: no actual push)")

    log("1/3 interrupt running main.py")
    if not args.dry_run:
        break_main_loop(mpremote, args.port)

    log(f"2/3 push {len(files)} file(s)")
    for src in files:
        push_file(mpremote, args.port, src, args.dry_run)

    if args.no_reset:
        log("--no-reset: skipped reset; run `mpremote reset` manually when ready")
    else:
        reset_device(mpremote, args.port, args.dry_run)

    log("done.")


if __name__ == "__main__":
    main()
