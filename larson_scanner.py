#!/usr/bin/env python3
"""
Larson Scanner (Knight Rider / Cylon effect) for boblight LEDs.
"""

import argparse
import signal
import socket
import sys
import time


class BoblightConnection:
    """Minimal boblight TCP connection for direct LED control."""

    def __init__(self, host, port, priority):
        self.host = host
        self.port = port
        self.priority = priority
        self.sock = None
        self.light_names = []
        self._active_leds = set()  # LEDs currently set to "use on"

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5.0)
        self.sock.connect((self.host, self.port))

        self._send("hello\n")
        resp = self._recv()
        if not resp or not resp.startswith("hello"):
            raise ConnectionError(f"Bad handshake: {resp}")

        self._send(f"set priority {self.priority}\n")

        self._send("get lights\n")
        resp = self._recv()
        if resp and resp.startswith("lights"):
            lines = resp.strip().split('\n')
            for line in lines[1:]:
                if line.startswith("light "):
                    self.light_names.append(line.split()[1])

        # Start with all LEDs released (use off)
        for name in self.light_names:
            self._send(f"set light {name} use off\n")
        self._send("sync\n")
        self._active_leds.clear()

        print(f"Connected to {self.host}:{self.port} ({len(self.light_names)} lights)")

    def set_leds(self, lit_leds):
        """Set LED colors, releasing unlit LEDs to lower-priority clients.

        Args:
            lit_leds: dict mapping LED index to (r, g, b) tuples (0.0-1.0).
                      LEDs not in the dict are released (use off).
        """
        needed = set(lit_leds.keys())

        # Release LEDs that are no longer needed
        for idx in self._active_leds - needed:
            if idx < len(self.light_names):
                self._send(f"set light {self.light_names[idx]} use off\n")

        # Activate and set color for lit LEDs
        for idx, (r, g, b) in lit_leds.items():
            if idx < len(self.light_names):
                if idx not in self._active_leds:
                    self._send(f"set light {self.light_names[idx]} use on\n")
                self._send(f"set light {self.light_names[idx]} rgb {r:.6f} {g:.6f} {b:.6f}\n")

        self._send("sync\n")
        self._active_leds = needed

    def close(self):
        if self.sock:
            try:
                # Release all LEDs back to lower-priority clients
                for name in self.light_names:
                    self._send(f"set light {name} use off\n")
                self._send("sync\n")
                self.sock.close()
            except:
                pass

    def _send(self, data):
        self.sock.sendall(data.encode('utf-8'))

    def _recv(self, size=4096):
        return self.sock.recv(size).decode('utf-8')


def parse_color(color_str):
    """Parse color string: name or R,G,B (0-255)."""
    names = {
        'red': (1.0, 0.0, 0.0),
        'green': (0.0, 1.0, 0.0),
        'blue': (0.0, 0.0, 1.0),
        'cyan': (0.0, 1.0, 1.0),
        'magenta': (1.0, 0.0, 1.0),
        'yellow': (1.0, 1.0, 0.0),
        'white': (1.0, 1.0, 1.0),
        'orange': (1.0, 0.5, 0.0),
    }
    lower = color_str.lower()
    if lower in names:
        return names[lower]
    parts = color_str.split(',')
    if len(parts) == 3:
        return tuple(int(p) / 255.0 for p in parts)
    raise ValueError(f"Unknown color: {color_str}. Use a name or R,G,B (0-255)")


def main():
    parser = argparse.ArgumentParser(description='Larson Scanner (Knight Rider effect) for boblight LEDs')
    parser.add_argument('--host', default='localhost', help='boblightd host (default: localhost)')
    parser.add_argument('--port', type=int, default=19333, help='boblightd port (default: 19333)')
    parser.add_argument('--priority', type=int, default=0, help='Boblight priority (default: 0, highest)')
    parser.add_argument('--leds', type=int, default=13, help='Number of LEDs (default: 13)')
    parser.add_argument('--color', default='red', help='Color: name or R,G,B e.g. "red" or "255,0,0" (default: red)')
    parser.add_argument('--speed', type=float, default=0.06, help='Seconds per step (default: 0.06)')
    parser.add_argument('--tail', type=int, default=3, help='Tail length in LEDs (default: 3)')
    args = parser.parse_args()

    color = parse_color(args.color)
    num_leds = args.leds

    conn = BoblightConnection(args.host, args.port, args.priority)

    running = True

    def on_signal(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    try:
        conn.connect()
        print(f"Larson scanner: {num_leds} LEDs, color={args.color}, speed={args.speed}s, tail={args.tail}")
        print("Transparent: unlit LEDs show boblight-X11 colors")
        print("Press Ctrl+C to stop")

        # Bounce back and forth: 0,1,2,...,12,11,10,...,1,0,1,...
        positions = list(range(num_leds)) + list(range(num_leds - 2, 0, -1))
        step = 0

        while running:
            pos = positions[step % len(positions)]

            # Only include lit LEDs (head + tail)
            lit_leds = {}

            # Head LED at full brightness
            lit_leds[pos] = color

            # Tail: fading LEDs behind the head
            for t in range(1, args.tail + 1):
                brightness = 1.0 - t / (args.tail + 1)
                brightness = brightness ** 1.5  # Gamma for smoother fade

                # Look back in the path to find where the tail LEDs are
                tail_step = (step - t) % len(positions)
                tail_pos = positions[tail_step]

                r, g, b = color
                tail_color = (r * brightness, g * brightness, b * brightness)

                # Use max if two tail positions overlap (at bounce points)
                if tail_pos in lit_leds:
                    existing = lit_leds[tail_pos]
                    lit_leds[tail_pos] = (
                        max(existing[0], tail_color[0]),
                        max(existing[1], tail_color[1]),
                        max(existing[2], tail_color[2]),
                    )
                else:
                    lit_leds[tail_pos] = tail_color

            conn.set_leds(lit_leds)

            step += 1
            time.sleep(args.speed)

    except ConnectionError as e:
        print(f"Connection error: {e}", file=sys.stderr)
        return 1
    finally:
        print("\nStopping...")
        conn.close()

    return 0


if __name__ == '__main__':
    sys.exit(main())
