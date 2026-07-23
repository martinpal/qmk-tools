#!/usr/bin/env python3
"""
QMK Keyboard Overlay GUI

A semi-transparent, click-through overlay window that displays the current
keyboard layer in real-time.

Requirements:
    pip install PyQt5 python-xlib

Usage:
    python3 keyboard_overlay_gui.py [--keyboard=INDEX|VID:PID]

Features:
    - Semi-transparent overlay window
    - No window decorations
    - Click-through (except when hotkey held)
    - Real-time layer visualization
    - Global hotkey: Hold Ctrl+Shift+Alt to make interactive
"""

import sys
import threading
import queue
import time
import signal
import socket
import os
from typing import Optional, List, Tuple

# Qt imports
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QGridLayout, QSizePolicy
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QPalette, QColor, QFont

# X11 imports for click-through and global hotkeys
try:
    import Xlib
    from Xlib import X, XK, display as xlib_display
    from Xlib.ext import shape
    XLIB_AVAILABLE = True
except ImportError:
    XLIB_AVAILABLE = False
    print("Warning: python-xlib not available. Click-through and global hotkeys disabled.")
    print("Install with: pip install python-xlib")

# Import our USB keyboard interface
import list_via_keyboards_usb as via

# Import boblight client (optional)
try:
    import boblight_client
    BOBLIGHT_AVAILABLE = True
except ImportError:
    BOBLIGHT_AVAILABLE = False
    print("Warning: boblight_client not available. Boblight integration disabled.")


class LayerUpdateSignal(QObject):
    """Signal emitter for thread-safe GUI updates"""
    layer_changed = pyqtSignal(int, dict, int)  # layer_num, layer_stack, default_layer


class InteractiveSignal(QObject):
    """Signal emitter for interactive mode changes"""
    interactive_changed = pyqtSignal(bool)  # interactive state


class OnTopSignal(QObject):
    """Signal emitter for on-top mode changes"""
    on_top_changed = pyqtSignal(bool)  # on-top state


class ReconnectSignal(QObject):
    """Signal emitter for keyboard reconnection"""
    reconnected = pyqtSignal()  # keyboard reconnected


class GnomeIndicatorBridge:
    """Bridge to update GNOME Shell extension via D-Bus or Unix socket"""

    SOCKET_PATH = '/tmp/qmk-dbus-bridge.sock'

    def __init__(self):
        self.sock = None
        self.use_socket = False
        self.proxy = None

        # Check if running as root
        if os.geteuid() == 0:
            # Running as root - must use Unix socket bridge
            try:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.connect(self.SOCKET_PATH)
                self.use_socket = True
                print("GNOME indicator bridge: Connected via Unix socket")
            except Exception as e:
                print(f"GNOME indicator bridge: Failed to connect to bridge - {e}")
                print(f"Make sure dbus_bridge_helper.py is running as user!")
                self.sock = None
        else:
            # Running as user - can use D-Bus directly
            try:
                import dbus
                bus = dbus.SessionBus()
                obj = bus.get_object('com.qmk.LayerIndicator', '/com/qmk/LayerIndicator')
                self.proxy = dbus.Interface(obj, 'com.qmk.LayerIndicator')
                print("GNOME indicator bridge: Connected via D-Bus")
            except Exception as e:
                print(f"GNOME indicator bridge: Failed to connect - {e}")

    def update_layer(self, layer_name: str, layer_color: str):
        """Send layer update to GNOME Shell extension"""
        if self.use_socket:
            if not self.sock:
                # Try to establish connection
                try:
                    self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self.sock.connect(self.SOCKET_PATH)
                    print("GNOME indicator: Connected to bridge")
                except Exception as e:
                    print(f"GNOME indicator: Failed to connect - {e}")
                    return

            # Send via Unix socket
            try:
                message = f"{layer_name}:{layer_color}\n"
                self.sock.sendall(message.encode('utf-8'))
            except (BrokenPipeError, OSError, ConnectionResetError) as e:
                # Connection lost, try to reconnect once
                print(f"GNOME indicator: Connection lost, reconnecting...")
                try:
                    self.sock.close()
                except:
                    pass
                try:
                    self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self.sock.connect(self.SOCKET_PATH)
                    message = f"{layer_name}:{layer_color}\n"
                    self.sock.sendall(message.encode('utf-8'))
                    print(f"GNOME indicator: Reconnected")
                except Exception as e2:
                    print(f"GNOME indicator: Reconnection failed - {e2}")
                    self.sock = None
        elif self.proxy:
            # Send via D-Bus
            try:
                self.proxy.SetLayer(layer_name, layer_color)
            except Exception as e:
                print(f"GNOME indicator: D-Bus error - {e}")


class KeyboardOverlay(QWidget):
    """Semi-transparent overlay window showing keyboard layout"""

    def __init__(self, keyboard, rows: int, cols: int, x: int = 0, y: int = 0):
        super().__init__()
        self.keyboard = keyboard
        self.rows = rows
        self.cols = cols
        self.window_x = x
        self.window_y = y
        self.is_split = (rows % 2 == 0) and rows >= 8
        self.rows_per_half = rows // 2 if self.is_split else rows

        # Layer data
        self.all_layers = []
        self.current_layer = 0
        self.default_layer = 0
        self.active_layer_stack = {}

        # Layer info (same as in list_via_keyboards_usb.py)
        self.layer_info = {
            0: {"name": "Base", "color": "WHITE"},
            1: {"name": "Game", "color": "CYAN"},
            2: {"name": "Lower", "color": "RED"},
            3: {"name": "Raise", "color": "BLUE"},
            4: {"name": "Adjust", "color": "GREEN"},
            5: {"name": "Mouse", "color": "ORANGE"},
            6: {"name": "Extra", "color": "MAGENTA"},
        }

        # Qt colors
        self.qt_colors = {
            "WHITE": QColor(120, 120, 120),  # Darker gray instead of bright white
            "CYAN": QColor(0, 255, 255),
            "RED": QColor(255, 50, 50),
            "BLUE": QColor(100, 150, 255),
            "GREEN": QColor(80, 220, 80),  # Softer green - between bright and muted
            "ORANGE": QColor(255, 165, 0),
            "MAGENTA": QColor(255, 0, 255),
        }

        # Boblight colors - fully saturated for LED display
        self.boblight_colors = {
            "WHITE": QColor(120, 120, 120),
            "CYAN": QColor(0, 255, 255),
            "RED": QColor(255, 0, 0),        # Pure red
            "BLUE": QColor(0, 0, 255),       # Pure blue instead of light blue
            "GREEN": QColor(0, 255, 0),      # Pure green
            "ORANGE": QColor(255, 128, 0),   # Bright orange
            "MAGENTA": QColor(255, 0, 255),
        }

        # GUI state
        self.interactive_mode = False
        self.key_labels = []
        self.drag_position = None
        self.on_top_timer = None  # Timer for auto-return to bottom
        self.reloading_layers = False  # Flag to prevent updates during layer reload

        # Boblight integration (set later by main)
        self.boblight = None
        self.boblight_refresh_timer = None
        self.boblight_current_color = None

        # Boblight animation state
        self.boblight_anim_timer = None
        self.boblight_anim_step = 0
        self.boblight_anim_target_color = None
        self.boblight_anim_led_states = {}  # Per-LED current state: led_idx → (r, g, b) or None (use off)
        self.boblight_anim_fade_steps = 5  # frames to fade each LED from old to target
        self.boblight_anim_ring_delay = 2  # frames between activating successive rings

        # Home Assistant integration (set later by main)
        self.ha_client = None
        self.ha_color_enabled = False
        self.ha_saved_light_state = None  # Captured before layer color change
        self.ha_saved_light_time = 0  # Timestamp when state was saved
        self.ha_save_expiry = 1.0  # Seconds before saved state expires

        # MQTT layer-state publishing (set later by main)
        self.mqtt_client = None
        self.mqtt_enabled = False

        # Thread communication
        self.update_signal = LayerUpdateSignal()
        self.update_signal.layer_changed.connect(self.on_layer_changed)

        # X11 display for window manipulation
        self.xdisplay = None
        if XLIB_AVAILABLE:
            try:
                self.xdisplay = xlib_display.Display()
            except Exception as e:
                print(f"Warning: Could not connect to X11 display: {e}")
                self.xdisplay = None

        self.init_ui()

        # X11 properties will be set in showEvent after window is realized

    def showEvent(self, event):
        """Called when window is shown - set X11 properties here"""
        super().showEvent(event)
        # Apply X11 properties after window is fully realized
        QTimer.singleShot(100, self.setup_x11_properties)

    def init_ui(self):
        """Initialize the UI"""
        # Window properties
        self.setWindowTitle("Keyboard Overlay")
        # Start as bottom-most window (on desktop)
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.Tool
        )

        # Transparency
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(0.85)

        # Layout
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)  # Reduced top/bottom margins
        layout.setSpacing(3)  # Reduced spacing

        # Header: Layer info
        self.header_label = QLabel("Keyboard Overlay")
        self.header_label.setAlignment(Qt.AlignCenter)
        header_font = QFont("Monospace", 11, QFont.Bold)  # Smaller font
        self.header_label.setFont(header_font)
        self.header_label.setStyleSheet("background-color: rgba(0, 0, 0, 200); color: black; padding: 3px; border-radius: 3px;")  # Reduced padding
        layout.addWidget(self.header_label)

        # Keyboard grid
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(0)  # No spacing between keys
        self.grid_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        layout.addLayout(self.grid_layout)

        self.setLayout(layout)

        # Size and position - calculate based on key count
        if self.is_split:
            # Split keyboard: two halves side by side + separator (2px)
            width = (self.cols * 2) * 45 + 2 + 20
            height = self.rows_per_half * 30 + 50  # +50 for header only (removed info label)
        else:
            # Normal keyboard
            width = self.cols * 45 + 20
            height = self.rows * 30 + 50  # +50 for header only
        self.resize(width, height)
        self.move(self.window_x, self.window_y)

    def setup_x11_properties(self):
        """Setup X11 window properties for click-through and bottom placement"""
        if not self.xdisplay:
            return

        try:
            # Get X11 window ID
            window_id = self.winId().__int__()
            x11_window = self.xdisplay.create_resource_object('window', window_id)

            # Set window type to DESKTOP (appears below normal windows)
            atom_type = self.xdisplay.intern_atom('_NET_WM_WINDOW_TYPE')
            atom_desktop = self.xdisplay.intern_atom('_NET_WM_WINDOW_TYPE_DESKTOP')
            x11_window.change_property(atom_type, self.xdisplay.intern_atom('ATOM'), 32, [atom_desktop])

            # Set window state to BELOW (stays below other windows) and STICKY (all workspaces)
            atom_state = self.xdisplay.intern_atom('_NET_WM_STATE')
            atom_below = self.xdisplay.intern_atom('_NET_WM_STATE_BELOW')
            atom_sticky = self.xdisplay.intern_atom('_NET_WM_STATE_STICKY')
            x11_window.change_property(atom_state, self.xdisplay.intern_atom('ATOM'), 32, [atom_below, atom_sticky])

            self.xdisplay.sync()

            # Lower window to bottom of stack
            x11_window.configure(stack_mode=X.Below)
            self.xdisplay.sync()

            # Enable click-through by default
            self.set_click_through(True)

        except Exception as e:
            print(f"Warning: Could not set X11 properties: {e}")

    def set_click_through(self, enabled: bool):
        """Enable or disable click-through using X11 shape extension"""
        if not self.xdisplay:
            return

        try:
            window_id = self.winId().__int__()
            x11_window = self.xdisplay.create_resource_object('window', window_id)

            if enabled:
                # Empty input region = click-through
                x11_window.shape_rectangles(shape.SO.Set, shape.SK.Input, 0, 0, 0, [])
            else:
                # Full window region = normal input
                geom = x11_window.get_geometry()
                rect = (0, 0, geom.width, geom.height)
                x11_window.shape_rectangles(shape.SO.Set, shape.SK.Input, 0, 0, 0, [rect])

            self.xdisplay.sync()

        except Exception as e:
            print(f"Warning: Could not set click-through: {e}")
            import traceback
            traceback.print_exc()

    def set_window_on_top(self, on_top: bool):
        """Toggle window stacking order between bottom-most and top-most"""
        if not self.xdisplay:
            return

        # Cancel any existing timer
        if self.on_top_timer:
            self.on_top_timer.stop()
            self.on_top_timer = None

        try:
            window_id = self.winId().__int__()
            x11_window = self.xdisplay.create_resource_object('window', window_id)
            root = self.xdisplay.screen().root

            # Get atoms
            atom_state = self.xdisplay.intern_atom('_NET_WM_STATE')
            atom_above = self.xdisplay.intern_atom('_NET_WM_STATE_ABOVE')
            atom_below = self.xdisplay.intern_atom('_NET_WM_STATE_BELOW')

            if on_top:
                # Remove BELOW, add ABOVE
                # Remove BELOW
                event = Xlib.protocol.event.ClientMessage(
                    window=x11_window,
                    client_type=atom_state,
                    data=(32, [0, atom_below, 0, 1, 0])  # 0 = _NET_WM_STATE_REMOVE
                )
                root.send_event(event, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)

                # Add ABOVE
                event = Xlib.protocol.event.ClientMessage(
                    window=x11_window,
                    client_type=atom_state,
                    data=(32, [1, atom_above, 0, 1, 0])  # 1 = _NET_WM_STATE_ADD
                )
                root.send_event(event, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)

                # Also raise the window
                x11_window.configure(stack_mode=X.Above)

                # Set timer to return to bottom after 10 seconds
                self.on_top_timer = QTimer()
                self.on_top_timer.setSingleShot(True)
                self.on_top_timer.timeout.connect(lambda: self.set_window_on_top(False))
                self.on_top_timer.start(10000)  # 10 seconds
            else:
                # Remove ABOVE, add BELOW
                # Remove ABOVE
                event = Xlib.protocol.event.ClientMessage(
                    window=x11_window,
                    client_type=atom_state,
                    data=(32, [0, atom_above, 0, 1, 0])  # 0 = _NET_WM_STATE_REMOVE
                )
                root.send_event(event, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)

                # Add BELOW
                event = Xlib.protocol.event.ClientMessage(
                    window=x11_window,
                    client_type=atom_state,
                    data=(32, [1, atom_below, 0, 1, 0])  # 1 = _NET_WM_STATE_ADD
                )
                root.send_event(event, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)

                # Also lower the window
                x11_window.configure(stack_mode=X.Below)

            self.xdisplay.sync()

        except Exception as e:
            print(f"Warning: Could not change window stacking: {e}")
            import traceback
            traceback.print_exc()

    def create_keyboard_grid(self):
        """Create the keyboard key grid"""
        # Clear existing widgets
        for label in self.key_labels:
            label.deleteLater()
        self.key_labels.clear()

        # Get current layer keys
        if not self.all_layers or self.current_layer >= len(self.all_layers):
            return

        layer_keys = self.all_layers[self.current_layer]

        if self.is_split:
            # Split keyboard layout - left and right halves side by side
            # Left half
            for row in range(self.rows_per_half):
                for col in range(self.cols):
                    idx = row * self.cols + col
                    keycode = layer_keys[idx] if idx < len(layer_keys) else 0
                    key_label = self.create_key_widget(keycode, idx)
                    self.grid_layout.addWidget(key_label, row, col)
                    self.key_labels.append(key_label)

            # Add vertical separator line between halves
            for row in range(self.rows_per_half):
                separator = QLabel()
                separator.setFixedSize(2, 30)  # Thin vertical line
                separator.setStyleSheet("background-color: rgba(100, 100, 100, 150);")
                self.grid_layout.addWidget(separator, row, self.cols)
                self.key_labels.append(separator)

            # Right half (reversed columns) - same rows, offset columns
            for row in range(self.rows_per_half, self.rows):
                for col in range(self.cols):
                    idx = row * self.cols + col
                    keycode = layer_keys[idx] if idx < len(layer_keys) else 0
                    key_label = self.create_key_widget(keycode, idx)
                    # Reverse column order for right half and offset by cols+1 for separator
                    display_col = (self.cols - 1 - col) + self.cols + 1
                    display_row = row - self.rows_per_half  # Same row as left
                    self.grid_layout.addWidget(key_label, display_row, display_col)
                    self.key_labels.append(key_label)
        else:
            # Normal keyboard layout
            for row in range(self.rows):
                for col in range(self.cols):
                    idx = row * self.cols + col
                    keycode = layer_keys[idx] if idx < len(layer_keys) else 0
                    key_label = self.create_key_widget(keycode, idx)
                    self.grid_layout.addWidget(key_label, row, col)
                    self.key_labels.append(key_label)

    def create_key_widget(self, keycode: int, key_idx: int = -1) -> QLabel:
        """Create a widget for a single key"""
        is_transparent = (keycode == 0x0001)  # KC_TRNS
        display_keycode = keycode

        # For transparent keys, find the actual key from lower layers
        if is_transparent and key_idx >= 0 and self.current_layer > 0:
            # Look down through layers until we find a non-transparent key
            for layer in range(self.current_layer - 1, -1, -1):
                # Check if layers are loaded and layer exists
                if layer < len(self.all_layers) and key_idx < len(self.all_layers[layer]):
                    lower_keycode = self.all_layers[layer][key_idx]
                    if lower_keycode != 0x0001:  # Not transparent
                        display_keycode = lower_keycode
                        break

        key_name = self.keyboard.keycode_to_name(display_keycode)

        # Check if this is a simple modifier key (LCTL(KC_A), etc - range 0x0100-0x1FFF)
        is_simple_mod = 0x0100 <= display_keycode <= 0x1FFF

        # Check if this is a Mod-Tap key
        is_mod_tap = 0x2000 <= display_keycode <= 0x3FFF
        mt_mod_color = None

        # Check for QMK shifted keycodes (0x7C1A = LSFT+9, 0x7C1B = LSFT+0)
        is_qmk_shifted = display_keycode in [0x7C1A, 0x7C1B]

        # Check for mouse keys (0x00CD - 0x00DF range)
        is_mouse_key = 0x00CD <= display_keycode <= 0x00DF

        if is_mouse_key:
            # Mouse movement and button keys
            mouse_keys = {
                0x00CD: '↑',      # MS_UP
                0x00CE: '↓',      # MS_DOWN
                0x00CF: '←',      # MS_LEFT
                0x00D0: '→',      # MS_RIGHT
                0x00D1: 'M1',     # MS_BTN1
                0x00D2: 'M2',     # MS_BTN2
                0x00D3: 'M3',     # MS_BTN3
                0x00D4: 'M4',     # MS_BTN4
                0x00D5: 'M5',     # MS_BTN5
                0x00D6: 'W↑',     # MS_WH_UP (wheel up)
                0x00D7: 'W↓',     # MS_WH_DOWN (wheel down)
                0x00D8: 'W←',     # MS_WH_LEFT (wheel left)
                0x00D9: 'W↑',     # (wheel up duplicate?)
                0x00DA: 'W↓',     # (wheel down duplicate?)
                0x00DB: 'W←',     # (wheel left duplicate?)
                0x00DC: 'W→',     # MS_WH_RIGHT (wheel right)
            }
            key_name = mouse_keys.get(display_keycode, f'MS_{display_keycode:02X}')
        elif is_simple_mod:
            # Simple modifier keys like LCTL(KC_A) - range 0x0100-0x1FFF
            # Format: 0x0M00 | keycode where M is modifier bits
            mods = (display_keycode >> 8) & 0x1F
            kc = display_keycode & 0xFF

            # Get the base key name
            base_key = self.keyboard.keycode_to_name(kc)
            if base_key.startswith("KC_"):
                base_key = base_key[3:]

            # Convert to single character if possible
            char_map = {
                'A': 'A', 'B': 'B', 'C': 'C', 'D': 'D', 'E': 'E', 'F': 'F', 'G': 'G',
                'H': 'H', 'I': 'I', 'J': 'J', 'K': 'K', 'L': 'L', 'M': 'M', 'N': 'N',
                'O': 'O', 'P': 'P', 'Q': 'Q', 'R': 'R', 'S': 'S', 'T': 'T', 'U': 'U',
                'V': 'V', 'W': 'W', 'X': 'X', 'Y': 'Y', 'Z': 'Z',
                'LBRC': '[', 'RBRC': ']', 'SCLN': ';', 'SLSH': '/',
                'QUOT': "'", 'GRV': '`', 'COMM': ',', 'DOT': '.',
                'MINS': '-', 'EQL': '=', 'BSLS': '\\',
            }
            base_key = char_map.get(base_key, base_key)

            # Build modifier prefix
            prefix = ''
            if mods & 0x01:  # LCTL
                prefix += '⌃'
            if mods & 0x02:  # LSFT
                prefix += '⇧'
            if mods & 0x04:  # LALT
                prefix += '⌥'
            if mods & 0x08:  # LGUI
                prefix += '⌘'

            key_name = f"{prefix}{base_key}"
        elif is_qmk_shifted:
            # These are special QMK shifted keys
            mt_mod_color = QColor(20, 80, 20)  # Even darker green like LSFT
            if display_keycode == 0x7C1A:
                key_name = '('  # LSFT+9
            elif display_keycode == 0x7C1B:
                key_name = ')'  # LSFT+0
        elif is_mod_tap:
            # Extract modifier and base key
            mods = (display_keycode >> 8) & 0x1F
            kc = display_keycode & 0xFF

            # Determine color based on modifier
            if mods & 0x08:  # LGUI
                mt_mod_color = QColor(70, 60, 0)  # Even darker yellow
            elif mods & 0x04:  # LALT
                mt_mod_color = QColor(20, 40, 80)  # Even darker blue
            elif mods & 0x01:  # LCTL
                mt_mod_color = QColor(80, 20, 20)  # Even darker red
            elif mods & 0x02:  # LSFT
                mt_mod_color = QColor(20, 80, 20)  # Even darker green

            # Decode the base keycode properly using the keyboard's decoder
            key_name = self.keyboard.keycode_to_name(kc)
            # Remove KC_ prefix if present
            if key_name.startswith("KC_"):
                key_name = key_name[3:]

            # Replace key names with actual characters for MT keys
            char_map = {
                'LBRC': '[', 'RBRC': ']', 'SCLN': ';', 'SLSH': '/',
                'BSLS': '\\', 'COMM': ',', 'DOT': '.', 'QUOT': "'",
                'GRV': '`', 'MINS': '-', 'EQL': '=',
            }
            if key_name in char_map:
                key_name = char_map[key_name]
        else:
            # Shorten common key names
            if key_name.startswith("KC_"):
                key_name = key_name[3:]

            # Handle LSFT(KC_XXX) keys - extract the base key and show shifted version
            if key_name.startswith("LSFT(KC_") and key_name.endswith(")"):
                # Extract base key name: "LSFT(KC_SCLN)" -> "SCLN"
                base_key = key_name[8:-1]  # Remove "LSFT(KC_" and ")"

                # Map to character
                char_map = {
                    'LBRC': '[', 'RBRC': ']', 'SCLN': ';', 'SLSH': '/',
                    'BSLS': '\\', 'COMM': ',', 'DOT': '.', 'QUOT': "'",
                    'GRV': '`', 'MINS': '-', 'EQL': '=',
                }
                if base_key in char_map:
                    base_key = char_map[base_key]

                # Apply shift
                shifted_chars = {
                    ';': ':', '/': '?', '\\': '|', ',': '<', '.': '>',
                    "'": '"', '`': '~', '-': '_', '=': '+',
                    '[': '{', ']': '}',
                    '1': '!', '2': '@', '3': '#', '4': '$', '5': '%',
                    '6': '^', '7': '&', '8': '*', '9': '(', '0': ')',
                }
                if base_key in shifted_chars:
                    key_name = shifted_chars[base_key]
                elif len(base_key) == 1 and base_key.islower():
                    key_name = base_key.upper()
                else:
                    key_name = base_key  # Keep as-is if no shift mapping

            # Replace MO(X) with layer name
            elif key_name.startswith("MO(") and key_name.endswith(")"):
                try:
                    layer_num = int(key_name[3:-1])
                    if layer_num in self.layer_info:
                        key_name = self.layer_info[layer_num]["name"]
                except ValueError:
                    pass  # Keep original if parsing fails

            # Replace DF(X) with layer name to show default layer set
            elif key_name.startswith("DF(") and key_name.endswith(")"):
                try:
                    layer_num = int(key_name[3:-1])
                    if layer_num in self.layer_info:
                        key_name = self.layer_info[layer_num]["name"]
                except ValueError:
                    pass  # Keep original if parsing fails

            # Replace key names with actual characters
            char_map = {
                'LBRC': '[',
                'RBRC': ']',
                'SCLN': ';',
                'SLSH': '/',
                'BSLS': '\\',
                'COMM': ',',
                'DOT': '.',
                'QUOT': "'",
                'GRV': '`',
                'MINS': '-',
                'EQL': '=',
                'QK_GESC': 'ESC~',
            }
            if key_name in char_map:
                key_name = char_map[key_name]

            # Improve RGB key display names - handle RGB(0xXX) format
            if key_name.startswith('RGB(0x') and key_name.endswith(')'):
                # Extract the hex value: "RGB(0x22)" -> "22"
                rgb_hex = key_name[6:-1]
                rgb_code = int(rgb_hex, 16)

                rgb_map = {
                    0x20: 'RGB⏻',     # RGB_TOG - Toggle
                    0x21: 'RGB▶',     # RGB_MOD - Mode next
                    0x22: 'RGB◀',     # RGB_RMOD - Mode previous
                    0x23: 'H+',       # RGB_HUI - Hue increase
                    0x24: 'H-',       # RGB_HUD - Hue decrease
                    0x25: 'S+',       # RGB_SAI - Saturation increase
                    0x26: 'S-',       # RGB_SAD - Saturation decrease
                    0x27: 'V+',       # RGB_VAI - Value/brightness increase
                    0x28: 'V-',       # RGB_VAD - Value/brightness decrease
                    0x29: 'SPD+',     # RGB_SPI - Speed increase
                    0x2A: 'SPD-',     # RGB_SPD - Speed decrease
                }
                if rgb_code in rgb_map:
                    key_name = rgb_map[rgb_code]

        # Make it shorter for display
        if len(key_name) > 8:
            key_name = key_name[:7] + "…"

        label = QLabel(key_name)
        label.setAlignment(Qt.AlignCenter)
        label.setFont(QFont("Monospace", 7))  # Smaller font
        label.setFixedSize(45, 30)  # Fixed size
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)  # Don't expand

        # Style based on key type
        bg_color = QColor(30, 30, 30)  # Darker default
        text_color = QColor(200, 200, 200)

        # Mod-Tap keys get color based on modifier
        if mt_mod_color:
            bg_color = mt_mod_color
            text_color = QColor(255, 255, 255)  # White text for contrast
        # Layer switching keys get special colors
        elif 0x5220 <= keycode <= 0x523F:  # MO keys
            bg_color = QColor(30, 60, 90)  # Darker blue
        elif 0x5240 <= keycode <= 0x525F:  # DF keys
            bg_color = QColor(90, 60, 30)  # Darker orange
        elif 0x5260 <= keycode <= 0x527F:  # TG keys
            bg_color = QColor(60, 90, 30)  # Darker green
        elif keycode == 0x0000:  # KC_NO
            bg_color = QColor(20, 20, 20)
            text_color = QColor(80, 80, 80)
        elif is_transparent:  # KC_TRNS - keep distinct style but show actual key
            bg_color = QColor(60, 60, 80)
            text_color = QColor(150, 150, 200)

        label.setStyleSheet(f"""
            background-color: rgba({bg_color.red()}, {bg_color.green()}, {bg_color.blue()}, 180);
            color: rgb({text_color.red()}, {text_color.green()}, {text_color.blue()});
            border: 1px solid rgba(100, 100, 100, 100);
            border-radius: 2px;
            padding: 0px;
            margin: 0px;
        """)

        return label

    def update_header(self):
        """Update the header with layer info"""
        layer_name = self.layer_info.get(self.current_layer, {}).get("name", f"Layer{self.current_layer}")
        layer_color_name = self.layer_info.get(self.current_layer, {}).get("color", "WHITE")
        layer_color = self.qt_colors.get(layer_color_name, QColor(255, 255, 255))

        header_text = f"LAYER {self.current_layer}: {layer_name}"

        if self.active_layer_stack:
            stack_str = ', '.join([f"{key_type}({layer})" for layer, key_type in sorted(self.active_layer_stack.items(), reverse=True)])
            header_text += f" | Stack: {stack_str}"

        # Add interactive mode indicator
        if self.interactive_mode:
            header_text += " | [INTERACTIVE]"
            # Use bright magenta/purple background when interactive (distinct from all layers)
            header_color = QColor(200, 0, 200)
        else:
            # Use layer color when not interactive
            header_color = layer_color

        self.header_label.setText(header_text)
        self.header_label.setStyleSheet(f"""
            background-color: rgba({header_color.red()}, {header_color.green()}, {header_color.blue()}, 200);
            color: black;
            padding: 5px;
            border-radius: 3px;
            font-weight: bold;
        """)

    def _qcolor_to_hex(self, color: QColor) -> str:
        """Convert QColor to hex string for D-Bus"""
        return f'#{color.red():02x}{color.green():02x}{color.blue():02x}'

    def on_layer_changed(self, layer_num: int, layer_stack: dict, default_layer: int):
        """Called when layer changes (from USB monitoring thread)"""
        # Skip updates if we're reloading layers
        if self.reloading_layers:
            return

        self.current_layer = layer_num
        self.active_layer_stack = layer_stack
        self.default_layer = default_layer

        self.update_header()
        self.create_keyboard_grid()

        # Update GNOME indicator if available
        if hasattr(self, 'gnome_bridge') and self.gnome_bridge:
            layer_name = self.layer_info.get(layer_num, {}).get("name", f"Layer{layer_num}")
            layer_color_name = self.layer_info.get(layer_num, {}).get("color", "WHITE")
            layer_color_hex = self._qcolor_to_hex(self.qt_colors[layer_color_name])
            self.gnome_bridge.update_layer(layer_name, layer_color_hex)

        # Update Home Assistant light color if enabled
        if self.ha_color_enabled and self.ha_client:
            if layer_num == 0:
                # Returning to base layer - restore the most recently active
                # light mode (scene, sun-following, dark, etc.)
                if self.ha_saved_light_state is not None:
                    self.ha_client.restore_light_mode()
                    self.ha_saved_light_state = None
            else:
                # Non-base layer - save current state only if not already saved
                # or if the saved state has expired (default 1 second)
                now = time.time()
                if (self.ha_saved_light_state is None or
                        now - self.ha_saved_light_time > self.ha_save_expiry):
                    self.ha_saved_light_state = self.ha_client.get_light_color_state()
                    self.ha_saved_light_time = now

                layer_color_name = self.layer_info.get(layer_num, {}).get("color", "WHITE")
                color = self.boblight_colors.get(layer_color_name, QColor(255, 255, 255))
                self.ha_client.set_light_color(color.red(), color.green(), color.blue())

        # Publish layer state to MQTT for Home Assistant to react to
        if self.mqtt_enabled and self.mqtt_client:
            layer_name = self.layer_info.get(layer_num, {}).get("name", f"Layer{layer_num}")
            layer_color_name = self.layer_info.get(layer_num, {}).get("color", "WHITE")
            color = self.boblight_colors.get(layer_color_name, QColor(255, 255, 255))
            self.mqtt_client.publish_layer_state(
                layer_num=layer_num,
                layer_name=layer_name,
                color_name=layer_color_name,
                color_hex=self._qcolor_to_hex(color),
                is_base_layer=(layer_num == 0),
            )

        # Update boblight if available
        # Strategy: Stay connected, use 'set light <name> use on/off' for per-LED transparency
        if hasattr(self, 'boblight') and self.boblight:
            print(f"[BOBLIGHT] Layer changed to {layer_num}")

            # Ensure connected (should be from startup)
            if not self.boblight.connected:
                print(f"[BOBLIGHT] Not connected, connecting...")
                if not self.boblight.connect():
                    print(f"[BOBLIGHT] Failed to connect")
                    return

            # Stop any existing timers
            if self.boblight_refresh_timer:
                self.boblight_refresh_timer.stop()
                self.boblight_refresh_timer = None
            if self.boblight_anim_timer:
                self.boblight_anim_timer.stop()
                self.boblight_anim_timer = None

            if layer_num == 0:
                # Base layer - animate LEDs off from edges inward at 2x speed
                self.boblight_current_color = None
                self.boblight_anim_target_color = None  # None = fade to off
                self.boblight_anim_step = 0
                self.boblight_anim_timer = QTimer()
                self.boblight_anim_timer.timeout.connect(self._boblight_animate_step)
                self.boblight_anim_timer.start(25)  # 25ms per frame = 40Hz
                print(f"[BOBLIGHT] Starting fade-out animation")
            else:
                # Set layer-specific vibrant color
                layer_color_name = self.layer_info.get(layer_num, {}).get("color", "WHITE")
                color = self.boblight_colors.get(layer_color_name, QColor(255, 255, 255))
                print(f"[BOBLIGHT] Setting color {layer_color_name}: RGB({color.red()}, {color.green()}, {color.blue()})")

                # boblight_anim_led_states already holds the current per-LED state
                # (from a previous animation or steady state). This is used as the
                # "from" state for each LED individually - preserving mid-animation
                # states, fully-on LEDs, and use-off LEDs correctly.

                # Store current color for refresh timer (used after animation completes)
                self.boblight_current_color = color

                # Start spread-from-center animation (LEDs activated via use on/off)
                self.boblight_anim_target_color = color
                self.boblight_anim_step = 0
                self.boblight_anim_timer = QTimer()
                self.boblight_anim_timer.timeout.connect(self._boblight_animate_step)
                self.boblight_anim_timer.start(25)  # 25ms per frame = 40Hz
                print(f"[BOBLIGHT] Starting spread animation")
        else:
            print(f"[BOBLIGHT] Boblight not available")

    def _boblight_animate_step(self):
        """Animate LEDs with spread-from-center (fade-in) or collapse-to-center (fade-out)."""
        if not self.boblight or not self.boblight.connected:
            return

        fading_out = self.boblight_anim_target_color is None
        color = self.boblight_anim_target_color

        # Apply Home Assistant brightness scaling
        ha_scale = 1.0
        if hasattr(self, 'ha_client') and self.ha_client:
            ha_scale = self.ha_client.brightness_scale

        # Determine which LEDs we control
        if self.boblight.led_indices is not None:
            led_list = self.boblight.led_indices
        else:
            led_list = list(range(self.boblight.num_lights))

        num_leds = len(led_list)
        center = num_leds // 2
        max_ring = (num_leds - 1) // 2

        if fading_out:
            # Fade-out: 2x speed, edges inward
            fade_steps = max(1, self.boblight_anim_fade_steps // 2)
            ring_delay = max(1, self.boblight_anim_ring_delay // 2)
        else:
            # Fade-in: normal speed, center outward
            fade_steps = self.boblight_anim_fade_steps
            ring_delay = self.boblight_anim_ring_delay

        # Animation is done when the last ring has fully transitioned
        total_frames = max_ring * ring_delay + fade_steps

        # Calculate per-LED color for this frame
        lit_leds = {}
        for i, led_idx in enumerate(led_list):
            # Distance from center (ring number)
            ring = abs(i - center)

            if fading_out:
                # Edges first: invert ring order (outermost = ring 0, center = max_ring)
                anim_ring = max_ring - ring
            else:
                # Center first
                anim_ring = ring

            # Frame at which this ring starts its transition
            ring_start = anim_ring * ring_delay

            # How far into the fade are we?
            fade_progress = self.boblight_anim_step - ring_start

            # This LED's current "from" state (may be None = use off)
            from_rgb = self.boblight_anim_led_states.get(led_idx)

            if fade_progress < 0:
                # Not started yet - keep current state
                if from_rgb is not None:
                    lit_leds[led_idx] = from_rgb
                continue

            if fade_progress >= fade_steps:
                t = 1.0
            else:
                t = (fade_progress / fade_steps) ** 2  # Quadratic ease-in

            if fading_out:
                # Fade from current color to off (use off)
                if from_rgb is not None and t < 1.0:
                    fr, fg, fb = from_rgb
                    r = fr * (1.0 - t)
                    g = fg * (1.0 - t)
                    b = fb * (1.0 - t)
                    rgb = (r, g, b)
                    lit_leds[led_idx] = rgb
                    self.boblight_anim_led_states[led_idx] = rgb
                else:
                    # Fully faded out - release this LED
                    self.boblight_anim_led_states.pop(led_idx, None)
                    # Don't add to lit_leds → will get 'use off'
            else:
                # Fade-in / cross-fade to target color
                tr = color.red() / 255.0 * ha_scale
                tg = color.green() / 255.0 * ha_scale
                tb = color.blue() / 255.0 * ha_scale

                if from_rgb is not None:
                    fr, fg, fb = from_rgb
                    r = fr * (1.0 - t) + tr * t
                    g = fg * (1.0 - t) + tg * t
                    b = fb * (1.0 - t) + tb * t
                else:
                    r = tr * t
                    g = tg * t
                    b = tb * t

                rgb = (r, g, b)
                lit_leds[led_idx] = rgb
                self.boblight_anim_led_states[led_idx] = rgb

        self.boblight.set_per_led_with_use(lit_leds, led_list)

        self.boblight_anim_step += 1

        # Animation complete
        if self.boblight_anim_step > total_frames:
            self.boblight_anim_timer.stop()
            self.boblight_anim_timer = None

            if fading_out:
                # All LEDs released
                self.boblight.set_all_use(False)
                self.boblight_anim_led_states = {}
            else:
                self.boblight_anim_target_color = None

                # Ensure all controlled LEDs are 'use on' for steady state
                self.boblight.set_all_use(True)

                # Start normal refresh timer to maintain color against boblight-X11
                self.boblight_refresh_timer = QTimer()
                self.boblight_refresh_timer.timeout.connect(self.refresh_boblight_color)
                self.boblight_refresh_timer.start(25)

    def refresh_boblight_color(self):
        """Periodically refresh boblight color to override boblight-X11"""
        if hasattr(self, 'boblight') and self.boblight and self.boblight_current_color:
            color = self.boblight_current_color

            # Apply Home Assistant brightness scaling if HA client is available
            ha_scale = 1.0
            if hasattr(self, 'ha_client') and self.ha_client:
                ha_scale = self.ha_client.brightness_scale

            scaled_color = QColor(
                int(color.red() * ha_scale),
                int(color.green() * ha_scale),
                int(color.blue() * ha_scale)
            )
            self.boblight.set_color_from_qcolor(scaled_color)

            # Keep per-LED state in sync for potential mid-refresh animation start
            rgb = (color.red() / 255.0 * ha_scale, color.green() / 255.0 * ha_scale, color.blue() / 255.0 * ha_scale)
            if self.boblight.led_indices is not None:
                for idx in self.boblight.led_indices:
                    self.boblight_anim_led_states[idx] = rgb
            else:
                for idx in range(self.boblight.num_lights):
                    self.boblight_anim_led_states[idx] = rgb

    def set_interactive(self, interactive: bool):
        """Toggle interactive mode"""
        if self.interactive_mode == interactive:
            return

        self.interactive_mode = interactive

        # Use X11 shape extension for click-through if available
        if self.xdisplay:
            self.set_click_through(not interactive)
        else:
            # Fallback to Qt attribute if xlib not available
            if interactive:
                self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            else:
                self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # Update header to show/hide interactive mode indicator
        self.update_header()

    def load_layers(self):
        """Load all layers from keyboard"""
        self.reloading_layers = True  # Pause layer updates during reload
        print("Loading keyboard layers...")

        # Clear existing layers
        self.all_layers = []

        total_keys = self.rows * self.cols * self.keyboard.layer_count
        total_bytes = total_keys * 2

        offset = 0
        keymap_data = bytearray()

        while offset < total_bytes:
            chunk_size = min(28, total_bytes - offset)

            response = self.keyboard.send_command(via.CMD_GET_KEYMAP_BUFFER, [
                (offset >> 8) & 0xFF,
                offset & 0xFF,
                chunk_size
            ])

            if response and response[0] == via.CMD_GET_KEYMAP_BUFFER:
                keymap_data.extend(response[4:4+chunk_size])
            else:
                print(f"Failed to read keymap at offset {offset}")
                break

            offset += chunk_size

        # Verify we got all the data
        if len(keymap_data) < total_bytes:
            print(f"Warning: Only received {len(keymap_data)} of {total_bytes} bytes - aborting layer load")
            # Don't proceed with partial data - it will cause issues
            self.all_layers = []
            self.reloading_layers = False
            return

        # Parse keycodes
        keycodes = []
        for i in range(0, len(keymap_data), 2):
            if i + 1 < len(keymap_data):
                keycode = (keymap_data[i] << 8) | keymap_data[i + 1]
                keycodes.append(keycode)

        # Split into layers
        keys_per_layer = self.rows * self.cols
        self.all_layers = []
        for layer in range(self.keyboard.layer_count):
            start_idx = layer * keys_per_layer
            end_idx = start_idx + keys_per_layer
            layer_keys = keycodes[start_idx:end_idx]
            self.all_layers.append(layer_keys)

        print(f"Loaded {len(self.all_layers)} layers")

        # Initial display
        self.update_header()
        self.create_keyboard_grid()

        self.reloading_layers = False  # Resume layer updates

    def on_keyboard_reconnected(self):
        """Called when keyboard is reconnected - reload layers in main thread"""
        print("Reloading keyboard layers after reconnection...")
        self.load_layers()

        if self.all_layers and len(self.all_layers) == self.keyboard.layer_count:
            print("Layer reload successful")
        else:
            print(f"Warning: Layer reload incomplete ({len(self.all_layers)} of {self.keyboard.layer_count} layers)")

    def mousePressEvent(self, event):
        """Handle mouse press for dragging window"""
        if self.interactive_mode and event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """Handle mouse move for dragging window"""
        if self.interactive_mode and event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_position)
            event.accept()


class HotkeyMonitor(threading.Thread):
    """Monitor global hotkeys using X11"""

    def __init__(self, overlay: KeyboardOverlay):
        super().__init__(daemon=True)
        self.overlay = overlay
        self.running = True
        self.display = None

        # Create signal for thread-safe communication
        self.interactive_signal = InteractiveSignal()
        self.interactive_signal.interactive_changed.connect(overlay.set_interactive)

        if not XLIB_AVAILABLE:
            print("Warning: Hotkey monitoring disabled (python-xlib not available)")
            return

        try:
            self.display = xlib_display.Display()
            self.root = self.display.screen().root

            # Grab the hotkey combination: Ctrl+Shift+Alt
            self.modifiers = X.ControlMask | X.ShiftMask | X.Mod1Mask

        except Exception as e:
            print(f"Warning: Could not initialize hotkey monitor: {e}")
            self.display = None

    def run(self):
        """Monitor keyboard state for hotkey"""
        if not self.display:
            return

        last_interactive = False

        # We'll poll the keyboard state instead of grabbing keys
        # This is less intrusive and works better with the desktop environment
        while self.running:
            try:
                # Query keyboard state
                result = self.root.query_pointer()
                mask = result.mask

                # Check if Ctrl+Shift+Alt are all pressed
                ctrl_pressed = bool(mask & X.ControlMask)
                shift_pressed = bool(mask & X.ShiftMask)
                alt_pressed = bool(mask & X.Mod1Mask)

                interactive = ctrl_pressed and shift_pressed and alt_pressed

                # Emit signal on state change
                if interactive != last_interactive:
                    last_interactive = interactive
                    # Emit signal for thread-safe GUI update
                    self.interactive_signal.interactive_changed.emit(interactive)

                time.sleep(0.016)  # Poll at ~60Hz (was 0.05 = 20Hz)

            except Exception as e:
                print(f"Error in hotkey monitor: {e}")
                time.sleep(1)


class KeyboardMonitor(threading.Thread):
    """Monitor keyboard layer changes via USB"""

    def __init__(self, keyboard, overlay: KeyboardOverlay, rows: int, cols: int):
        super().__init__(daemon=True)
        self.keyboard = keyboard
        self.overlay = overlay
        self.rows = rows
        self.cols = cols
        self.running = True
        self.error_count = 0
        self.max_errors = 10  # Reconnect after 10 consecutive errors

        # Store keyboard identification for reconnection
        self.keyboard_vid = keyboard.device.idVendor
        self.keyboard_pid = keyboard.device.idProduct
        self.keyboard_name = keyboard.keyboard_name
        # Store bus and port numbers - these should remain stable across reconnects
        self.keyboard_bus = keyboard.device.bus
        try:
            self.keyboard_port_numbers = tuple(keyboard.device.port_numbers) if hasattr(keyboard.device, 'port_numbers') else None
        except:
            self.keyboard_port_numbers = None

        # Create signal for thread-safe interactive mode communication
        self.interactive_signal = InteractiveSignal()
        self.interactive_signal.interactive_changed.connect(overlay.set_interactive)

        # Create signal for thread-safe on-top mode communication
        self.on_top_signal = OnTopSignal()
        self.on_top_signal.on_top_changed.connect(overlay.set_window_on_top)

        # Create signal for thread-safe keyboard reconnection
        self.reconnect_signal = ReconnectSignal()
        self.reconnect_signal.reconnected.connect(overlay.on_keyboard_reconnected)

        # Layer state tracking
        self.current_layer = 0
        self.default_layer = 0
        self.active_layer_stack = {}
        self.pressed_keys = {}
        self.prev_state = [[False] * cols for _ in range(rows)]

        # Split keyboard configuration
        self.rows_per_half = rows // 2

        # Trigger keys on bottom row (last row of each half)
        # For crkbd (4 rows): row 3
        # For Sofle (5 rows): row 4
        bottom_row = self.rows_per_half - 1

        # Trigger key column depends on keyboard layout
        # Crkbd: column 4 (natural thumb resting position without rotary encoder)
        # Sofle: column 3 (natural thumb resting position)
        trigger_col = 4 if keyboard.keyboard_name == "Crkbd" else 3

        # Interactive mode trigger key (left half, bottom row)
        self.interactive_key_row = bottom_row
        self.interactive_key_col = trigger_col
        self.interactive_key_layer = 5
        self.interactive_key_pressed = False  # Track if interactive key is currently pressed

        # On-top mode trigger key (right half, bottom row)
        self.on_top_key_row = bottom_row + self.rows_per_half
        self.on_top_key_col = trigger_col
        self.on_top_key_layer = 4
        self.on_top_key_pressed = False  # Track if on-top key is currently pressed

    def reconnect_keyboard(self) -> bool:
        """Attempt to reconnect to the same keyboard after disconnection"""
        print(f"Attempting to reconnect to {self.keyboard_name} (VID:PID {self.keyboard_vid:04X}:{self.keyboard_pid:04X})...")

        # Close old keyboard handle
        try:
            self.keyboard.close()
        except Exception as e:
            print(f"Error closing old keyboard: {e}")

        # Scan for keyboards
        devices = via.find_via_keyboards(verbose=False)
        if not devices:
            print("No VIA-capable keyboards found")
            return False

        # Find matching keyboard by VID/PID, bus, and port numbers
        matching = []
        for d in devices:
            if d.idVendor != self.keyboard_vid or d.idProduct != self.keyboard_pid:
                continue

            # Match by bus number
            if d.bus != self.keyboard_bus:
                continue

            # If we have port numbers, also match by port numbers
            if self.keyboard_port_numbers:
                try:
                    device_ports = tuple(d.port_numbers) if hasattr(d, 'port_numbers') else None
                    if device_ports == self.keyboard_port_numbers:
                        matching.append(d)
                        break  # Found our specific keyboard
                except:
                    pass
            else:
                # No port numbers, but bus matches
                matching.append(d)
                break

        if not matching:
            if self.keyboard_port_numbers:
                print(f"Keyboard {self.keyboard_name} on bus {self.keyboard_bus} ports {self.keyboard_port_numbers} not found")
            else:
                print(f"Keyboard {self.keyboard_name} on bus {self.keyboard_bus} not found")
            return False

        # Open the keyboard
        device = matching[0]
        new_keyboard = via.ViaKeyboard(device)
        if not new_keyboard.open():
            print("Failed to open keyboard")
            return False

        # Detect keyboard type and query info
        new_keyboard.detect_keyboard_type()
        new_keyboard.query_info()

        # Verify matrix size was detected
        if not new_keyboard.matrix_rows or not new_keyboard.matrix_cols:
            print(f"Failed to detect keyboard matrix size")
            new_keyboard.close()
            return False

        # Verify it's the same keyboard
        if new_keyboard.matrix_rows != self.rows or new_keyboard.matrix_cols != self.cols:
            print(f"Warning: Matrix size changed from {self.rows}x{self.cols} to {new_keyboard.matrix_rows}x{new_keyboard.matrix_cols}")
            new_keyboard.close()
            return False

        # Success! Replace keyboard handle
        self.keyboard = new_keyboard
        self.overlay.keyboard = new_keyboard
        print(f"✓ Successfully reconnected to {self.keyboard_name}")

        # Reset layer state
        self.current_layer = 0
        self.default_layer = 0
        self.active_layer_stack = {}
        self.pressed_keys = {}

        # Pause monitoring while reloading layers to avoid USB command conflicts
        self.error_count = self.max_errors + 1

        # Signal the overlay to reload layers (thread-safe)
        self.reconnect_signal.reconnected.emit()

        # Wait for load_layers() to start and complete
        # Check the flag has been set to True (load started) then back to False (load done)
        timeout = 100  # 10 seconds max
        started = False
        while timeout > 0:
            if self.overlay.reloading_layers:
                started = True
            elif started and not self.overlay.reloading_layers:
                # Load has completed
                break
            time.sleep(0.1)
            timeout -= 1

        # Resume monitoring
        self.error_count = 0

        return True

    def run(self):
        """Monitor keyboard matrix for layer changes"""
        print("Keyboard monitor started")

        while self.running:
            try:
                # Read matrix state
                matrix_data = self.keyboard.get_matrix_state(self.rows, self.cols, verbose=False)
                if matrix_data is None:
                    self.error_count += 1
                    if self.error_count >= self.max_errors:
                        print("Too many USB errors, device may be disconnected. Attempting reconnection...")

                        # Keep trying to reconnect every 1 second
                        while self.running:
                            if self.reconnect_keyboard():
                                # Reconnection successful, reset error count and continue
                                self.error_count = 0
                                print("Resuming keyboard monitoring...")
                                break
                            else:
                                # Reconnection failed, wait 1 second and retry
                                time.sleep(1)
                    time.sleep(0.02)
                    continue

                # Reset error count on successful read
                self.error_count = 0

                current_state = self.keyboard.decode_matrix_state(matrix_data, self.rows, self.cols)

                # Detect changes
                layer_changed = False
                for row in range(self.rows):
                    for col in range(self.cols):
                        if current_state[row][col] != self.prev_state[row][col]:
                            pressed = current_state[row][col]
                            key_idx = row * self.cols + col

                            # Check for interactive mode trigger key
                            if row == self.interactive_key_row and col == self.interactive_key_col:
                                if pressed and self.current_layer == self.interactive_key_layer:
                                    # Activate interactive mode when pressed on layer 5
                                    self.interactive_key_pressed = True
                                    self.interactive_signal.interactive_changed.emit(True)
                                elif not pressed and self.interactive_key_pressed:
                                    # Deactivate interactive mode when released (regardless of layer)
                                    self.interactive_key_pressed = False
                                    self.interactive_signal.interactive_changed.emit(False)

                            # Check for on-top mode trigger key
                            if row == self.on_top_key_row and col == self.on_top_key_col:
                                if pressed and self.current_layer == self.on_top_key_layer:
                                    # Bring window to top when pressed on layer 4 (for 10 seconds)
                                    if not self.on_top_key_pressed:
                                        self.on_top_key_pressed = True
                                        self.on_top_signal.on_top_changed.emit(True)
                                elif not pressed and self.on_top_key_pressed:
                                    # Reset pressed state when released
                                    self.on_top_key_pressed = False

                            if pressed:
                                # Key pressed - check current layer
                                # Bounds check for layer data (may be reloading after reconnection)
                                if (self.current_layer < len(self.overlay.all_layers) and
                                    key_idx < len(self.overlay.all_layers[self.current_layer])):
                                    keycode = self.overlay.all_layers[self.current_layer][key_idx]
                                    self.pressed_keys[(row, col)] = keycode
                                else:
                                    keycode = 0x0000  # No-op if layers aren't loaded yet
                            else:
                                # Key released - use remembered keycode
                                keycode = self.pressed_keys.get((row, col), 0x0000)
                                if (row, col) in self.pressed_keys:
                                    del self.pressed_keys[(row, col)]

                            # Check for layer switching keys
                            if 0x5220 <= keycode <= 0x523F:  # MO keys
                                target_layer = keycode & 0x1F
                                if pressed:
                                    self.active_layer_stack[target_layer] = "MO"
                                    new_layer = max(self.active_layer_stack.keys())
                                    if new_layer != self.current_layer:
                                        self.current_layer = new_layer
                                        layer_changed = True
                                else:
                                    if target_layer in self.active_layer_stack:
                                        del self.active_layer_stack[target_layer]
                                    new_layer = max(self.active_layer_stack.keys()) if self.active_layer_stack else self.default_layer
                                    if new_layer != self.current_layer:
                                        self.current_layer = new_layer
                                        layer_changed = True

                            elif 0x5240 <= keycode <= 0x525F and pressed:  # DF keys
                                target_layer = keycode & 0x1F
                                self.default_layer = target_layer
                                if not self.active_layer_stack:
                                    self.current_layer = target_layer
                                    layer_changed = True

                            elif 0x5260 <= keycode <= 0x527F and pressed:  # TG keys
                                target_layer = keycode & 0x1F
                                if self.current_layer == target_layer:
                                    self.current_layer = 0
                                else:
                                    self.current_layer = target_layer
                                layer_changed = True

                if layer_changed:
                    # Send update to GUI (thread-safe)
                    self.overlay.update_signal.layer_changed.emit(
                        self.current_layer,
                        dict(self.active_layer_stack),
                        self.default_layer
                    )

                self.prev_state = current_state
                time.sleep(0.007)  # ~150Hz polling (was 0.02 = 50Hz, 3x faster)

            except Exception as e:
                print(f"Error in keyboard monitor: {e}")
                time.sleep(1)


def load_config(path: str) -> dict:
    """Load a YAML config file and return the raw parsed dict."""
    import yaml
    with open(path, 'r') as f:
        return yaml.safe_load(f) or {}


def apply_config_defaults(parser, config: dict):
    """
    Apply config.yaml values as argparse defaults.

    Only sets defaults for keys present in the config so that CLI arguments
    (parsed afterwards) still override, and built-in defaults remain for
    anything not specified in either config or CLI.
    """
    # --- overlay ---
    overlay = config.get('overlay', {}) or {}
    if 'x' in overlay:
        parser.set_defaults(x=overlay['x'])
    if 'y' in overlay:
        parser.set_defaults(y=overlay['y'])
    if 'keyboard' in overlay:
        parser.set_defaults(keyboard=str(overlay['keyboard']))

    # --- boblight ---
    boblight = config.get('boblight', {}) or {}
    if 'enabled' in boblight:
        parser.set_defaults(boblight=boblight['enabled'])
    if 'host' in boblight:
        parser.set_defaults(boblight_host=boblight['host'])
    if 'port' in boblight:
        parser.set_defaults(boblight_port=boblight['port'])
    if 'priority' in boblight:
        parser.set_defaults(boblight_priority=boblight['priority'])
    if 'leds' in boblight:
        leds = boblight['leds']
        # YAML list -> comma-separated string (matching CLI format)
        if isinstance(leds, list):
            parser.set_defaults(boblight_leds=','.join(str(l) for l in leds))
        else:
            parser.set_defaults(boblight_leds=str(leds))

    # --- home_assistant ---
    ha = config.get('home_assistant', {}) or {}
    if 'enabled' in ha:
        parser.set_defaults(ha=ha['enabled'])
    if 'url' in ha:
        parser.set_defaults(ha_url=ha['url'])
    if 'entity' in ha:
        parser.set_defaults(ha_entity=ha['entity'])
    if 'min_brightness' in ha:
        parser.set_defaults(ha_min_brightness=ha['min_brightness'])
    if 'poll_interval' in ha:
        parser.set_defaults(ha_poll_interval=ha['poll_interval'])

    # Token: env var takes precedence over config for security
    token = os.environ.get('HASS_TOKEN') or ha.get('token')
    if token:
        parser.set_defaults(ha_token=token)

    # Solar (nested under home_assistant)
    solar = ha.get('solar', {}) or {}
    if 'enabled' in solar:
        # CLI flag is --ha-no-solar (inverted), config key is solar.enabled
        parser.set_defaults(ha_no_solar=not solar['enabled'])
    if 'latitude' in solar:
        parser.set_defaults(ha_latitude=solar['latitude'])
    if 'longitude' in solar:
        parser.set_defaults(ha_longitude=solar['longitude'])

    # Color sync (nested under home_assistant)
    color = ha.get('color', {}) or {}
    if 'enabled' in color:
        parser.set_defaults(ha_color=color['enabled'])
    if 'entity' in color:
        parser.set_defaults(ha_color_entity=color['entity'])

    # --- mqtt ---
    mqtt_cfg = config.get('mqtt', {}) or {}
    if 'enabled' in mqtt_cfg:
        parser.set_defaults(mqtt=mqtt_cfg['enabled'])
    if 'host' in mqtt_cfg:
        parser.set_defaults(mqtt_broker=mqtt_cfg['host'])
    if 'port' in mqtt_cfg:
        parser.set_defaults(mqtt_port=mqtt_cfg['port'])
    if 'transport' in mqtt_cfg:
        parser.set_defaults(mqtt_transport=mqtt_cfg['transport'])
    if 'tls' in mqtt_cfg:
        parser.set_defaults(mqtt_tls=mqtt_cfg['tls'])
    if 'username' in mqtt_cfg:
        parser.set_defaults(mqtt_username=mqtt_cfg['username'])
    if 'device_id' in mqtt_cfg:
        parser.set_defaults(mqtt_device_id=mqtt_cfg['device_id'])

    # Password: env var takes precedence over config for security
    mqtt_password = os.environ.get('MQTT_PASSWORD') or mqtt_cfg.get('password')
    if mqtt_password:
        parser.set_defaults(mqtt_password=mqtt_password)


def main():
    """Main function"""
    import argparse

    # --- Phase 1: parse --config (and any unknown args) to find config path ---
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument('--config', type=str, default='config.yaml',
                           help='Path to YAML config file (default: config.yaml)')
    pre_args, _ = pre_parser.parse_known_args()

    # --- Phase 2: load config and apply as defaults ---
    config = {}
    try:
        config = load_config(pre_args.config)
        print(f"[CONFIG] Loaded configuration from {pre_args.config}")
    except FileNotFoundError:
        # Config file not found is fine - use CLI/built-in defaults only
        pass
    except Exception as e:
        print(f"[CONFIG] Warning: Error loading {pre_args.config}: {e}")
        print("[CONFIG] Continuing with command-line defaults only")

    # --- Phase 3: full argument parser with config-aware defaults ---
    parser = argparse.ArgumentParser(description="QMK Keyboard Overlay GUI")
    parser.add_argument('--config', type=str, default='config.yaml',
                        help='Path to YAML config file (default: config.yaml)')
    parser.add_argument('--keyboard', type=str, help='Keyboard selection: INDEX or VID:PID (e.g., 1 or FEED:6060)')
    parser.add_argument('--x', type=int, default=0, help='X position of window (default: 0)')
    parser.add_argument('--y', type=int, default=0, help='Y position of window (default: 0)')

    # Boblight integration arguments
    parser.add_argument('--boblight', action='store_true', help='Enable boblight integration')
    parser.add_argument('--boblight-host', type=str, default='localhost', help='Boblight server host (default: localhost)')
    parser.add_argument('--boblight-port', type=int, default=19333, help='Boblight server port (default: 19333)')
    parser.add_argument('--boblight-priority', type=int, default=100, help='Boblight priority (default: 100, LOWER = higher priority, 255 = disabled, boblight-X11 uses 128)')
    parser.add_argument('--boblight-leds', type=str, help='Comma-separated LED indices to control (e.g., "0,1,2,3,4,5"), omit for all LEDs')

    # Home Assistant integration arguments
    parser.add_argument('--ha', action='store_true', help='Enable Home Assistant brightness control')
    parser.add_argument('--ha-url', type=str, default='http://homeassistant.local:8123', help='Home Assistant base URL (default: http://homeassistant.local:8123, or set HASS_URL env var)')
    parser.add_argument('--ha-token', type=str, default=os.environ.get('HASS_TOKEN'), help='Home Assistant long-lived access token (default: HASS_TOKEN env var)')
    parser.add_argument('--ha-entity', type=str, default='light.velke_svetlo_v_obyvaku', help='Home Assistant light entity_id to monitor (default: light.velke_svetlo_v_obyvaku)')
    parser.add_argument('--ha-min-brightness', type=float, default=0.25, help='Minimum boblight brightness when light is off (0.0-1.0, default: 0.25)')
    parser.add_argument('--ha-poll-interval', type=float, default=5.0, help='Home Assistant polling interval in seconds (default: 5.0)')
    parser.add_argument('--ha-latitude', type=float, default=49.19, help='Latitude for solar calculations (default: 49.19 = Brno, CZ)')
    parser.add_argument('--ha-longitude', type=float, default=16.61, help='Longitude for solar calculations (default: 16.61 = Brno, CZ)')
    parser.add_argument('--ha-no-solar', action='store_true', help='Disable solar brightness calculations (use only Home Assistant light)')

    # Home Assistant color sync arguments
    parser.add_argument('--ha-color', action='store_true', help='Enable Home Assistant light color sync with keyboard layer')
    parser.add_argument('--ha-color-entity', type=str, default=None, help='Home Assistant light entity_id to control color on (default: same as --ha-entity)')

    # MQTT layer-state publishing arguments
    parser.add_argument('--mqtt', action='store_true', help='Publish keyboard layer state to MQTT for Home Assistant to react to')
    parser.add_argument('--mqtt-broker', type=str, default='homeassistant.local', help='MQTT broker host (default: homeassistant.local)')
    parser.add_argument('--mqtt-port', type=int, default=1883, help='MQTT broker port (default: 1883)')
    parser.add_argument('--mqtt-transport', type=str, default='tcp', choices=['tcp', 'websockets'], help='MQTT transport (default: tcp)')
    parser.add_argument('--mqtt-tls', action='store_true', help='Use TLS for the MQTT connection')
    parser.add_argument('--mqtt-username', type=str, default=None, help='MQTT broker username')
    parser.add_argument('--mqtt-password', type=str, default=os.environ.get('MQTT_PASSWORD'), help='MQTT broker password (default: MQTT_PASSWORD env var)')
    parser.add_argument('--mqtt-device-id', type=str, default='keyboard1', help='Device id used in MQTT topics, e.g. qmk/<device-id>/layer (default: keyboard1)')

    # Apply config.yaml values as defaults (CLI args will override these)
    if config:
        apply_config_defaults(parser, config)

    args = parser.parse_args()

    # Parse keyboard selection
    selected_keyboard_index = None
    selected_keyboard_vid = None
    selected_keyboard_pid = None

    if args.keyboard:
        if ':' in args.keyboard:
            vid_str, pid_str = args.keyboard.split(':')
            selected_keyboard_vid = int(vid_str, 16)
            selected_keyboard_pid = int(pid_str, 16)
        else:
            selected_keyboard_index = int(args.keyboard)

    # Parse boblight LED indices
    boblight_led_indices = None
    if args.boblight_leds:
        try:
            boblight_led_indices = [int(x.strip()) for x in args.boblight_leds.split(',')]
        except ValueError:
            print(f"Error: Invalid LED indices format: {args.boblight_leds}")
            return 1

    print("QMK Keyboard Overlay GUI")
    print("=" * 70)
    print()

    # Find keyboards
    print("Scanning for VIA-capable keyboards...")
    devices = via.find_via_keyboards(verbose=False)

    if not devices:
        print("\nNo VIA-capable keyboards found.")
        return 1

    # Filter by selection
    if selected_keyboard_index is not None:
        if selected_keyboard_index < 1 or selected_keyboard_index > len(devices):
            print(f"Error: Invalid keyboard index {selected_keyboard_index}")
            return 1
        devices = [devices[selected_keyboard_index - 1]]
    elif selected_keyboard_vid is not None and selected_keyboard_pid is not None:
        matching = [d for d in devices if d.idVendor == selected_keyboard_vid and d.idProduct == selected_keyboard_pid]
        if not matching:
            print(f"Error: No keyboard found with VID:PID {selected_keyboard_vid:04X}:{selected_keyboard_pid:04X}")
            return 1
        devices = matching

    if len(devices) > 1:
        print(f"\nFound {len(devices)} keyboards. Using first one.")
        print("Use --keyboard=INDEX to select a specific keyboard.")

    device = devices[0]

    # Open keyboard
    keyboard = via.ViaKeyboard(device)
    if not keyboard.open():
        print("Failed to open keyboard")
        return 1

    # Detect keyboard type
    keyboard.detect_keyboard_type()
    keyboard.query_info()

    rows = keyboard.matrix_rows
    cols = keyboard.matrix_cols

    if not rows or not cols:
        print("Error: Could not detect keyboard matrix size")
        return 1

    print(f"Detected: {keyboard.keyboard_name} ({rows}x{cols} matrix)")
    print()

    # Setup signal handler for Ctrl+C
    def signal_handler(sig, frame):
        print("\nShutting down...")
        QApplication.quit()

    signal.signal(signal.SIGINT, signal_handler)

    # Create Qt application
    app = QApplication(sys.argv)

    # Allow Ctrl+C to work by processing events periodically
    timer = QTimer()
    timer.start(500)  # Process events every 500ms
    timer.timeout.connect(lambda: None)

    # Create overlay window
    overlay = KeyboardOverlay(keyboard, rows, cols, args.x, args.y)
    overlay.show()

    # Setup GNOME Shell indicator bridge if available
    gnome_bridge = GnomeIndicatorBridge()
    overlay.gnome_bridge = gnome_bridge

    # Setup boblight integration if enabled
    boblight = None
    if args.boblight:
        if not BOBLIGHT_AVAILABLE:
            print("Error: Boblight integration requested but boblight_client module not available")
            return 1

        print(f"\n[BOBLIGHT] Initializing boblight integration...")
        boblight = boblight_client.BoblightClient(
            host=args.boblight_host,
            port=args.boblight_port,
            priority=args.boblight_priority,
            led_indices=boblight_led_indices
        )

        if boblight.connect():
            overlay.boblight = boblight
            print("[BOBLIGHT] Integration enabled")
        else:
            print("[BOBLIGHT] Warning: Failed to connect to boblight server, continuing without boblight")
            boblight = None
    overlay.boblight = boblight

    # Setup Home Assistant integration if enabled
    ha_client = None
    if args.ha:
        if not BOBLIGHT_AVAILABLE:
            print("Error: Home Assistant integration requested but boblight must also be enabled")
            return 1

        try:
            import homeassistant_client
            HA_AVAILABLE = True
        except ImportError:
            print("Error: Home Assistant integration requested but homeassistant_client module not available")
            print("Install with: pip install requests astral")
            return 1

        print(f"\n[HA] Initializing Home Assistant integration...")
        ha_client = homeassistant_client.HomeAssistantClient(
            base_url=args.ha_url,
            token=args.ha_token,
            entity_id=args.ha_entity,
            color_entity_id=args.ha_color_entity,
            min_brightness=args.ha_min_brightness,
            poll_interval=args.ha_poll_interval,
            latitude=args.ha_latitude,
            longitude=args.ha_longitude,
            use_solar=not args.ha_no_solar
        )

        if ha_client.connect():
            ha_client.start_polling()
            overlay.ha_client = ha_client
            overlay.ha_color_enabled = args.ha_color
            print(f"[HA] Integration enabled, monitoring '{args.ha_entity}'")
            print(f"[HA] Min brightness: {args.ha_min_brightness*100:.0f}%")
            if not args.ha_no_solar:
                print(f"[HA] Solar brightness enabled (location: {args.ha_latitude:.2f}°N, {args.ha_longitude:.2f}°E)")
            if args.ha_color:
                color_entity = args.ha_color_entity or args.ha_entity
                print(f"[HA] Color sync enabled, controlling '{color_entity}'")
        else:
            print("[HA] Warning: Failed to connect to Home Assistant, continuing without HA")
            ha_client = None
    overlay.ha_client = ha_client

    # Setup MQTT layer-state publishing if enabled
    mqtt_client_instance = None
    if args.mqtt:
        try:
            import mqtt_client as mqtt_client_module
        except ImportError:
            print("Error: MQTT integration requested but mqtt_client module not available")
            print("Install with: pip install paho-mqtt")
            return 1

        print(f"\n[MQTT] Initializing MQTT layer-state publishing...")
        mqtt_client_instance = mqtt_client_module.MQTTHomeAssistantClient(
            mqtt_broker=args.mqtt_broker,
            mqtt_port=args.mqtt_port,
            mqtt_transport=args.mqtt_transport,
            mqtt_username=args.mqtt_username,
            mqtt_password=args.mqtt_password,
            use_tls=args.mqtt_tls,
            device_id=args.mqtt_device_id,
        )

        if mqtt_client_instance.connect():
            overlay.mqtt_client = mqtt_client_instance
            overlay.mqtt_enabled = True
            print(f"[MQTT] Publishing layer state to 'qmk/{args.mqtt_device_id}/layer'")
        else:
            print("[MQTT] Warning: Failed to connect to MQTT broker, continuing without MQTT")
            mqtt_client_instance = None

    # Load keyboard layers
    overlay.load_layers()

    # Start keyboard monitoring thread
    keyboard_monitor = KeyboardMonitor(keyboard, overlay, rows, cols)
    keyboard_monitor.start()

    print("\nOverlay window active!")
    print(f"- Press L[{keyboard_monitor.interactive_key_row},{keyboard_monitor.interactive_key_col}] on layer {keyboard_monitor.interactive_key_layer} to make window interactive (drag to move)")
    print(f"- Press R[{keyboard_monitor.on_top_key_row - keyboard_monitor.rows_per_half},{keyboard_monitor.on_top_key_col}] on layer {keyboard_monitor.on_top_key_layer} to bring window to top for 10 seconds")
    print("- Press Ctrl+C to exit")
    print()

    # Run Qt event loop
    try:
        ret = app.exec_()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        keyboard_monitor.running = False
        keyboard.close()
        # Stop Home Assistant polling if enabled
        if ha_client:
            ha_client.stop_polling()
            ha_client.disconnect()
        if mqtt_client_instance:
            mqtt_client_instance.disconnect()

    return ret if 'ret' in locals() else 0


if __name__ == "__main__":
    sys.exit(main())
