#!/usr/bin/env python3
"""Audible nudges for habits being retrained.

Plays a harsh buzz when a key press hits one of the old pinky keys (Esc /
Grave-Esc / Grave / Backspace / Delete on an outer column) and a mild blip when a
finger reaches for the top row on the chosen layers. Each kind has its own
cooldown so a burst of presses makes one sound.
"""

import math
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import wave
from typing import Callable, Dict, Iterable, List, Optional, Tuple

KC_ESC, KC_BSPC, KC_DEL, KC_GRV, QK_GESC = 0x0029, 0x002A, 0x004C, 0x0035, 0x7C16
OLD_KEYS = frozenset({KC_ESC, KC_BSPC, KC_DEL, KC_GRV, QK_GESC})

OLD_KEY = "old_key"
TOP_ROW = "top_row"

SAMPLE_RATE = 22050


def classify(row: int, col: int, layer: int, keycode: int, rows: int,
             top_row_layers: Iterable[int], pinky_cols: int = 2) -> Optional[str]:
    """OLD_KEY, TOP_ROW or None for a key press.

    rows is the matrix row count: a split board stores one half after the other,
    so each half has rows // 2 rows and the last of them is the thumb row.
    A KC_NO key never counts.
    """
    if keycode == 0x0000:
        return None
    half = rows // 2 if rows > 5 else rows
    row_in_half = row % half
    if row_in_half == half - 1:  # thumb row
        return None
    if keycode in OLD_KEYS and col < pinky_cols:
        return OLD_KEY
    if row_in_half == 0 and layer in top_row_layers:
        return TOP_ROW
    return None


def _write_tone(path: str, segments, volume: float = 0.6) -> None:
    """segments: list of (frequency Hz, seconds, square 0..1 mix); 0 Hz is silence."""
    samples = []
    for freq, seconds, square in segments:
        n = int(SAMPLE_RATE * seconds)
        for i in range(n):
            if freq <= 0:
                samples.append(0.0)
                continue
            phase = 2 * math.pi * freq * i / SAMPLE_RATE
            sine = math.sin(phase)
            value = (1 - square) * sine + square * (1.0 if sine >= 0 else -1.0)
            fade = min(1.0, i / 120, (n - i) / 120)  # avoid clicks
            samples.append(value * fade)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"".join(struct.pack("<h", int(s * volume * 32767)) for s in samples))


class HabitCoach:
    """Decides when to play a sound and plays it without blocking the caller."""

    def __init__(self, rows: int, top_row_layers: Iterable[int] = (0, 2, 3), cooldown: float = 5.0,
                 player: Optional[Callable[[str], None]] = None, clock: Callable[[], float] = time.monotonic):
        self.rows = rows
        self.top_row_layers = frozenset(top_row_layers)
        self.cooldown = cooldown
        self.clock = clock
        self.last_played: Dict[str, float] = {}
        self.dir = tempfile.mkdtemp(prefix="qmk-habit-sounds-")
        self.files = {OLD_KEY: os.path.join(self.dir, "old_key.wav"),
                      TOP_ROW: os.path.join(self.dir, "top_row.wav")}
        # Old key: two low, rough buzzes. Top row: one short soft blip.
        _write_tone(self.files[OLD_KEY], [(140, 0.14, 0.9), (0, 0.05, 0), (110, 0.2, 0.9)])
        _write_tone(self.files[TOP_ROW], [(660, 0.07, 0.0)], volume=0.35)
        self.play = player or self._play_file

    def on_press(self, row: int, col: int, layer: int, keycode: int) -> Optional[str]:
        """Call for every key press; returns the kind that was played, if any."""
        kind = classify(row, col, layer, keycode, self.rows, self.top_row_layers)
        if kind is None:
            return None
        now = self.clock()
        last = self.last_played.get(kind)
        if last is not None and now - last < self.cooldown:
            return None
        self.last_played[kind] = now
        print(f"[HABIT] {kind} at row {row}, col {col}, layer {layer}")
        self.play(self.files[kind])
        return kind

    def close(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def _play_file(self, path: str) -> None:
        """Play a file in a background thread so key polling never waits for the player."""
        threading.Thread(target=self._run_player, args=(path,), daemon=True).start()

    @staticmethod
    def _run_player(path: str) -> None:
        attempts = player_attempts(path)
        if not attempts:
            print("[HABIT] No sound player found (paplay, pw-play, aplay)")
            return
        for label, cmd, env in attempts:
            try:
                result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired) as e:
                print(f"[HABIT] Sound player ({label}) failed: {e}")
                continue
            if result.returncode == 0:
                return
            print(f"[HABIT] Sound player ({label}) exited {result.returncode}: {result.stderr.strip()}")


def player_attempts(path: str, environ=None, euid: Optional[int] = None) -> List[Tuple[str, List[str], dict]]:
    """Commands to try, in order, as (label, argv, environment).

    The overlay normally runs as root under sudo, while the sound server belongs
    to the user who started sudo (SUDO_UID). First try the player directly with
    that user's server address, then as that user through sudo.
    """
    environ = dict(os.environ if environ is None else environ)
    euid = os.geteuid() if euid is None else euid
    for tool in ("paplay", "pw-play", "aplay"):
        exe = shutil.which(tool)
        if exe:
            break
    else:
        return []
    argv = [exe] + (["-q"] if tool == "aplay" else []) + [path]
    uid = environ.get("SUDO_UID")
    if euid != 0 or not uid:
        return [("direct", argv, environ)]
    runtime = f"/run/user/{uid}"
    env = dict(environ, XDG_RUNTIME_DIR=runtime, PULSE_SERVER=f"unix:{runtime}/pulse/native")
    return [
        ("root, user's sound server", argv, env),
        ("sudo -u user", ["sudo", "-n", "-u", f"#{uid}", "env", f"XDG_RUNTIME_DIR={runtime}"] + argv, environ),
    ]
