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


# Keep in sync with layer_info / qt_colors in keyboard_overlay_gui.py (not importable here: it pulls in PyQt)
LAYER_NAMES = {0: "Base", 1: "Game", 2: "Lower", 3: "Raise", 4: "Adjust", 5: "Mouse", 6: "Extra"}
LAYER_COLORS = {
    0: ("white", (120, 120, 120)),
    1: ("cyan", (0, 255, 255)),
    2: ("red", (255, 50, 50)),
    3: ("blue", (100, 150, 255)),
    4: ("green", (80, 220, 80)),
    5: ("orange", (255, 165, 0)),
    6: ("magenta", (255, 0, 255)),
}


def layer_label(layer: int) -> str:
    """'4 (Adjust, green)'; falls back to the bare number for unknown layers."""
    name = LAYER_NAMES.get(layer)
    color = LAYER_COLORS.get(layer)
    if name and color:
        return f"{layer} ({name}, {color[0]})"
    return f"{layer} ({name})" if name else str(layer)


def layer_swatch(layer: int, color: bool) -> str:
    """Colored block for the layer header; empty in plain output or for unknown layers."""
    rgb = LAYER_COLORS.get(layer)
    if not color or not rgb:
        return ""
    r, g, b = rgb[1]
    return f"\033[38;2;{r};{g};{b}m\u2588\u2588\033[0m "


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


def is_split(rows: int) -> bool:
    return rows % 2 == 0 and rows >= 8


def column_totals(counts: dict, rows: int, cols: int):
    """Per-column press totals, skipping each half's last row (the thumb cluster) on split boards.
    Returns (left, right) lists indexed by matrix column; right is None on non-split boards."""
    if not is_split(rows):
        return [sum(counts.get((r, c), 0) for r in range(rows)) for c in range(cols)], None
    half = rows // 2
    left = [sum(counts.get((r, c), 0) for r in range(half - 1)) for c in range(cols)]
    right = [sum(counts.get((r, c), 0) for r in range(half, rows - 1)) for c in range(cols)]
    return left, right


def grid_widths(counts: dict, rows: int, cols: int) -> tuple:
    """(cell width, row-total width) for the overall counts; share across all grids so they align.
    Overall counts bound every per-layer grid, including the column totals and their corners."""
    left, right = column_totals(counts, rows, cols)
    row_max = max(sum(counts.get((r, c), 0) for c in range(cols)) for r in range(rows))
    cell_max = max([max(counts.values())] + left + (right or []))
    corner_max = max(sum(left), sum(right or [0]))
    return max(5, len(str(cell_max)) + 2), max(len(str(max(row_max, corner_max))), 1)


def render_grid(counts: dict, rows: int, cols: int, color: bool, widths: tuple = None,
                header: bool = False) -> str:
    """Matrix counts laid out like the overlay: split boards show both halves side by side,
    right half in mirrored column order, with each half's row total at the outer edges.
    header=True adds column numbers above the grid. A totals row follows the grid
    (thumb row excluded on split boards); its corners are the sums of the column totals."""
    peak = max(counts.values())
    width, tw = widths or grid_widths(counts, rows, cols)
    cell = lambda r, c: render_cell(counts.get((r, c), 0), peak, width, color)
    total = lambda r: sum(counts.get((r, c), 0) for c in range(cols))
    num = lambda n: f"{n:^{width}}"
    left_tot, right_tot = column_totals(counts, rows, cols)
    lines = []
    if is_split(rows):
        half = rows // 2
        if header:
            # Left half 1..N left to right; right half N..1 left to right (1 = outer edge)
            lines.append(" " * (tw + 2) + "".join(num(c + 1) for c in range(cols))
                         + " \u2502 " + "".join(num(c + 1) for c in range(cols - 1, -1, -1)))
        for r in range(half):
            left = "".join(cell(r, c) for c in range(cols))
            right = "".join(cell(r + half, c) for c in range(cols - 1, -1, -1))
            lines.append(f"{total(r):>{tw}} |{left} \u2502 {right}| {total(r + half):>{tw}}")
        bar = "\u2500" * (cols * width)
        lines.append(" " * tw + f" |{bar}\u2500\u253c\u2500{bar}|")
        lines.append(f"{sum(left_tot):>{tw}} |" + "".join(num(n) for n in left_tot)
                     + " \u2502 " + "".join(num(n) for n in reversed(right_tot))
                     + f"| {sum(right_tot):>{tw}}")
    else:
        if header:
            lines.append(" " * (tw + 2) + "".join(num(c + 1) for c in range(cols)))
        for r in range(rows):
            lines.append(f"{total(r):>{tw}} |" + "".join(cell(r, c) for c in range(cols)))
        lines.append(" " * tw + " |" + "\u2500" * (cols * width))
        lines.append(f"{sum(left_tot):>{tw}} |" + "".join(num(n) for n in left_tot))
    return "\n".join(lines)


def render_top(counts: dict, rows: int, cols: int, top: int, total: int) -> str:
    """Most-used keys. Split boards get one list per half, side by side, labelled with
    row 1..N within the half and column 1..N counting from the left edge (left half)
    or the right edge (right half), matching the grid header."""
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    entry = lambda row, col, n: f"row {row} col {col}: {n} ({100 * n / total:.1f}%)"
    if not is_split(rows):
        lines = [f"Top {top} keys:"]
        lines += [f"  {entry(r + 1, c + 1, n)}" for (r, c), n in ranked[:top]]
        return "\n".join(lines)
    half = rows // 2
    left = [entry(r + 1, c + 1, n) for (r, c), n in ranked if r < half][:top]
    right = [entry(r - half + 1, c + 1, n) for (r, c), n in ranked if r >= half][:top]
    head_l, head_r = f"Top {top} left half:", f"Top {top} right half:"
    w = max([len(head_l)] + [len(x) + 2 for x in left])
    lines = [f"{head_l:<{w}}    {head_r}"]
    for i in range(max(len(left), len(right))):
        l = f"  {left[i]}" if i < len(left) else ""
        r = f"  {right[i]}" if i < len(right) else ""
        lines.append(f"{l:<{w}}    {r}".rstrip())
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=DEFAULT_DIR, help="heatmap data directory")
    ap.add_argument("--from", dest="start", help="range start (inclusive)")
    ap.add_argument("--to", dest="end", help="range end (exclusive; a bare date includes that whole day)")
    ap.add_argument("--layer", type=int, help="only count events on this layer")
    ap.add_argument("--top", type=int, default=10, help="number of most-used keys to list")
    ap.add_argument("--csv", action="store_true", help="print row,col,presses CSV instead of the report")
    ap.add_argument("--no-layers", action="store_true", help="skip the per-layer reports")
    ap.add_argument("--no-color", action="store_true", help="plain numbers without colored cells")
    args = ap.parse_args()

    t0 = parse_time(args.start) if args.start else 0.0
    t1 = parse_time(args.end, is_end=True) if args.end else 1e15

    files = sorted(glob.glob(os.path.join(os.path.expanduser(args.dir), "heatmap-*.bin")))
    rows = cols = 0
    counts = {}
    layer_counts = {}  # layer -> {(row, col): presses}
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
                lc = layer_counts.setdefault(layer, {})
                lc[(r, c)] = lc.get((r, c), 0) + 1
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
          + (f", layer {layer_label(args.layer)}" if args.layer is not None else ""))
    print("\nPresses per key:\n")
    color = sys.stdout.isatty() and not args.no_color
    widths = grid_widths(counts, rows, cols)
    print(render_grid(counts, rows, cols, color, widths, header=True))
    print()
    print(render_top(counts, rows, cols, args.top, total))

    if args.layer is None and not args.no_layers:
        for layer in sorted(layer_counts):
            lc = layer_counts[layer]
            n = sum(lc.values())
            print(f"\n{layer_swatch(layer, color)}Layer {layer_label(layer)} \u2014 {n} presses ({100 * n / total:.1f}% of total), peak {max(lc.values())}\n")
            print(render_grid(lc, rows, cols, color, widths))


if __name__ == "__main__":
    main()
