#!/usr/bin/env python3
"""
Proof of concept: temporarily rebind the M65 Ultra's scroll wheel to
volume up/down via ckb-next's live 'bind' command, then restore it.

This talks to the already-running ckb-next daemon through its device
node (same mechanism as corsair_mouse_monitor.py) - no USB access,
no root required as long as the daemon's cmd fifo is world-writable.

Usage:
    python3 wheel_volume_test.py [duration_seconds]
"""

import glob
import sys
import time

M65_ULTRA_PRODUCT_ID = "1b9e"

# Key names as known to ckb-next's keymap (src/daemon/keymap.c)
WHEEL_UP, WHEEL_DOWN = "wheelup", "wheeldn"
VOL_UP, VOL_DOWN = "volup", "voldn"


def find_device() -> str:
    """Locate the ckb-next device directory for the M65 Ultra."""
    for path in glob.glob("/dev/input/ckb*"):
        try:
            with open(f"{path}/productid") as f:
                if f.read().strip().lower() == M65_ULTRA_PRODUCT_ID:
                    return path
        except FileNotFoundError:
            continue  # ckb0 is the root control node, has no productid
    raise RuntimeError("M65 RGB Ultra not found under /dev/input/ckb*")


def send(cmd_path: str, command: str) -> None:
    with open(cmd_path, "w") as cmd:
        cmd.write(command + "\n")
        cmd.flush()


def main() -> None:
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0

    device = find_device()
    cmd_path = f"{device}/cmd"
    print(f"Using device: {device}")

    print(f"Rebinding wheel -> volume for {duration:.0f}s ...")
    send(cmd_path, "active")
    # NOTE: separate bind pairs must be space-separated words, not comma-joined -
    # command.c splits each word on its first ':', and only commas *within* the
    # left side are supported (e.g. "mouse1,mouse2:target"). A comma between two
    # full pairs gets swallowed into the first pair's target and silently ignored.
    send(cmd_path, f"bind {WHEEL_UP}:{VOL_UP} {WHEEL_DOWN}:{VOL_DOWN}")

    try:
        time.sleep(duration)
    finally:
        print("Restoring wheel -> scroll")
        send(cmd_path, f"bind {WHEEL_UP}:{WHEEL_UP} {WHEEL_DOWN}:{WHEEL_DOWN}")


if __name__ == "__main__":
    main()
