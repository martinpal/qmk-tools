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


class LayerUpdateSignal(QObject):
    """Signal emitter for thread-safe GUI updates"""
    layer_changed = pyqtSignal(int, dict, int)  # layer_num, layer_stack, default_layer


class InteractiveSignal(QObject):
    """Signal emitter for interactive mode changes"""
    interactive_changed = pyqtSignal(bool)  # interactive state


class OnTopSignal(QObject):
    """Signal emitter for on-top mode changes"""
    on_top_changed = pyqtSignal(bool)  # on-top state


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

        # GUI state
        self.interactive_mode = False
        self.key_labels = []
        self.drag_position = None
        self.on_top_timer = None  # Timer for auto-return to bottom

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
                lower_keycode = self.all_layers[layer][key_idx]
                if lower_keycode != 0x0001:  # Not transparent
                    display_keycode = lower_keycode
                    break

        key_name = self.keyboard.keycode_to_name(display_keycode)

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
        print("Loading keyboard layers...")

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

        # Create signal for thread-safe interactive mode communication
        self.interactive_signal = InteractiveSignal()
        self.interactive_signal.interactive_changed.connect(overlay.set_interactive)

        # Create signal for thread-safe on-top mode communication
        self.on_top_signal = OnTopSignal()
        self.on_top_signal.on_top_changed.connect(overlay.set_window_on_top)

        # Layer state tracking
        self.current_layer = 0
        self.default_layer = 0
        self.active_layer_stack = {}
        self.pressed_keys = {}
        self.prev_state = [[False] * cols for _ in range(rows)]

        # Split keyboard configuration
        self.rows_per_half = rows // 2

        # Interactive mode trigger key (left half, row 4, col 3)
        self.interactive_key_row = 4
        self.interactive_key_col = 3
        self.interactive_key_layer = 5
        self.interactive_key_pressed = False  # Track if interactive key is currently pressed

        # On-top mode trigger key (right half, row 4, col 3)
        self.on_top_key_row = 4 + self.rows_per_half
        self.on_top_key_col = 3
        self.on_top_key_layer = 4
        self.on_top_key_pressed = False  # Track if on-top key is currently pressed

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
                        print("Too many USB errors, device may be disconnected. Waiting for reconnection...")
                        time.sleep(5)
                        self.error_count = 0
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
                                keycode = self.overlay.all_layers[self.current_layer][key_idx]
                                self.pressed_keys[(row, col)] = keycode
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


def main():
    """Main function"""
    import argparse

    parser = argparse.ArgumentParser(description="QMK Keyboard Overlay GUI")
    parser.add_argument('--keyboard', type=str, help='Keyboard selection: INDEX or VID:PID (e.g., 1 or FEED:6060)')
    parser.add_argument('--x', type=int, default=0, help='X position of window (default: 0)')
    parser.add_argument('--y', type=int, default=0, help='Y position of window (default: 0)')
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

    # Load keyboard layers
    overlay.load_layers()

    # Start keyboard monitoring thread
    keyboard_monitor = KeyboardMonitor(keyboard, overlay, rows, cols)
    keyboard_monitor.start()

    print("\nOverlay window active!")
    print("- Press L[4,3] on layer 5 to make window interactive (drag to move)")
    print("- Press R[4,3] on layer 4 to bring window to top for 10 seconds")
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

    return ret if 'ret' in locals() else 0


if __name__ == "__main__":
    sys.exit(main())
