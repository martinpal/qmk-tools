#!/usr/bin/env python3
"""Summarize key usage from heatmap_logger files.

Examples:
    heatmap_report.py                         # everything in the default directory
    heatmap_report.py --from 2026-10-01 --to 2026-10-08
    heatmap_report.py --from "2026-10-19 08:00" --layer 0
    heatmap_report.py --from 7d                # last 7 days
    heatmap_report.py --csv > keys.csv
"""

import argparse
import glob
import os
import re
import struct
import sys
from datetime import datetime, timedelta

from heatmap_logger import HEADER, MAGIC, RECORD

DEFAULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "heatmap_data")


def parse_time(text: str, is_end: bool = False) -> float:
    """Accepts YYYY-MM-DD[ HH:MM[:SS]], 'now', or a relative age like 90m, 12h, 7d."""
    text = text.strip()
    if text == "now":
        return datetime.now().timestamp()
    m = re.fullmatch(r"(\d+)([mhd])", text)
    if m:
        unit = {"m": "minutes", "h": "hours", "d": "days"}[m.group(2)]
        return (datetime.now() - timedelta(**{unit: int(m.group(1))})).timestamp()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt == "%Y-%m-%d" and is_end:
            dt += timedelta(days=1)  # a bare end date is inclusive
        return dt.timestamp()
    raise SystemExit(f"Cannot parse time: {text!r}")


def read_events(path: str, t0: float, t1: float):
    """Yield (ms, row, col, layer, pressed) from one file; ignores a torn final record."""
    with open(path, "rb") as f:
        head = f.read(HEADER.size)
        if len(head) < HEADER.size:
            return None
        magic, version, rows, cols, _ = HEADER.unpack(head)
        if magic != MAGIC or version != 1:
            print(f"Skipping {path}: unknown format", file=sys.stderr)
            return None
        data = f.read()
    data = data[: len(data) - len(data) % RECORD.size]
    lo, hi = int(t0 * 1000), int(t1 * 1000)
    events = [(ms, r, c, l, e) for ms, r, c, l, e, _ in RECORD.iter_unpack(data) if lo <= ms < hi]
    return rows, cols, events


RAMP = (19, 27, 37, 41, 76, 148, 220, 208, 196)  # 256-color backgrounds, cold -> hot


def render_cell(n: int, peak: int, width: int, color: bool) -> str:
    text = f"{n:^{width}}"
    if not color:
        return text
    if n == 0:
        return f"\033[2m{text}\033[0m"
    idx = min(len(RAMP) - 1, int(n / peak * len(RAMP)))
    fg = 97 if idx < 3 else 30
    return f"\033[48;5;{RAMP[idx]};{fg}m{text}\033[0m"


def render_grid(counts: dict, rows: int, cols: int, color: bool) -> str:
    """Matrix counts laid out like the overlay: split boards show both halves side by side,
    right half in mirrored column order."""
    peak = max(counts.values())
    width = max(5, len(str(peak)) + 2)
    cell = lambda r, c: render_cell(counts.get((r, c), 0), peak, width, color)
    lines = []
    if rows % 2 == 0 and rows >= 8:
        half = rows // 2
        for r in range(half):
            left = "".join(cell(r, c) for c in range(cols))
            right = "".join(cell(r + half, c) for c in range(cols - 1, -1, -1))
            lines.append(f"{left} \u2502 {right}")
    else:
        for r in range(rows):
            lines.append("".join(cell(r, c) for c in range(cols)))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=DEFAULT_DIR, help="heatmap data directory")
    ap.add_argument("--from", dest="start", help="range start (inclusive)")
    ap.add_argument("--to", dest="end", help="range end (exclusive; a bare date includes that whole day)")
    ap.add_argument("--layer", type=int, help="only count events on this layer")
    ap.add_argument("--top", type=int, default=10, help="number of most-used keys to list")
    ap.add_argument("--csv", action="store_true", help="print row,col,presses CSV instead of the report")
    ap.add_argument("--no-color", action="store_true", help="plain numbers without colored cells")
    args = ap.parse_args()

    t0 = parse_time(args.start) if args.start else 0.0
    t1 = parse_time(args.end, is_end=True) if args.end else 1e15

    files = sorted(glob.glob(os.path.join(os.path.expanduser(args.dir), "heatmap-*.bin")))
    rows = cols = 0
    counts = {}
    total = 0
    first = last = None
    for path in files:
        # File date is the logical-day start; a day spans < 25h, so skip clearly out-of-range files
        m = re.search(r"heatmap-(\d{4}-\d{2}-\d{2})\.bin$", path)
        if m:
            day = datetime.strptime(m.group(1), "%Y-%m-%d").timestamp()
            if day + 25 * 3600 < t0 or day > t1:
                continue
        res = read_events(path, t0, t1)
        if res is None:
            continue
        rows, cols = max(rows, res[0]), max(cols, res[1])
        for ms, r, c, layer, pressed in res[2]:
            if args.layer is not None and layer != args.layer:
                continue
            first = ms if first is None else min(first, ms)
            last = ms if last is None else max(last, ms)
            if pressed:
                counts[(r, c)] = counts.get((r, c), 0) + 1
                total += 1

    if args.csv:
        print("row,col,presses")
        for (r, c), n in sorted(counts.items()):
            print(f"{r},{c},{n}")
        return

    if not counts:
        print("No key presses in range.")
        return

    fmt = lambda ms: datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{total} presses, {fmt(first)} .. {fmt(last)}"
          + (f", layer {args.layer}" if args.layer is not None else ""))
    print("\nPresses per key:\n")
    print(render_grid(counts, rows, cols, sys.stdout.isatty() and not args.no_color))
    print(f"\nTop {args.top} keys:")
    for (r, c), n in sorted(counts.items(), key=lambda kv: -kv[1])[: args.top]:
        print(f"  row {r} col {c}: {n} ({100 * n / total:.1f}%)")


if __name__ == "__main__":
    main()
