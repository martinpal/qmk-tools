#!/usr/bin/env python3
"""
Boblight Client for QMK Overlay Integration

Connects to boblightd daemon and controls LED colors based on keyboard layer changes.
Supports configurable LED selection for partial lighting control.
"""

import socket
import threading
import time
from typing import Optional, List, Tuple


class BoblightClient:
    """Client for communicating with boblightd daemon"""

    def __init__(self, host: str = "localhost", port: int = 19333,
                 priority: int = 100, led_indices: Optional[List[int]] = None):
        """
        Initialize boblight client

        Args:
            host: Boblight server hostname (default: localhost)
            port: Boblight server port (default: 19333)
            priority: Priority level for this client (default: 100, LOWER = more important, 255 = disabled)
            led_indices: List of LED indices to control (None = all LEDs)
        """
        self.host = host
        self.port = port
        self.priority = priority
        self.led_indices = led_indices
        self.sock = None
        self.connected = False
        self.lock = threading.Lock()
        self.num_lights = 0
        self.light_names = []

    def connect(self) -> bool:
        """Connect to boblightd server"""
        with self.lock:
            try:
                # Close existing connection if any
                if self.sock:
                    try:
                        self.sock.close()
                    except:
                        pass
                    self.sock = None

                # Create new connection
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(5.0)
                self.sock.connect((self.host, self.port))

                # Boblight handshake
                self._send("hello\n")
                response = self._recv()
                if not response or not response.startswith("hello"):
                    print(f"[BOBLIGHT] Invalid handshake response: {response}")
                    self.sock.close()
                    self.sock = None
                    return False

                # Set priority
                self._send(f"set priority {self.priority}\n")

                # Get light names
                self._send("get lights\n")
                lights_response = self._recv()
                if lights_response and lights_response.startswith("lights"):
                    # Parse: "lights <count>\nlight <name>\nlight <name>\n..."
                    lines = lights_response.strip().split('\n')
                    if len(lines) > 0:
                        try:
                            self.num_lights = int(lines[0].split()[1])
                            self.light_names = []
                            for line in lines[1:]:
                                if line.startswith("light "):
                                    self.light_names.append(line.split()[1])
                        except (IndexError, ValueError) as e:
                            print(f"[BOBLIGHT] Failed to parse lights response: {e}")

                self.connected = True
                print(f"[BOBLIGHT] Connected to {self.host}:{self.port} ({self.num_lights} lights)")
                if self.led_indices:
                    print(f"[BOBLIGHT] Controlling LED indices: {self.led_indices}")
                else:
                    print(f"[BOBLIGHT] Controlling all LEDs")
                return True

            except (socket.error, socket.timeout, OSError) as e:
                print(f"[BOBLIGHT] Connection failed - {e}")
                self.connected = False
                if self.sock:
                    try:
                        self.sock.close()
                    except:
                        pass
                    self.sock = None
                return False

    def disconnect(self):
        """Disconnect from boblightd server"""
        with self.lock:
            if self.sock:
                try:
                    self.sock.close()
                except:
                    pass
                self.sock = None
            self.connected = False

    def _send(self, data: str) -> bool:
        """Send data to boblight server"""
        try:
            self.sock.sendall(data.encode('utf-8'))
            return True
        except (socket.error, OSError) as e:
            print(f"[BOBLIGHT] Send failed - {e}")
            self.connected = False
            return False

    def _recv(self, buffer_size: int = 4096) -> str:
        """Receive data from boblight server"""
        try:
            data = self.sock.recv(buffer_size)
            return data.decode('utf-8')
        except (socket.error, OSError) as e:
            print(f"[BOBLIGHT] Receive failed - {e}")
            self.connected = False
            return ""

    def set_color(self, r: float, g: float, b: float) -> bool:
        """
        Set color for configured LEDs

        Args:
            r, g, b: RGB values in range 0.0-1.0

        Returns:
            True if successful, False otherwise
        """
        with self.lock:
            if not self.connected or not self.sock:
                return False

            try:
                # Determine which lights to control
                if self.led_indices is not None:
                    # Control only specified LEDs
                    lights_to_set = [self.light_names[i] for i in self.led_indices
                                    if i < len(self.light_names)]
                else:
                    # Control all LEDs
                    lights_to_set = self.light_names

                # Set color for each light (debug output removed to avoid spam during refresh)
                for light_name in lights_to_set:
                    command = f"set light {light_name} rgb {r:.6f} {g:.6f} {b:.6f}\n"
                    if not self._send(command):
                        return False

                # Sync to apply changes
                if not self._send("sync\n"):
                    return False

                return True

            except Exception as e:
                print(f"[BOBLIGHT] Error setting color - {e}")
                self.connected = False
                return False

    def set_color_from_qcolor(self, qcolor) -> bool:
        """
        Set color from PyQt5 QColor object

        Args:
            qcolor: PyQt5.QtGui.QColor object

        Returns:
            True if successful, False otherwise
        """
        r = qcolor.red() / 255.0
        g = qcolor.green() / 255.0
        b = qcolor.blue() / 255.0
        return self.set_color(r, g, b)

    def set_color_from_hex(self, hex_color: str) -> bool:
        """
        Set color from hex string

        Args:
            hex_color: Hex color string (e.g., "#FF0000" or "FF0000")

        Returns:
            True if successful, False otherwise
        """
        # Remove # if present
        hex_color = hex_color.lstrip('#')

        # Parse RGB
        try:
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0
            return self.set_color(r, g, b)
        except (ValueError, IndexError) as e:
            print(f"[BOBLIGHT] Invalid hex color '{hex_color}' - {e}")
            return False

    def clear(self) -> bool:
        """Clear (turn off) configured LEDs by setting to black"""
        return self.set_color(0.0, 0.0, 0.0)

    def set_priority(self, priority: int) -> bool:
        """
        Change priority dynamically

        Args:
            priority: New priority (0-254 active, 255 = disabled)

        Returns:
            True if successful, False otherwise
        """
        with self.lock:
            if not self.connected or not self.sock:
                return False

            try:
                command = f"set priority {priority}\n"
                if self._send(command):
                    self.priority = priority
                    print(f"[BOBLIGHT] Priority changed to {priority}")
                    return True
                return False
            except Exception as e:
                print(f"[BOBLIGHT] Error setting priority - {e}")
                return False

    def reconnect(self) -> bool:
        """Attempt to reconnect to boblightd"""
        print("[BOBLIGHT] Attempting to reconnect...")
        self.disconnect()
        time.sleep(1)
        return self.connect()
