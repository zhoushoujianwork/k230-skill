# k230-skill

Tooling + AI-assistant context for the K230 (lckfb 庐山派) CanMV dev board.

## What is this

Three small Python scripts that wrap [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html)
to make K230 firmware iteration painless, plus a `SKILL.md` that teaches
AI coding assistants (Claude Code, etc.) the board's pin map, mpremote
quirks, and common workflows so they stop guessing.

K230 = Kanaan / Canaan K230 SoC: Cortex-A55 dual + KPU + DPU + GPU + ISP,
running [CanMV](https://github.com/kendryte/k230_canmv) (MicroPython on
RT-Smart). lckfb's 庐山派 is the most accessible dev board for it.

## Why this exists

mpremote on K230 has a half-dozen sharp edges that take hours to discover:

- `mpremote exec` hangs because the running `main.py` swallows Ctrl-C
- `mpremote reset` fails the same way; you need `resume reset`
- `/sdcard` disappears after a soft reset until next hard reset
- `PWM(ch, freq, duty, enable=False)` raises "extra positional" on this CanMV build
- `I2C.I2C1` is not a real attribute — pass the bus number as a bare int

The scripts and SKILL.md capture all of this so the next person (or LLM)
doesn't have to rediscover it.

## Install

```bash
pip3 install --user mpremote pyserial
git clone https://github.com/zhoushoujian/k230-skill ~/k230-skill
```

## Use directly from the shell

```bash
cd your-k230-firmware-project/

# Push every *.py in the cwd to /sdcard/ and reset
python3 ~/k230-skill/scripts/push_k230.py

# Push specific files
python3 ~/k230-skill/scripts/push_k230.py main.py buzzer.py

# Capture 30s of serial output
python3 ~/k230-skill/scripts/serial_log.py

# See full boot trace
python3 ~/k230-skill/scripts/serial_log.py --reset --duration 60

# Grab a camera frame (one-time --install first)
python3 ~/k230-skill/scripts/screenshot.py --install
python3 ~/k230-skill/scripts/screenshot.py --open
```

`--help` on each script lists every flag.

## Use as a Claude Code skill

```bash
# Per-project
cp -r ~/k230-skill .claude/skills/k230/

# Or global
mkdir -p ~/.claude/skills
ln -s ~/k230-skill ~/.claude/skills/k230
```

When you talk to Claude Code about K230 (mention "lckfb 庐山派",
"K230 烧录", "k230 deploy", etc.), it will load `SKILL.md` and use the
scripts in `scripts/` directly — no copy-paste needed.

## What's in `SKILL.md`

- Hardware / port facts: USB-CDC port name, baud rate, mpremote install path
- Pin / FPIOA cheatsheet: UART2 pins, buzzer pin, I²C buses, LCD driver
- mpremote quirks: 5 specific gotchas with workarounds
- Workflow recipes: deploy, capture logs, screenshot
- Why each script does what it does (so you can hack it)

## Status

- macOS Apple Silicon (Python 3.9 from Xcode CLT): primary tested env
- Linux x86_64: should work, port path differs (`/dev/ttyACM*`)
- Windows: untested; PRs welcome

## License

MIT — see `LICENSE`.
