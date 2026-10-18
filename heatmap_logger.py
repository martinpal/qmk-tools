#!/usr/bin/env python3
"""Append-only key event logger for building a keyboard usage heatmap.

File format (little endian), one file per "logical day":

    header (16 bytes): magic "QMKHEAT1", u16 version, u8 rows, u8 cols, u32 reserved
    record (16 bytes): u64 unix time in ms, u8 row, u8 col, u8 layer, u8 event
                       (1 = press, 0 = release), u32 reserved

A logical day starts at `rollover_hour` local time (default 05:00), so events
at 02:00 belong to the previous day's file. Files are named
heatmap-YYYY-MM-DD.bin after the date on which the logical day started.
"""

import os
import struct
import threading
import time
from datetime import datetime, timedelta

MAGIC = b"QMKHEAT1"
VERSION = 1
HEADER = struct.Struct("<8sHBBI")
RECORD = struct.Struct("<QBBBBI")
FLUSH_BYTES = 4096


def day_start(ts: float, rollover_hour: int) -> datetime:
    """Local datetime at which the logical day containing `ts` began."""
    dt = datetime.fromtimestamp(ts)
    start = dt.replace(hour=rollover_hour, minute=0, second=0, microsecond=0)
    if dt < start:
        start -= timedelta(days=1)
    return start


def file_name(start: datetime) -> str:
    return f"heatmap-{start:%Y-%m-%d}.bin"


class HeatmapLogger:
    def __init__(self, directory: str, rows: int, cols: int,
                 rollover_hour: int = 5, flush_interval: float = 5.0):
        self.directory = os.path.expanduser(directory)
        self.rows = rows
        self.cols = cols
        self.rollover_hour = rollover_hour
        self.flush_interval = flush_interval
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._file = None
        self._next_rollover = 0.0  # unix time at which the open file expires
        self._last_flush = time.monotonic()
        os.makedirs(self.directory, mode=0o700, exist_ok=True)
        os.chmod(self.directory, 0o700)
        self._chown_to_sudo_user(self.directory)

    @staticmethod
    def _chown_to_sudo_user(path: str):
        """Files created under sudo should stay readable by the invoking user."""
        sudo_uid, sudo_gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
        if sudo_uid and sudo_gid:
            try:
                os.chown(path, int(sudo_uid), int(sudo_gid))
            except OSError:
                pass

    def log(self, row: int, col: int, layer: int, pressed: bool):
        now = time.time()
        with self._lock:
            if now >= self._next_rollover:
                self._rotate(now)
            self._buf += RECORD.pack(int(now * 1000), row, col, layer, 1 if pressed else 0, 0)
            if len(self._buf) >= FLUSH_BYTES:
                self._flush()

    def tick(self):
        """Call periodically; flushes buffered records after flush_interval."""
        if self._buf and time.monotonic() - self._last_flush >= self.flush_interval:
            with self._lock:
                self._flush()

    def close(self):
        with self._lock:
            self._flush()
            if self._file:
                self._file.close()
                self._file = None

    def _rotate(self, now: float):
        self._flush()
        if self._file:
            self._file.close()
        start = day_start(now, self.rollover_hour)
        path = os.path.join(self.directory, file_name(start))
        new = not os.path.exists(path) or os.path.getsize(path) == 0
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        os.fchmod(fd, 0o600)  # enforce even if the file already existed with looser perms
        self._file = os.fdopen(fd, "ab")
        if new:
            self._file.write(HEADER.pack(MAGIC, VERSION, self.rows, self.cols, 0))
            self._file.flush()
        self._next_rollover = (start + timedelta(days=1)).timestamp()
        if new:
            self._chown_to_sudo_user(path)

    def _flush(self):
        if self._buf and self._file:
            self._file.write(self._buf)
            self._file.flush()
        self._buf.clear()
        self._last_flush = time.monotonic()
