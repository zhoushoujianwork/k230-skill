---
name: k230
description: K230 (lckfb 庐山派 CanMV) toolkit — deploy MicroPython firmware to /sdcard/, capture USB-CDC serial logs, take camera-frame screenshots, and answer questions about board pin maps and mpremote/CanMV quirks. Use when the user mentions K230, lckfb 庐山派, CanMV, K230 烧录, K230 推码, K230 调试, K230 串口, K230 截图, K230 日志, K230 deploy, push to k230, k230 screenshot, k230 serial log, k230 firmware, k230 flash, mpremote.
---

# K230 (lckfb 庐山派 CanMV) toolkit

K230 is the AI SoC on the lckfb 庐山派 dev board: Kanaan / Canaan K230,
dual-core Cortex-A55 + KPU (NPU) + DPU + GPU + ISP, running **CanMV**
(MicroPython on RT-Smart). Firmware is one or more `*.py` files dropped on
the on-board SD card; `/sdcard/main.py` auto-runs at boot.

This skill bundles three workflows: **deploy** code, **capture+analyze**
serial logs, **screenshot** the camera frame.

## Hardware / port facts

- USB-CDC port on macOS: typically `/dev/cu.usbmodem0010000001` (Kendryte
  CanMV, VID:PID `1209:abd1`). On Linux: `/dev/ttyACM*`. Only ONE serial
  port — REPL and stdout share it.
- Baud rate: **115200** (CanMV default; not configurable on the K230 side).
- mpremote: `pip3 install --user mpremote` → usually
  `~/Library/Python/3.9/bin/mpremote` on macOS, `~/.local/bin/mpremote` on Linux.
- Boot entry: `/sdcard/main.py` auto-runs at reset, never exits until interrupted.
- `/sdcard` is **only mounted after a hard reset** (DTR/RTS pulse via
  `mpremote ... reset`). After a Ctrl-D soft reset, `os.listdir("/sdcard")`
  returns `[]` until next power cycle.
- `sys.path` on CanMV includes `/sdcard` — any `.py` file dropped there is
  importable from main.py.

## Common pin / FPIOA cheatsheet (lckfb 庐山派)

| Function | Pin | FPIOA mapping |
|---|---|---|
| UART2 TXD | GPIO5 | `FPIOA.UART2_TXD` |
| UART2 RXD | GPIO6 | `FPIOA.UART2_RXD` |
| Onboard buzzer (passive) | GPIO43 | `FPIOA.PWM1` |
| I²C1 (touch + LCD backlight GP7101) | shared SCL/SDA | auto-configured by SDK |
| 3.1" MIPI LCD | DSI lanes | `Display.ST7701` driver |

LCD backlight is **not** a direct GPIO — it goes through a GP7101 I²C-to-PWM
chip (7-bit address `0x58`) on the I²C1 bus, then drives an SY7201ABC LED
driver. Write a single byte (0–255 PWM duty) to control brightness:
`I2C(1, freq=400000).writeto(0x58, bytes([duty]))`.

## mpremote quirks on K230

1. **`mpremote exec` / raw-paste enter sequence often hangs**. The K230 main
   loop frequently has nested `try / except` that swallows a single Ctrl-C,
   so the raw-paste handshake times out. Always send a **raw 10×Ctrl-C burst
   via pyserial first**, then use `mpremote ... resume <subcommand>` so
   mpremote attaches to the existing REPL without re-entering raw-paste.
2. **`mpremote connect ... reset` also needs `resume`**. Without it, mpremote
   tries to enter raw paste mode again and falls into the same trap.
3. **Large files are slow over 115200 baud**: ~5–10 KB/s, so a 150 KB main.py
   takes ~80 seconds. mpremote 1.28 has a content-hash check, so re-pushing
   an unchanged file is instant (`Up to date: /sdcard/foo.py`).
4. **PWM ctor argument signatures vary by CanMV build**. `PWM(ch, freq, duty,
   enable=False)` may raise "extra positional arguments given" — fall back to
   `PWM(ch)` + individual `freq()` / `duty()` / `enable()` setter calls.
   `enable(0)` is not always honored on the lckfb build — use `duty(0)` as
   the canonical "silent" state for buzzers.
5. **`I2C` does not have `I2C.I2C0` / `I2C.I2C1` enum attributes** on this
   CanMV build. Pass the bus number as a bare integer: `I2C(1, freq=400000)`.

## Workflow: deploying firmware

```bash
# Push every *.py in the current dir to /sdcard/ and reset.
python3 scripts/push_k230.py

# Or specify files explicitly
python3 scripts/push_k230.py main.py mod.py

# Use a different source dir
python3 scripts/push_k230.py --src-dir firmware/

# Skip the reset (useful when iterating fast)
python3 scripts/push_k230.py --no-reset

# Different port
PORT=/dev/ttyACM0 python3 scripts/push_k230.py
```

What the script does:

1. **Interrupt** running main.py — sends 10×Ctrl-C via raw pyserial.
2. **Push** — `mpremote connect <port> resume fs cp <local> :/sdcard/<name>`
   for each file. Uses `resume` so mpremote doesn't try to re-enter raw paste.
3. **Reset** — `mpremote ... resume reset`; falls back to Ctrl-D soft reset
   if that fails (less reliable: SD card may not re-mount).

Manual fallback when the script can't grab the REPL:

```bash
# 1. Raw Ctrl-C burst
python3 -c "import serial,time; p=serial.Serial('/dev/cu.usbmodem0010000001',115200,timeout=0.3); [p.write(b'\\x03') or time.sleep(0.15) for _ in range(10)]; p.close()"

# 2. Push
mpremote connect /dev/cu.usbmodem0010000001 resume cp main.py :/sdcard/main.py

# 3. Hard reset
mpremote connect /dev/cu.usbmodem0010000001 resume reset
```

## Workflow: capturing serial logs

```bash
# 30s capture, default port, log → ./logs/k230-<ts>.log
python3 scripts/serial_log.py

# Force a soft-reset (Ctrl-D) before capture, to grab the full boot trace
python3 scripts/serial_log.py --reset --duration 60

# Stop a running main.py and capture REPL output
python3 scripts/serial_log.py --break-first --duration 20

# Collapse a noisy repeated line (e.g. face firmware spamming "NO_FACE")
python3 scripts/serial_log.py --dedup-pattern "NO_FACE"
```

## Workflow: camera frame screenshot

```bash
# One-time: patch main.py to dump a stride-subsampled snapshot to /sdcard/snap.rgb every 3s
python3 scripts/screenshot.py --install

# Grab a frame → snaps/snap-<ts>.jpg
python3 scripts/screenshot.py

# Open in default viewer (macOS)
python3 scripts/screenshot.py --open

# Remove the patch
python3 scripts/screenshot.py --uninstall
```

This is a non-trivial dance: the K230 main loop holds the camera and deinits
it on Ctrl-C, so by the time mpremote attaches the in-RAM frame is gone.
The script side-channels a 700 KB raw frame through `/sdcard/snap.rgb` and
decodes CHW → HWC + JPEG locally.

## Use as a Claude Code skill

Drop this directory into `.claude/skills/k230/` of any project, or clone it
to `~/.claude/skills/k230/` for global availability. Claude Code's skill
loader will pick up `SKILL.md` and surface this toolkit when the user
mentions K230 / lckfb 庐山派 in conversation.

## Prerequisites

```bash
pip3 install --user mpremote pyserial
```

That's it. No K230 SDK needed locally — all the heavy lifting (kmodel
inference, camera, display) runs on the device.
