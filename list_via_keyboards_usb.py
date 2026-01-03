#!/usr/bin/env python3
"""
QMK VIA Keyboard Scanner (using libusb)

This script discovers all VIA-capable QMK keyboards connected to the system
and displays detailed information about each one including macros and keymap layers.
It can also control RGB lighting settings.

This version uses libusb (PyUSB) for direct USB communication, which matches
how via-nativia works.

Requirements:
    pip install pyusb

Usage:
    python3 list_via_keyboards_usb.py                        # Basic info only
    python3 list_via_keyboards_usb.py --dump                 # Dump macros and keymaps
    python3 list_via_keyboards_usb.py --dump --matrix=6x7    # Specify matrix size
    python3 list_via_keyboards_usb.py --monitor --matrix=6x7 # Monitor key presses
    python3 list_via_keyboards_usb.py --monitor=10 --matrix=6x7  # Monitor for 10 seconds
    python3 list_via_keyboards_usb.py --brightness=128 --keyboard=1  # Set brightness on keyboard #1
    python3 list_via_keyboards_usb.py --brightness=200 --save  # Set and save to EEPROM
    python3 list_via_keyboards_usb.py --color=128,255        # Set RGB color (H,S)
    python3 list_via_keyboards_usb.py --blink --keyboard=FEED:6060  # Blink specific keyboard
    python3 list_via_keyboards_usb.py --blink=5              # Blink LEDs 5 times
    python3 list_via_keyboards_usb.py --debug                # Show all USB devices
    python3 list_via_keyboards_usb.py --verbose              # Show communication details
    python3 list_via_keyboards_usb.py --help                 # Show this help

Options:
    --dump                  Dump all macros and keymap layers (fast buffer method)
    --dump-slow             Dump keymap using slow single-key method
                            Uses CMD_GET_KEYCODE (0x04) to read each key individually
                            Slower but can be used to verify buffer method accuracy
    --dump-compare          Compare fast and slow methods, report any discrepancies
                            Useful for debugging keymap reading issues
    --matrix=ROWSxCOLS      Specify keyboard matrix dimensions (e.g., 10x6 for Sofle)
                            Required for keymap dumping and matrix monitoring
    --monitor[=SECONDS]     Monitor key presses in real-time (requires --matrix)
                            Shows physical matrix positions [row,col] for all keys
                            Optional: specify duration in seconds (default: until Ctrl+C)
    --monitor-layers        Monitor active layer and display keymap when it changes
                            Tracks MO/TG/TT/DF/OSL layer keys and shows current layout
                            Clears screen and displays full keymap for active layer
                            (requires --matrix)
    --keyboard=SELECTOR     Select specific keyboard to operate on
                            Can be index (e.g., --keyboard=1 for first keyboard)
                            or VID:PID (e.g., --keyboard=FEED:6060)
                            Without this option, operations affect ALL keyboards
    --brightness=VALUE      Set RGB brightness (0-255)
    --color=HUE,SAT         Set RGB color in HSV format (both 0-255)
                            Example: --color=128,255 for cyan at full saturation
    --blink[=TIMES]         Blink keyboard LEDs (1-10 times, default 3)
                            Uses VIA device indication to toggle all LEDs
    --save                  Save RGB settings to EEPROM (persistent across reboots)
                            Use with --brightness or --color
    --debug                 Debug mode: list all USB devices
    --verbose, -v           Verbose mode: show USB communication details
    --help, -h              Show this help message

Examples:
    # List all VIA keyboards with basic info
    python3 list_via_keyboards_usb.py

    # Dump everything from a Sofle keyboard (10 rows × 6 columns)
    sudo python3 list_via_keyboards_usb.py --dump --matrix=10x6

    # Dump using slow method for verification
    sudo python3 list_via_keyboards_usb.py --dump-slow --matrix=10x6

    # Compare fast vs slow methods to check for issues
    sudo python3 list_via_keyboards_usb.py --dump-compare --matrix=10x6

    # Monitor key presses on first keyboard only
    sudo python3 list_via_keyboards_usb.py --monitor --matrix=10x6 --keyboard=1

    # Monitor layers - see keymap change when you press layer keys
    sudo python3 list_via_keyboards_usb.py --monitor-layers --matrix=10x6 --keyboard=1

    # Monitor for 30 seconds then exit
    sudo python3 list_via_keyboards_usb.py --monitor=30 --matrix=10x6

    # Set brightness on keyboard #2 only
    sudo python3 list_via_keyboards_usb.py --brightness=128 --keyboard=2

    # Set brightness on specific keyboard by VID:PID
    sudo python3 list_via_keyboards_usb.py --brightness=128 --keyboard=FEED:6060

    # Set brightness to 80% and save permanently (all keyboards)
    sudo python3 list_via_keyboards_usb.py --brightness=200 --save

    # Set color to red (hue=0) at full saturation
    sudo python3 list_via_keyboards_usb.py --color=0,255 --save

    # Set color to cyan (hue=128) at full saturation
    sudo python3 list_via_keyboards_usb.py --color=128,255

    # Blink LEDs on keyboard #1 to identify it
    sudo python3 list_via_keyboards_usb.py --blink --keyboard=1

    # Blink LEDs 5 times on all keyboards
    sudo python3 list_via_keyboards_usb.py --blink=5

Note:
    Currently requires sudo due to USB permissions. Working on non-sudo solution.
"""

import usb.core
import usb.util
import sys
from typing import List, Optional

# VIA Protocol Constants
RAW_EPSIZE = 32
RAW_OUT_EP = 0x03  # OUT endpoint for sending commands
RAW_IN_EP = 0x82   # IN endpoint for receiving responses

# Command IDs
CMD_GET_PROTOCOL_VERSION = 0x01
CMD_GET_KEYBOARD_VALUE = 0x02
CMD_SET_KEYBOARD_VALUE = 0x03
CMD_GET_KEYCODE = 0x04
CMD_CUSTOM_SET_VALUE = 0x07
CMD_CUSTOM_GET_VALUE = 0x08
CMD_CUSTOM_SAVE = 0x09
CMD_GET_LAYER_COUNT = 0x11
CMD_GET_MACRO_COUNT = 0x0C
CMD_GET_MACRO_BUFFER_SIZE = 0x0D
CMD_GET_KEYMAP_BUFFER = 0x12
CMD_GET_MACRO_BUFFER = 0x0E
CMD_GET_KEYMAP_BUFFER = 0x12

# Keyboard Value IDs
ID_UPTIME = 0x01
ID_LAYOUT_OPTIONS = 0x02
ID_SWITCH_MATRIX_STATE = 0x03
ID_FIRMWARE_VERSION = 0x04
ID_DEVICE_INDICATION = 0x05

# Channel IDs for custom values
CHANNEL_BACKLIGHT = 0x01
CHANNEL_RGBLIGHT = 0x02
CHANNEL_RGB_MATRIX = 0x03
CHANNEL_AUDIO = 0x04

# RGB Matrix Value IDs
RGB_MATRIX_BRIGHTNESS = 0x01
RGB_MATRIX_EFFECT = 0x02
RGB_MATRIX_EFFECT_SPEED = 0x03
RGB_MATRIX_COLOR = 0x04


class ViaKeyboard:
    """Represents a VIA-capable keyboard using libusb"""

    def __init__(self, device: usb.core.Device):
        self.device = device
        self.interface_number = None
        self.out_endpoint = None
        self.in_endpoint = None
        self.protocol_version = None
        self.uptime_ms = None
        self.firmware_version = None
        self.layer_count = None
        self.macro_count = None
        self.macro_buffer_size = None
        self.layout_options = None
        self.keyboard_name = None
        self.matrix_rows = None
        self.matrix_cols = None
        self.error_count = 0  # Track consecutive errors
        self.last_error_msg = None  # Avoid spamming same error

    def detect_keyboard_type(self):
        """Detect keyboard type based on product name and set matrix size"""
        try:
            product = usb.util.get_string(self.device, self.device.iProduct) if self.device.iProduct else ""
            product_lower = product.lower()

            # Known keyboard types with their matrix sizes
            if "sofle" in product_lower:
                self.keyboard_name = "Sofle"
                self.matrix_rows = 10
                self.matrix_cols = 6
            elif "crkbd" in product_lower or "corne" in product_lower:
                self.keyboard_name = "Crkbd"
                self.matrix_rows = 8
                self.matrix_cols = 6
            else:
                self.keyboard_name = product
                # Unknown keyboard - matrix will need to be specified manually

        except Exception:
            self.keyboard_name = "Unknown"

    def open(self) -> bool:
        """Open connection to the keyboard"""
        try:
            # Find the RAW HID interface (interface 1 according to QMK source)
            cfg = self.device.get_active_configuration()

            # Look for interface with interrupt endpoints 0x03 and 0x82
            for intf in cfg:
                has_out = False
                has_in = False

                for ep in intf:
                    if ep.bEndpointAddress == RAW_OUT_EP:
                        has_out = True
                        self.out_endpoint = ep
                    elif ep.bEndpointAddress == RAW_IN_EP:
                        has_in = True
                        self.in_endpoint = ep

                if has_out and has_in:
                    self.interface_number = intf.bInterfaceNumber

                    # Claim the interface if needed
                    if self.device.is_kernel_driver_active(self.interface_number):
                        try:
                            self.device.detach_kernel_driver(self.interface_number)
                        except usb.core.USBError:
                            pass  # Already detached or can't detach

                    usb.util.claim_interface(self.device, self.interface_number)
                    return True

            return False

        except Exception as e:
            print(f"Error opening device: {e}", file=sys.stderr)
            return False

    def close(self):
        """Close connection to the keyboard"""
        if self.device and self.interface_number is not None:
            try:
                usb.util.release_interface(self.device, self.interface_number)
            except:
                pass

    def send_command(self, command_id: int, params: List[int] = None, verbose=False) -> Optional[bytearray]:
        """Send a command and receive response"""
        if not self.device or not self.out_endpoint or not self.in_endpoint:
            return None

        # Build packet
        packet = bytearray(RAW_EPSIZE)
        packet[0] = command_id

        # Add parameters if provided
        if params:
            for i, param in enumerate(params):
                if i + 1 < RAW_EPSIZE:
                    packet[i + 1] = param

        try:
            # Clear any stale data in the IN endpoint buffer
            try:
                while True:
                    self.in_endpoint.read(RAW_EPSIZE, timeout=10)
            except usb.core.USBTimeoutError:
                pass  # Buffer is now clear

            if verbose:
                print(f"  Sending command 0x{command_id:02X} to EP 0x{self.out_endpoint.bEndpointAddress:02X}")
                print(f"  Data: {' '.join(f'{b:02X}' for b in packet[:8])}...")

            # Send command via interrupt OUT
            bytes_written = self.out_endpoint.write(packet, timeout=1000)

            if verbose:
                print(f"  Wrote {bytes_written} bytes")

            # Receive response via interrupt IN
            if verbose:
                print(f"  Reading from EP 0x{self.in_endpoint.bEndpointAddress:02X}")

            response = self.in_endpoint.read(RAW_EPSIZE, timeout=1000)

            if verbose:
                print(f"  Received {len(response)} bytes")
                print(f"  Full response: {' '.join(f'{b:02X}' for b in response)}")

            if not response:
                return None

            # Check for unhandled command
            if response[0] == 0xFF:
                if verbose:
                    print(f"  Command returned unhandled (0xFF)")
                return None

            return bytearray(response)

        except Exception as e:
            error_msg = str(e)
            # Only print error if it's different from last one or first error
            if error_msg != self.last_error_msg:
                print(f"Error during communication: {e}", file=sys.stderr)
                self.last_error_msg = error_msg
                self.error_count = 1
            else:
                self.error_count += 1
                # Print every 20th repeated error to show device is still having issues
                if self.error_count % 20 == 0:
                    print(f"USB communication still failing ({self.error_count} errors): {e}", file=sys.stderr)
            return None

    def query_info(self) -> bool:
        """Query all available information from the keyboard"""
        if not self.device:
            return False

        # Get protocol version
        response = self.send_command(CMD_GET_PROTOCOL_VERSION)
        if response and response[0] == CMD_GET_PROTOCOL_VERSION:
            self.protocol_version = (response[1] << 8) | response[2]

        # Get uptime
        response = self.send_command(CMD_GET_KEYBOARD_VALUE, [ID_UPTIME])
        if response and response[0] == CMD_GET_KEYBOARD_VALUE:
            self.uptime_ms = (response[2] << 24) | (response[3] << 16) | \
                            (response[4] << 8) | response[5]

        # Get firmware version
        response = self.send_command(CMD_GET_KEYBOARD_VALUE, [ID_FIRMWARE_VERSION])
        if response and response[0] == CMD_GET_KEYBOARD_VALUE:
            self.firmware_version = (response[2] << 24) | (response[3] << 16) | \
                                   (response[4] << 8) | response[5]

        # Get layout options
        response = self.send_command(CMD_GET_KEYBOARD_VALUE, [ID_LAYOUT_OPTIONS])
        if response and response[0] == CMD_GET_KEYBOARD_VALUE:
            self.layout_options = (response[2] << 24) | (response[3] << 16) | \
                                 (response[4] << 8) | response[5]

        # Get layer count
        response = self.send_command(CMD_GET_LAYER_COUNT)
        if response and response[0] == CMD_GET_LAYER_COUNT:
            self.layer_count = response[1]

        # Get macro count
        response = self.send_command(CMD_GET_MACRO_COUNT)
        if response and response[0] == CMD_GET_MACRO_COUNT:
            self.macro_count = response[1]

        # Get macro buffer size
        response = self.send_command(CMD_GET_MACRO_BUFFER_SIZE)
        if response and response[0] == CMD_GET_MACRO_BUFFER_SIZE:
            self.macro_buffer_size = (response[1] << 8) | response[2]

        return True

    def format_uptime(self) -> str:
        """Format uptime in human-readable format"""
        if self.uptime_ms is None:
            return "N/A"

        seconds = self.uptime_ms / 1000
        minutes = seconds / 60
        hours = minutes / 60
        days = hours / 24

        if days >= 1:
            return f"{days:.1f} days"
        elif hours >= 1:
            return f"{hours:.1f} hours"
        elif minutes >= 1:
            return f"{minutes:.1f} minutes"
        else:
            return f"{seconds:.1f} seconds"

    def get_matrix_dimensions(self) -> tuple:
        """Try to determine matrix dimensions by probing"""
        # We could query switch_matrix_state, but for now return None
        # Real implementation would need to know the keyboard's matrix size
        return (None, None)

    def get_rgb_brightness(self) -> Optional[int]:
        """Get RGB Matrix brightness (0-255)"""
        response = self.send_command(CMD_CUSTOM_GET_VALUE, [
            CHANNEL_RGB_MATRIX,
            RGB_MATRIX_BRIGHTNESS
        ])

        if response and response[0] == CMD_CUSTOM_GET_VALUE:
            # Response format: [command_id, channel_id, value_id, brightness]
            return response[3]
        return None

    def set_rgb_brightness(self, brightness: int, save: bool = False, verbose: bool = False) -> bool:
        """Set RGB brightness (0-255) - tries both RGBLIGHT and RGB_MATRIX

        Args:
            brightness: Brightness value 0-255
            save: If True, save to EEPROM (persistent across reboots)
            verbose: If True, print debug information

        Returns:
            True if successful, False otherwise
        """
        if not 0 <= brightness <= 255:
            print(f"Brightness must be 0-255, got {brightness}")
            return False

        # Try RGBLIGHT first (more common on split keyboards)
        for channel, channel_name in [(CHANNEL_RGBLIGHT, "RGBLIGHT"), (CHANNEL_RGB_MATRIX, "RGB_MATRIX")]:
            if verbose:
                print(f"Trying {channel_name} (channel 0x{channel:02X})...")
                print(f"Sending CMD_CUSTOM_SET_VALUE (0x{CMD_CUSTOM_SET_VALUE:02X})")
                print(f"  Channel: {channel_name} (0x{channel:02X})")
                print(f"  Value ID: BRIGHTNESS (0x{RGB_MATRIX_BRIGHTNESS:02X})")
                print(f"  Brightness: {brightness}")

            response = self.send_command(CMD_CUSTOM_SET_VALUE, [
                channel,
                RGB_MATRIX_BRIGHTNESS,  # Same ID for both RGBLIGHT and RGB_MATRIX
                brightness
            ], verbose=verbose)

            if verbose:
                if response:
                    print(f"Response: {' '.join(f'{b:02X}' for b in response[:8])}")
                else:
                    print("No response received")

            if not response:
                if verbose:
                    print(f"Error: No response from keyboard for {channel_name}")
                continue

            if response[0] == 0xFF:
                if verbose:
                    print(f"{channel_name} not supported (unhandled), trying next...")
                continue

            if response[0] != CMD_CUSTOM_SET_VALUE:
                if verbose:
                    print(f"Error: Response command ID mismatch: got 0x{response[0]:02X}, expected 0x{CMD_CUSTOM_SET_VALUE:02X}")
                continue

            # Success! Save to EEPROM if requested
            if verbose:
                print(f"✓ {channel_name} accepted the command")

            if save:
                if verbose:
                    print(f"Sending CMD_CUSTOM_SAVE (0x{CMD_CUSTOM_SAVE:02X})")
                save_response = self.send_command(CMD_CUSTOM_SAVE, [channel], verbose=verbose)
                if not save_response or save_response[0] != CMD_CUSTOM_SAVE:
                    print("Warning: Failed to save to EEPROM")
                    return False

            return True

        # Neither channel worked
        if verbose:
            print("Error: Neither RGBLIGHT nor RGB_MATRIX responded successfully")
        return False

    def get_rgb_color(self) -> Optional[tuple]:
        """Get RGB Matrix color as (hue, saturation)"""
        response = self.send_command(CMD_CUSTOM_GET_VALUE, [
            CHANNEL_RGB_MATRIX,
            RGB_MATRIX_COLOR
        ])

        if response and response[0] == CMD_CUSTOM_GET_VALUE:
            # Response format: [command_id, channel_id, value_id, hue, saturation]
            return (response[3], response[4])
        return None

    def set_rgb_color(self, hue: int, saturation: int, save: bool = False, verbose: bool = False) -> bool:
        """Set RGB color (HSV) - tries both RGBLIGHT and RGB_MATRIX

        Args:
            hue: Hue value 0-255
            saturation: Saturation value 0-255
            save: If True, save to EEPROM
            verbose: If True, print debug information

        Returns:
            True if successful, False otherwise
        """
        if not (0 <= hue <= 255 and 0 <= saturation <= 255):
            print(f"Hue and saturation must be 0-255")
            return False

        # Try RGBLIGHT first (more common on split keyboards)
        for channel, channel_name in [(CHANNEL_RGBLIGHT, "RGBLIGHT"), (CHANNEL_RGB_MATRIX, "RGB_MATRIX")]:
            if verbose:
                print(f"Trying {channel_name} (channel 0x{channel:02X})...")

            response = self.send_command(CMD_CUSTOM_SET_VALUE, [
                channel,
                RGB_MATRIX_COLOR,  # Same ID for both
                hue,
                saturation
            ], verbose=verbose)

            if not response:
                if verbose:
                    print(f"Error: No response from keyboard for {channel_name}")
                continue

            if response[0] == 0xFF:
                if verbose:
                    print(f"{channel_name} not supported (unhandled), trying next...")
                continue

            if response[0] != CMD_CUSTOM_SET_VALUE:
                if verbose:
                    print(f"Error: Response command ID mismatch")
                continue

            # Success!
            if verbose:
                print(f"✓ {channel_name} accepted the command")

            if save:
                save_response = self.send_command(CMD_CUSTOM_SAVE, [channel], verbose=verbose)
                if not save_response or save_response[0] != CMD_CUSTOM_SAVE:
                    print("Warning: Failed to save to EEPROM")
                    return False

            return True

        return False

    def blink_leds(self, times: int = 3, verbose: bool = False) -> bool:
        """Blink keyboard LEDs using device indication

        This triggers the VIA device indication function which toggles all RGB LEDs.
        The keyboard will blink its LEDs on and off the specified number of times.

        Args:
            times: Number of times to blink (default 3)
            verbose: If True, print debug information

        Returns:
            True if successful, False otherwise
        """
        import time

        if verbose:
            print(f"Blinking LEDs {times} times...")

        # Send device indication commands
        # Toggle on/off the specified number of times
        for i in range(times * 2):
            response = self.send_command(CMD_SET_KEYBOARD_VALUE, [
                ID_DEVICE_INDICATION,
                i % 6  # Value cycles 0-5 as per VIA protocol
            ], verbose=verbose)

            if not response or response[0] == 0xFF:
                if verbose:
                    print(f"Error: Device indication not supported or failed")
                return False

            # Wait between toggles (matches VIA's 200ms interval)
            time.sleep(0.2)

        if verbose:
            print("✓ Blink complete")

        return True

    def get_matrix_state(self, rows: int, cols: int, offset: int = 0, verbose: bool = False) -> Optional[List[int]]:
        """Get the switch matrix state (which keys are currently pressed)

        Args:
            rows: Number of rows in the keyboard matrix
            cols: Number of columns in the keyboard matrix
            offset: Row offset for querying (used for large matrices)
            verbose: If True, print debug information

        Returns:
            List of bytes representing the matrix state, or None on error
            Each bit represents whether a switch is pressed (1) or released (0)
        """
        bytes_per_row = (cols + 7) // 8  # Round up to nearest byte
        rows_per_query = min(rows - offset, 28 // bytes_per_row)
        query_size = rows_per_query * bytes_per_row

        if verbose:
            print(f"Querying matrix: rows={rows}, cols={cols}, offset={offset}")
            print(f"  bytes_per_row={bytes_per_row}, rows_per_query={rows_per_query}, query_size={query_size}")

        # Query matrix state
        response = self.send_command(CMD_GET_KEYBOARD_VALUE, [
            ID_SWITCH_MATRIX_STATE,
            offset
        ], verbose=verbose)

        if not response or response[0] != CMD_GET_KEYBOARD_VALUE:
            if verbose:
                print("Error: Failed to get matrix state")
            return None

        # Extract matrix data from response
        # Response format: [command_id, value_id, offset, data...]
        matrix_data = list(response[3:3+query_size])

        if verbose:
            print(f"  Received {len(matrix_data)} bytes of matrix data")

        return matrix_data

    def decode_matrix_state(self, matrix_data: List[int], rows: int, cols: int) -> List[List[bool]]:
        """Decode raw matrix state bytes into a 2D array of key states

        Args:
            matrix_data: Raw bytes from get_matrix_state()
            rows: Number of rows in the matrix
            cols: Number of columns in the matrix

        Returns:
            2D list where result[row][col] = True if key is pressed
        """
        bytes_per_row = (cols + 7) // 8
        result = []

        for row in range(rows):
            row_states = []
            for col in range(cols):
                byte_idx = row * bytes_per_row + (col // 8)
                bit_idx = col % 8

                if byte_idx < len(matrix_data):
                    is_pressed = (matrix_data[byte_idx] >> bit_idx) & 1
                    row_states.append(bool(is_pressed))
                else:
                    row_states.append(False)

            result.append(row_states)

        return result

    def monitor_layers(self, rows: int, cols: int, duration: float = None, verbose: bool = False):
        """Monitor active layer and display keymap when layer changes"""
        import time
        import os

        # Detect if this is likely a split keyboard
        is_split = (rows % 2 == 0) and rows >= 8
        rows_per_half = rows // 2 if is_split else rows

        print(f"Monitoring layers on {rows}x{cols} matrix...")
        if is_split:
            print(f"Split keyboard detected: {rows_per_half} rows per half")
        print("Press layer keys (MO/TG/TT/DF/OSL) to see layer layouts")
        print("Press Ctrl+C to stop")
        print()

        # Read all keymaps once at start using fast method
        print("Loading all layer keymaps...")

        # Use fast buffer method
        total_keys = rows * cols * self.layer_count
        total_bytes = total_keys * 2

        offset = 0
        keymap_data = bytearray()

        while offset < total_bytes:
            chunk_size = min(28, total_bytes - offset)

            response = self.send_command(CMD_GET_KEYMAP_BUFFER, [
                (offset >> 8) & 0xFF,
                offset & 0xFF,
                chunk_size
            ])

            if response and response[0] == CMD_GET_KEYMAP_BUFFER:
                keymap_data.extend(response[4:4+chunk_size])
            else:
                print(f"Failed to read keymap at offset {offset}")
                break

            offset += chunk_size

        # Parse keycodes (big-endian)
        keycodes = []
        for i in range(0, len(keymap_data), 2):
            if i + 1 < len(keymap_data):
                keycode = (keymap_data[i] << 8) | keymap_data[i + 1]
                keycodes.append(keycode)

        # Split into layers
        keys_per_layer = rows * cols
        all_layers = []
        for layer in range(self.layer_count):
            start_idx = layer * keys_per_layer
            end_idx = start_idx + keys_per_layer
            layer_keys = keycodes[start_idx:end_idx]
            all_layers.append(layer_keys)

        print(f"Loaded {self.layer_count} layers")
        print()

        # Layer names and colors from QMK source code
        # Extracted from keyboards/crkbd/keymaps/default/keymap.c (lines 98-125)
        # and keyboards/sofle/keymaps/via-mouse/keymap.c (lines 197-248)
        layer_info = {
            0: {"name": "Base", "color": "WHITE"},
            1: {"name": "Game", "color": "CYAN"},
            2: {"name": "Lower", "color": "RED"},
            3: {"name": "Raise", "color": "BLUE"},
            4: {"name": "Adjust", "color": "GREEN"},
            5: {"name": "Mouse", "color": "ORANGE"},
            6: {"name": "Extra", "color": "MAGENTA"},
        }

        # ANSI color codes for rendering
        color_codes = {
            "WHITE": "\033[97m",
            "CYAN": "\033[96m",
            "RED": "\033[91m",
            "BLUE": "\033[94m",
            "GREEN": "\033[92m",
            "ORANGE": "\033[38;5;208m",  # 256-color orange
            "MAGENTA": "\033[95m",
            "RESET": "\033[0m",
        }

        def get_layer_name(layer_num):
            """Get friendly name for layer"""
            if layer_num in layer_info:
                return layer_info[layer_num]["name"]
            return f"Layer{layer_num}"

        def get_layer_color(layer_num):
            """Get color name for layer"""
            if layer_num in layer_info:
                return layer_info[layer_num]["color"]
            return ""

        def get_colored_text(text, color_name):
            """Render text in the specified color using ANSI codes"""
            if color_name in color_codes:
                return f"{color_codes[color_name]}{text}{color_codes['RESET']}"
            return text

        current_layer = 0
        default_layer = 0  # Track the default base layer (set by DF keys)
        active_layer_stack = {}  # Track which layer keys are held: {layer_num: key_type}
        pressed_keys = {}  # Track what keycode each physical key had when pressed: {(row, col): keycode}
        prev_state = [[False] * cols for _ in range(rows)]
        start_time = time.time()

        def display_layer(layer_num):
            """Display the keymap for a specific layer"""
            os.system('clear' if os.name == 'posix' else 'cls')
            print("=" * 70)
            layer_name = get_layer_name(layer_num)
            layer_color = get_layer_color(layer_num)
            if active_layer_stack:
                stack_str = ', '.join([f"{key_type}({layer})" for layer, key_type in sorted(active_layer_stack.items(), reverse=True)])
                if layer_color:
                    colored_layer = get_colored_text(layer_color, layer_color)
                    print(f"ACTIVE LAYER: {layer_num} ({layer_name}) [{colored_layer}] | Stack: {stack_str}")
                else:
                    print(f"ACTIVE LAYER: {layer_num} ({layer_name}) | Stack: {stack_str}")
            else:
                if layer_color:
                    colored_layer = get_colored_text(layer_color, layer_color)
                    print(f"ACTIVE LAYER: {layer_num} ({layer_name}) [{colored_layer}]")
                else:
                    print(f"ACTIVE LAYER: {layer_num} ({layer_name})")
            print("=" * 70)
            print()

            layer_keys = all_layers[layer_num]

            if is_split:
                # Display left half
                print("  LEFT HALF:")
                for row in range(rows_per_half):
                    row_start = row * cols
                    row_end = row_start + cols
                    row_keys = layer_keys[row_start:row_end]

                    # Show key names
                    key_names = [self.keycode_to_name(kc) for kc in row_keys]
                    max_width = max(len(name) for name in key_names) if key_names else 10
                    padded = [name.ljust(max_width) for name in key_names]
                    names_str = ' '.join(padded)
                    print(f"    L{row}: {names_str}")

                print()
                print("  RIGHT HALF:")

                # Display right half (columns are REVERSED in the matrix!)
                for row in range(rows_per_half, rows):
                    row_start = row * cols
                    row_end = row_start + cols
                    row_keys = layer_keys[row_start:row_end]

                    # REVERSE the columns for right half
                    row_keys = list(reversed(row_keys))

                    # Show key names
                    key_names = [self.keycode_to_name(kc) for kc in row_keys]
                    max_width = max(len(name) for name in key_names) if key_names else 10
                    padded = [name.ljust(max_width) for name in key_names]
                    names_str = ' '.join(padded)
                    print(f"    R{row - rows_per_half}: {names_str}")
            else:
                # Display as matrix
                for row in range(rows):
                    row_start = row * cols
                    row_end = row_start + cols
                    row_keys = layer_keys[row_start:row_end]

                    # Show key names
                    key_names = [self.keycode_to_name(kc) for kc in row_keys]
                    max_width = max(len(name) for name in key_names) if key_names else 10
                    padded = [name.ljust(max_width) for name in key_names]
                    names_str = ' '.join(padded)
                    print(f"    Row {row}: {names_str}")

            print()
            if active_layer_stack:
                stack_str = ', '.join([f"{key_type}({layer})" for layer, key_type in sorted(active_layer_stack.items(), reverse=True)])
                print(f"Active layer keys: {stack_str}")
            else:
                print("Active layer keys: None")
            print("Press Ctrl+C to stop")

        # Display initial layer
        display_layer(current_layer)

        try:
            while True:
                # Check duration
                if duration is not None and (time.time() - start_time) >= duration:
                    break

                # Read matrix state
                matrix_data = self.get_matrix_state(rows, cols, verbose=verbose)
                if matrix_data is None:
                    continue

                current_state = self.decode_matrix_state(matrix_data, rows, cols)

                # Detect changes
                layer_changed = False
                for row in range(rows):
                    for col in range(cols):
                        if current_state[row][col] != prev_state[row][col]:
                            pressed = current_state[row][col]

                            # Get the keycode at this position
                            key_idx = row * cols + col

                            if pressed:
                                # Key was just pressed - check current layer
                                keycode = all_layers[current_layer][key_idx]
                                # Remember what this key was when pressed
                                pressed_keys[(row, col)] = keycode
                            else:
                                # Key was just released - use the keycode it had when pressed
                                keycode = pressed_keys.get((row, col), 0x0000)
                                # Clean up
                                if (row, col) in pressed_keys:
                                    del pressed_keys[(row, col)]

                            if verbose:
                                state_str = "PRESSED" if pressed else "RELEASED"
                                print(f"Key [{row},{col}]: {state_str}, keycode=0x{keycode:04X} {self.keycode_to_name(keycode)}")

                            # Check if it's a layer switching key
                            # MO(layer) - 0x5220-0x523F (momentary)
                            if 0x5220 <= keycode <= 0x523F:
                                target_layer = keycode & 0x1F
                                if pressed:
                                    # Add to stack
                                    active_layer_stack[target_layer] = "MO"
                                    # Switch to highest priority layer (highest number)
                                    new_layer = max(active_layer_stack.keys())
                                    if new_layer != current_layer:
                                        current_layer = new_layer
                                        layer_changed = True
                                else:
                                    # Remove from stack
                                    if target_layer in active_layer_stack:
                                        del active_layer_stack[target_layer]
                                    # Return to highest priority remaining layer or default layer
                                    new_layer = max(active_layer_stack.keys()) if active_layer_stack else default_layer
                                    if new_layer != current_layer:
                                        current_layer = new_layer
                                        layer_changed = True

                            # TG(layer) - 0x5260-0x527F (toggle)
                            elif 0x5260 <= keycode <= 0x527F and pressed:
                                target_layer = keycode & 0x1F
                                if current_layer == target_layer:
                                    current_layer = 0
                                else:
                                    current_layer = target_layer
                                layer_changed = True

                            # DF(layer) - 0x5240-0x525F (set default)
                            elif 0x5240 <= keycode <= 0x525F and pressed:
                                target_layer = keycode & 0x1F
                                # DF sets the default (base) layer
                                default_layer = target_layer
                                # If no layer keys are active, switch to it immediately
                                if not active_layer_stack:
                                    current_layer = target_layer
                                    layer_changed = True
                                # Otherwise, the new default will take effect when layer keys are released

                            # OSL(layer) - 0x5280-0x529F (one-shot layer)
                            elif 0x5280 <= keycode <= 0x529F and pressed:
                                target_layer = keycode & 0x1F
                                active_layer_stack[target_layer] = "OSL"
                                current_layer = target_layer
                                layer_changed = True

                            # TT(layer) - 0x52C0-0x52DF (tap toggle)
                            elif 0x52C0 <= keycode <= 0x52DF and pressed:
                                target_layer = keycode & 0x1F
                                if current_layer == target_layer:
                                    current_layer = 0
                                else:
                                    current_layer = target_layer
                                layer_changed = True

                if layer_changed:
                    display_layer(current_layer)

                prev_state = current_state
                time.sleep(0.02)  # 20ms poll interval

        except KeyboardInterrupt:
            print("\nLayer monitoring stopped")

    def monitor_matrix(self, rows: int, cols: int, duration: float = None, callback=None, verbose: bool = False):
        """Monitor the keyboard matrix for key presses in real-time

        Args:
            rows: Number of rows in the keyboard matrix (total, including both halves for split keyboards)
            cols: Number of columns in the keyboard matrix
            duration: How long to monitor in seconds (None = indefinite)
            callback: Optional function called when keys change: callback(row, col, pressed)
            verbose: If True, print debug information
        """
        import time

        # Detect if this is likely a split keyboard (even number of rows)
        is_split = (rows % 2 == 0) and rows >= 8
        rows_per_half = rows // 2 if is_split else rows

        print(f"Monitoring {rows}x{cols} matrix...")
        if is_split:
            print(f"Split keyboard detected: {rows_per_half} rows per half")
        print("Press Ctrl+C to stop")
        print()

        prev_state = [[False] * cols for _ in range(rows)]
        start_time = time.time()

        try:
            while True:
                # Check duration
                if duration is not None and (time.time() - start_time) >= duration:
                    break

                # Get current matrix state
                matrix_data = self.get_matrix_state(rows, cols, verbose=verbose)
                if matrix_data is None:
                    print("Error reading matrix state")
                    break

                # Decode into 2D array
                current_state = self.decode_matrix_state(matrix_data, rows, cols)

                # Detect changes
                changes = []
                for row in range(rows):
                    for col in range(cols):
                        if current_state[row][col] != prev_state[row][col]:
                            changes.append((row, col, current_state[row][col]))

                # Report changes
                for row, col, pressed in changes:
                    state = "PRESSED" if pressed else "RELEASED"

                    if is_split:
                        # Determine which half and adjust display
                        if row < rows_per_half:
                            half = "L"  # Left half
                            half_row = row
                        else:
                            half = "R"  # Right half
                            half_row = row - rows_per_half
                        print(f"Key {half}[{half_row},{col}]: {state}")
                    else:
                        print(f"Key [{row},{col}]: {state}")

                    if callback:
                        callback(row, col, pressed)

                prev_state = current_state

                # Poll interval (20ms like VIA)
                time.sleep(0.02)

        except KeyboardInterrupt:
            print("\nMonitoring stopped")

    def get_keycode(self, layer: int, row: int, col: int, verbose: bool = False) -> Optional[int]:
        """Get a single keycode at [layer, row, col] using CMD_GET_KEYCODE (0x04)"""
        response = self.send_command(CMD_GET_KEYCODE, [layer, row, col], verbose=verbose)

        if not response or response[0] != CMD_GET_KEYCODE:
            return None

        # Response format: [cmd, layer, row, col, hi_byte, lo_byte, ...]
        # Keycode is at bytes 4-5 (big-endian: hi byte first)
        hi = response[4]
        lo = response[5]
        keycode = (hi << 8) | lo

        return keycode

    def parse_macro(self, macro_data: bytearray) -> str:
        """Parse a QMK macro into human-readable format

        QMK macros can contain:
        1. Special sequences: \x01 + code + keycode (TAP/DOWN/UP/DELAY)
        2. Printable ASCII: 0x20-0x7E printed directly
        3. HID keycodes: 0x04-0x1F used as keycodes (layout-dependent)
        """
        # QMK macro format codes
        SS_QMK_PREFIX = 0x01
        SS_TAP_CODE = 0x01
        SS_DOWN_CODE = 0x02
        SS_UP_CODE = 0x03
        SS_DELAY_CODE = 0x04

        # Basic keycode names (0x00-0xFF)
        keycode_names = {
            0x00: 'KC_NO', 0x01: 'KC_TRNS',
            0x04: 'KC_A', 0x05: 'KC_B', 0x06: 'KC_C', 0x07: 'KC_D',
            0x08: 'KC_E', 0x09: 'KC_F', 0x0A: 'KC_G', 0x0B: 'KC_H',
            0x0C: 'KC_I', 0x0D: 'KC_J', 0x0E: 'KC_K', 0x0F: 'KC_L',
            0x10: 'KC_M', 0x11: 'KC_N', 0x12: 'KC_O', 0x13: 'KC_P',
            0x14: 'KC_Q', 0x15: 'KC_R', 0x16: 'KC_S', 0x17: 'KC_T',
            0x18: 'KC_U', 0x19: 'KC_V', 0x1A: 'KC_W', 0x1B: 'KC_X',
            0x1C: 'KC_Y', 0x1D: 'KC_Z',
            0x1E: 'KC_1', 0x1F: 'KC_2', 0x20: 'KC_3', 0x21: 'KC_4',
            0x22: 'KC_5', 0x23: 'KC_6', 0x24: 'KC_7', 0x25: 'KC_8',
            0x26: 'KC_9', 0x27: 'KC_0',
            0x28: 'KC_ENT', 0x29: 'KC_ESC', 0x2A: 'KC_BSPC', 0x2B: 'KC_TAB',
            0x2C: 'KC_SPC', 0x2D: 'KC_MINS', 0x2E: 'KC_EQL', 0x2F: 'KC_LBRC',
            0x30: 'KC_RBRC', 0x31: 'KC_BSLS', 0x33: 'KC_SCLN', 0x34: 'KC_QUOT',
            0x35: 'KC_GRV', 0x36: 'KC_COMM', 0x37: 'KC_DOT', 0x38: 'KC_SLSH',
            0x39: 'KC_CAPS',
            0x3A: 'KC_F1', 0x3B: 'KC_F2', 0x3C: 'KC_F3', 0x3D: 'KC_F4',
            0x3E: 'KC_F5', 0x3F: 'KC_F6', 0x40: 'KC_F7', 0x41: 'KC_F8',
            0x42: 'KC_F9', 0x43: 'KC_F10', 0x44: 'KC_F11', 0x45: 'KC_F12',
            0x68: 'KC_F13', 0x69: 'KC_F14', 0x6A: 'KC_F15', 0x6B: 'KC_F16',
            0x6C: 'KC_F17', 0x6D: 'KC_F18', 0x6E: 'KC_F19', 0x6F: 'KC_F20',
            0x70: 'KC_F21', 0x71: 'KC_F22', 0x72: 'KC_F23', 0x73: 'KC_F24',
            0x50: 'KC_LEFT', 0x4F: 'KC_RGHT', 0x51: 'KC_DOWN', 0x52: 'KC_UP',
            0xE0: 'KC_LCTL', 0xE1: 'KC_LSFT', 0xE2: 'KC_LALT', 0xE3: 'KC_LGUI',
            0xE4: 'KC_RCTL', 0xE5: 'KC_RSFT', 0xE6: 'KC_RALT', 0xE7: 'KC_RGUI',
        }

        # Czech QWERTZ layout keycode to character mapping (unshifted)
        # Based on quantum/keymap_extras/keymap_czech.h and observed behavior
        # This handles bytes 0x04-0x1F that appear without SS_QMK_PREFIX
        czech_layout = {
            0x04: 'a', 0x05: 'b', 0x06: 'c', 0x07: 'd',  # KC_A-D
            0x08: 'e', 0x09: 'f', 0x0A: 'g', 0x0B: 'h',  # KC_E-H
            0x0C: 'i', 0x0D: 'j', 0x0E: 'k', 0x0F: 'l',  # KC_I-L
            0x10: 'm', 0x11: 'n', 0x12: 'o', 0x13: 'p',  # KC_M-P
            0x14: 'q', 0x15: 'r', 0x16: 's', 0x17: 't',  # KC_Q-T
            0x18: 'u', 0x19: 'v', 0x1A: 'w', 0x1B: 'x',  # KC_U-X
            0x1C: '.', 0x1D: 'y',  # KC_Y->.  on Czech, KC_Z->y (empirically determined)
            0x1E: '1', 0x1F: '2',  # Numbers (but might be special chars on Czech)
        }

        result = []
        i = 0
        while i < len(macro_data):
            byte = macro_data[i]

            if byte == SS_QMK_PREFIX and i + 1 < len(macro_data):
                # Special QMK code
                code = macro_data[i + 1]

                if code == SS_TAP_CODE and i + 2 < len(macro_data):
                    keycode = macro_data[i + 2]
                    keyname = keycode_names.get(keycode, f'0x{keycode:02X}')
                    result.append(f'{{TAP({keyname})}}')
                    i += 3
                elif code == SS_DOWN_CODE and i + 2 < len(macro_data):
                    keycode = macro_data[i + 2]
                    keyname = keycode_names.get(keycode, f'0x{keycode:02X}')
                    result.append(f'{{DOWN({keyname})}}')
                    i += 3
                elif code == SS_UP_CODE and i + 2 < len(macro_data):
                    keycode = macro_data[i + 2]
                    keyname = keycode_names.get(keycode, f'0x{keycode:02X}')
                    result.append(f'{{UP({keyname})}}')
                    i += 3
                elif code == SS_DELAY_CODE and i + 2 < len(macro_data):
                    # Delay format: read digits until '|'
                    i += 2
                    delay_str = ''
                    while i < len(macro_data) and macro_data[i] != ord('|'):
                        delay_str += chr(macro_data[i])
                        i += 1
                    if i < len(macro_data) and macro_data[i] == ord('|'):
                        i += 1
                    result.append(f'{{DELAY({delay_str}ms)}}')
                else:
                    # Unknown code, show as hex
                    result.append(f'{{0x{byte:02X}{code:02X}}}')
                    i += 2
            elif 0x20 <= byte <= 0x7E:
                # Printable ASCII
                result.append(chr(byte))
                i += 1
            elif byte in czech_layout:
                # HID keycode that should be interpreted with Czech layout
                # These are unshifted characters
                result.append(czech_layout[byte])
                i += 1
            else:
                # Non-printable/unknown, show as hex
                result.append(f'{{0x{byte:02X}}}')
                i += 1

        return ''.join(result)

    def dump_macros(self) -> str:
        """Dump all macro data"""
        if not self.macro_buffer_size:
            return "Macro buffer size unknown"

        lines = []
        lines.append("=" * 70)
        lines.append("MACRO DATA")
        lines.append("=" * 70)

        # Read macro buffer in chunks
        offset = 0
        macro_data = bytearray()

        while offset < self.macro_buffer_size:
            chunk_size = min(28, self.macro_buffer_size - offset)

            response = self.send_command(CMD_GET_MACRO_BUFFER, [
                (offset >> 8) & 0xFF,
                offset & 0xFF,
                chunk_size
            ])

            if response and response[0] == CMD_GET_MACRO_BUFFER:
                macro_data.extend(response[3:3+chunk_size])
            else:
                lines.append(f"Failed to read at offset {offset}")
                break

            offset += chunk_size

        # Parse macros (null-terminated strings)
        lines.append(f"Total buffer size: {len(macro_data)} bytes")
        lines.append(f"Macro slots: {self.macro_count}")
        lines.append("")

        macro_id = 0
        current_macro = bytearray()

        for i, byte in enumerate(macro_data):
            if byte == 0x00:
                # End of macro
                if len(current_macro) > 0:
                    lines.append(f"Macro {macro_id}:")
                    parsed = self.parse_macro(current_macro)
                    lines.append(f"  Content: {parsed}")
                    lines.append(f"  Raw hex: {' '.join(f'{b:02X}' for b in current_macro)}")
                    lines.append("")
                    current_macro = bytearray()
                    macro_id += 1

                    if macro_id >= self.macro_count:
                        break
                elif macro_id < self.macro_count:
                    # Empty macro slot
                    lines.append(f"Macro {macro_id}: (empty)")
                    lines.append("")
                    macro_id += 1
            else:
                current_macro.append(byte)

        if len(current_macro) > 0:
            lines.append(f"Macro {macro_id} (incomplete/no null terminator):")
            parsed = self.parse_macro(current_macro)
            lines.append(f"  Content: {parsed}")
            lines.append(f"  Raw hex: {' '.join(f'{b:02X}' for b in current_macro)}")

        lines.append("=" * 70)
        return "\n".join(lines)

    def keycode_to_name(self, keycode: int) -> str:
        """Convert QMK keycode to human-readable name"""
        # Basic keycodes (0x0000-0x00FF)
        basic_keycodes = {
            0x0000: 'KC_NO', 0x0001: 'KC_TRNS',
            0x0004: 'KC_A', 0x0005: 'KC_B', 0x0006: 'KC_C', 0x0007: 'KC_D',
            0x0008: 'KC_E', 0x0009: 'KC_F', 0x000A: 'KC_G', 0x000B: 'KC_H',
            0x000C: 'KC_I', 0x000D: 'KC_J', 0x000E: 'KC_K', 0x000F: 'KC_L',
            0x0010: 'KC_M', 0x0011: 'KC_N', 0x0012: 'KC_O', 0x0013: 'KC_P',
            0x0014: 'KC_Q', 0x0015: 'KC_R', 0x0016: 'KC_S', 0x0017: 'KC_T',
            0x0018: 'KC_U', 0x0019: 'KC_V', 0x001A: 'KC_W', 0x001B: 'KC_X',
            0x001C: 'KC_Y', 0x001D: 'KC_Z',
            0x001E: 'KC_1', 0x001F: 'KC_2', 0x0020: 'KC_3', 0x0021: 'KC_4',
            0x0022: 'KC_5', 0x0023: 'KC_6', 0x0024: 'KC_7', 0x0025: 'KC_8',
            0x0026: 'KC_9', 0x0027: 'KC_0',
            0x0028: 'KC_ENT', 0x0029: 'KC_ESC', 0x002A: 'KC_BSPC', 0x002B: 'KC_TAB',
            0x002C: 'KC_SPC', 0x002D: 'KC_MINS', 0x002E: 'KC_EQL', 0x002F: 'KC_LBRC',
            0x0030: 'KC_RBRC', 0x0031: 'KC_BSLS', 0x0032: 'KC_NUHS', 0x0033: 'KC_SCLN',
            0x0034: 'KC_QUOT', 0x0035: 'KC_GRV', 0x0036: 'KC_COMM', 0x0037: 'KC_DOT',
            0x0038: 'KC_SLSH', 0x0039: 'KC_CAPS',
            0x003A: 'KC_F1', 0x003B: 'KC_F2', 0x003C: 'KC_F3', 0x003D: 'KC_F4',
            0x003E: 'KC_F5', 0x003F: 'KC_F6', 0x0040: 'KC_F7', 0x0041: 'KC_F8',
            0x0042: 'KC_F9', 0x0043: 'KC_F10', 0x0044: 'KC_F11', 0x0045: 'KC_F12',
            0x0068: 'KC_F13', 0x0069: 'KC_F14', 0x006A: 'KC_F15', 0x006B: 'KC_F16',
            0x006C: 'KC_F17', 0x006D: 'KC_F18', 0x006E: 'KC_F19', 0x006F: 'KC_F20',
            0x0070: 'KC_F21', 0x0071: 'KC_F22', 0x0072: 'KC_F23', 0x0073: 'KC_F24',
            0x0046: 'KC_PSCR', 0x0047: 'KC_SCRL', 0x0048: 'KC_PAUS', 0x0049: 'KC_INS',
            0x004A: 'KC_HOME', 0x004B: 'KC_PGUP', 0x004C: 'KC_DEL', 0x004D: 'KC_END',
            0x004E: 'KC_PGDN', 0x004F: 'KC_RGHT', 0x0050: 'KC_LEFT', 0x0051: 'KC_DOWN',
            0x0052: 'KC_UP', 0x0053: 'KC_NUM',
            0x0054: 'KC_PSLS', 0x0055: 'KC_PAST', 0x0056: 'KC_PMNS', 0x0057: 'KC_PPLS',
            0x0058: 'KC_PENT', 0x0059: 'KC_P1', 0x005A: 'KC_P2', 0x005B: 'KC_P3',
            0x005C: 'KC_P4', 0x005D: 'KC_P5', 0x005E: 'KC_P6', 0x005F: 'KC_P7',
            0x0060: 'KC_P8', 0x0061: 'KC_P9', 0x0062: 'KC_P0', 0x0063: 'KC_PDOT',
            0x0064: 'KC_NUBS', 0x0065: 'KC_APP',
            0x00E0: 'KC_LCTL', 0x00E1: 'KC_LSFT', 0x00E2: 'KC_LALT', 0x00E3: 'KC_LGUI',
            0x00E4: 'KC_RCTL', 0x00E5: 'KC_RSFT', 0x00E6: 'KC_RALT', 0x00E7: 'KC_RGUI',
            0x00A8: 'KC_MUTE', 0x00A9: 'KC_VOLU', 0x00AA: 'KC_VOLD',
            0x00AB: 'KC_MNXT', 0x00AC: 'KC_MPRV', 0x00AD: 'KC_MSTP', 0x00AE: 'KC_MPLY',
        }

        if keycode in basic_keycodes:
            return basic_keycodes[keycode]

        # Mods with basic keycode (0x0100-0x1FFF)
        if 0x0100 <= keycode <= 0x1FFF:
            mods = (keycode >> 8) & 0x1F
            kc = keycode & 0xFF
            mod_str = []
            if mods & 0x01: mod_str.append('LCTL')
            if mods & 0x02: mod_str.append('LSFT')
            if mods & 0x04: mod_str.append('LALT')
            if mods & 0x08: mod_str.append('LGUI')
            if mods & 0x10: mod_str.append('RCTL')
            kc_str = basic_keycodes.get(kc, f'0x{kc:02X}')
            return f'{"+".join(mod_str)}({kc_str})'

        # Mod-Tap (0x2000-0x3FFF)
        if 0x2000 <= keycode <= 0x3FFF:
            mods = (keycode >> 8) & 0x1F
            kc = keycode & 0xFF
            mod_str = []
            if mods & 0x01: mod_str.append('LCTL')
            if mods & 0x02: mod_str.append('LSFT')
            if mods & 0x04: mod_str.append('LALT')
            if mods & 0x08: mod_str.append('LGUI')
            if mods & 0x10: mod_str.append('RCTL')
            kc_str = basic_keycodes.get(kc, f'0x{kc:02X}')
            return f'MT({"+".join(mod_str)},{kc_str})'

        # Layer-Tap (0x4000-0x4FFF)
        if 0x4000 <= keycode <= 0x4FFF:
            layer = (keycode >> 8) & 0x0F
            kc = keycode & 0xFF
            kc_str = basic_keycodes.get(kc, f'0x{kc:02X}')
            return f'LT({layer},{kc_str})'

        # TO(layer) - 0x5200-0x521F
        if 0x5200 <= keycode <= 0x521F:
            layer = keycode & 0x1F
            return f'TO({layer})'

        # MO(layer) - 0x5220-0x523F
        if 0x5220 <= keycode <= 0x523F:
            layer = keycode & 0x1F
            return f'MO({layer})'

        # DF(layer) - 0x5240-0x525F
        if 0x5240 <= keycode <= 0x525F:
            layer = keycode & 0x1F
            return f'DF({layer})'

        # TG(layer) - 0x5260-0x527F
        if 0x5260 <= keycode <= 0x527F:
            layer = keycode & 0x1F
            return f'TG({layer})'

        # OSL(layer) - 0x5280-0x529F
        if 0x5280 <= keycode <= 0x529F:
            layer = keycode & 0x1F
            return f'OSL({layer})'

        # TT(layer) - 0x52C0-0x52DF
        if 0x52C0 <= keycode <= 0x52DF:
            layer = keycode & 0x1F
            return f'TT({layer})'

        # Macro (0x7700-0x777F)
        if 0x7700 <= keycode <= 0x777F:
            macro_id = keycode & 0x7F
            return f'M{macro_id}'

        # RGB controls (0x7800-0x78FF)
        if 0x7800 <= keycode <= 0x78FF:
            rgb_offset = keycode - 0x7800
            rgb_codes = {
                0x00: 'RGB_TOG', 0x01: 'RGB_MOD', 0x02: 'RGB_RMOD',
                0x03: 'RGB_HUI', 0x04: 'RGB_HUD', 0x05: 'RGB_SAI',
                0x06: 'RGB_SAD', 0x07: 'RGB_VAI', 0x08: 'RGB_VAD',
                0x09: 'RGB_SPI', 0x0A: 'RGB_SPD',
            }
            return rgb_codes.get(rgb_offset, f'RGB(0x{rgb_offset:02X})')

        # QMK keycodes (0x7C00-0x7DFF)
        qmk_codes = {
            0x7C00: 'QK_BOOT', 0x7C01: 'QK_RBT', 0x7C02: 'QK_MAKE',
            0x7C03: 'QK_VERS', 0x7C04: 'QK_CLR_EEPROM',
            0x7C16: 'QK_GESC',  # Grave Escape (ESC/~)
        }
        if keycode in qmk_codes:
            return qmk_codes[keycode]

        # Unknown - show as hex
        return f'0x{keycode:04X}'

    def dump_keymap_compare(self, rows: int, cols: int) -> str:
        """Compare fast and slow methods, showing discrepancies with debug info"""
        if not self.layer_count or not rows or not cols:
            return "Layer count or matrix dimensions unknown"

        lines = []
        lines.append("=" * 70)
        lines.append("KEYMAP COMPARISON - Fast vs Slow Method")
        lines.append("=" * 70)
        lines.append("")

        # Detect if this is likely a split keyboard
        is_split = (rows % 2 == 0) and rows >= 8
        rows_per_half = rows // 2 if is_split else rows

        lines.append(f"Matrix: {rows} rows × {cols} columns")
        if is_split:
            lines.append(f"Split keyboard: {rows_per_half} rows per half")
        lines.append(f"Layers: {self.layer_count}")
        lines.append("")

        # Read using SLOW method (single-key API)
        lines.append("Reading keymap using SLOW method (CMD_GET_KEYCODE)...")
        keycodes_slow = []
        for layer in range(self.layer_count):
            for row in range(rows):
                for col in range(cols):
                    keycode = self.get_keycode(layer, row, col)
                    if keycode is None:
                        keycode = 0x0000
                    keycodes_slow.append(keycode)

        # Read using FAST method (buffer API)
        lines.append("Reading keymap using FAST method (CMD_GET_KEYMAP_BUFFER)...")
        lines.append("")

        total_keys = rows * cols * self.layer_count
        total_bytes = total_keys * 2

        offset = 0
        keymap_data = bytearray()

        while offset < total_bytes:
            chunk_size = min(28, total_bytes - offset)

            response = self.send_command(CMD_GET_KEYMAP_BUFFER, [
                (offset >> 8) & 0xFF,
                offset & 0xFF,
                chunk_size
            ])

            if response and response[0] == CMD_GET_KEYMAP_BUFFER:
                keymap_data.extend(response[4:4+chunk_size])
            else:
                break

            offset += chunk_size

        # Parse keycodes (big-endian)
        keycodes_fast = []
        for i in range(0, len(keymap_data), 2):
            if i + 1 < len(keymap_data):
                keycode = (keymap_data[i] << 8) | keymap_data[i + 1]
                keycodes_fast.append(keycode)

        # Compare and find discrepancies
        keys_per_layer = rows * cols
        discrepancies = []

        for layer in range(self.layer_count):
            for row in range(rows):
                for col in range(cols):
                    idx = layer * keys_per_layer + row * cols + col
                    if idx < len(keycodes_fast) and idx < len(keycodes_slow):
                        if keycodes_fast[idx] != keycodes_slow[idx]:
                            discrepancies.append({
                                'layer': layer,
                                'row': row,
                                'col': col,
                                'idx': idx,
                                'fast': keycodes_fast[idx],
                                'slow': keycodes_slow[idx]
                            })

        # Report results
        if not discrepancies:
            lines.append("✓ NO DISCREPANCIES FOUND - Both methods return identical data!")
            lines.append("")
        else:
            lines.append(f"✗ FOUND {len(discrepancies)} DISCREPANCIES!")
            lines.append("")

            # Show all discrepancies
            lines.append("Discrepancy Details:")
            lines.append("-" * 70)
            for d in discrepancies:
                lines.append(f"Layer {d['layer']}, Row {d['row']}, Col {d['col']} (keycode index {d['idx']}):")
                lines.append(f"  SLOW (correct): 0x{d['slow']:04X} = {self.keycode_to_name(d['slow'])}")
                lines.append(f"  FAST (wrong):   0x{d['fast']:04X} = {self.keycode_to_name(d['fast'])}")

                # Show wire format around this position
                byte_idx = d['idx'] * 2
                byte_start = max(0, byte_idx - 4)
                byte_end = min(len(keymap_data), byte_idx + 6)
                lines.append(f"  Wire bytes [{byte_start}-{byte_end-1}]:")
                lines.append(f"    {[f'0x{b:02X}' for b in keymap_data[byte_start:byte_end]]}")
                lines.append(f"    Position: {' ' * ((byte_idx - byte_start) * 6)}^^")
                lines.append("")

            # Show first discrepancy in detail
            if discrepancies:
                d = discrepancies[0]
                lines.append("=" * 70)
                lines.append("DETAILED ANALYSIS OF FIRST DISCREPANCY")
                lines.append("=" * 70)
                lines.append("")
                lines.append(f"Location: Layer {d['layer']}, Row {d['row']}, Col {d['col']}")
                lines.append(f"Keycode index in layer: {d['idx'] % keys_per_layer}")
                lines.append(f"Absolute keycode index: {d['idx']}")
                lines.append(f"Byte offset in buffer (after skip): {d['idx'] * 2}")
                lines.append("")
                lines.append(f"Expected (SLOW): 0x{d['slow']:04X} = {self.keycode_to_name(d['slow'])}")
                lines.append(f"Got (FAST):      0x{d['fast']:04X} = {self.keycode_to_name(d['fast'])}")
                lines.append("")

                # Show context - the entire row
                layer = d['layer']
                row = d['row']
                row_start = row * cols
                row_end = row_start + cols
                layer_offset = layer * keys_per_layer

                lines.append(f"Entire Row {row} in Layer {layer}:")
                lines.append("  SLOW (correct):")
                row_slow = [keycodes_slow[layer_offset + i] for i in range(row_start, row_end)]
                lines.append(f"    {[f'0x{k:04X}' for k in row_slow]}")
                lines.append(f"    {[self.keycode_to_name(k) for k in row_slow]}")
                lines.append("  FAST (wrong):")
                row_fast = [keycodes_fast[layer_offset + i] for i in range(row_start, row_end) if layer_offset + i < len(keycodes_fast)]
                lines.append(f"    {[f'0x{k:04X}' for k in row_fast]}")
                lines.append(f"    {[self.keycode_to_name(k) for k in row_fast]}")
                lines.append("")

        return '\n'.join(lines)

    def dump_keymap_slow(self, rows: int, cols: int) -> str:
        """Dump all keymap layers using slow single-key method (CMD_GET_KEYCODE)"""
        if not self.layer_count or not rows or not cols:
            return "Layer count or matrix dimensions unknown"

        lines = []
        lines.append("=" * 70)
        lines.append("KEYMAP DATA (SLOW METHOD - Single Key API)")
        lines.append("=" * 70)
        lines.append("")

        # Detect if this is likely a split keyboard
        is_split = (rows % 2 == 0) and rows >= 8
        rows_per_half = rows // 2 if is_split else rows

        lines.append(f"Matrix: {rows} rows × {cols} columns")
        if is_split:
            lines.append(f"Split keyboard: {rows_per_half} rows per half")
        lines.append(f"Layers: {self.layer_count}")
        lines.append("")

        # Read keymap using single-key API
        lines.append("Reading keymap using CMD_GET_KEYCODE (0x04)...")
        lines.append("")

        keycodes = []
        for layer in range(self.layer_count):
            for row in range(rows):
                for col in range(cols):
                    keycode = self.get_keycode(layer, row, col)
                    if keycode is None:
                        lines.append(f"Failed to read key at L{layer} R{row} C{col}")
                        keycode = 0x0000
                    keycodes.append(keycode)

        # Now display using same format as fast method
        keys_per_layer = rows * cols

        for layer in range(self.layer_count):
            lines.append(f"Layer {layer}:")
            lines.append("-" * 70)

            start_idx = layer * keys_per_layer
            end_idx = start_idx + keys_per_layer
            layer_keys = keycodes[start_idx:end_idx]

            if is_split:
                # Display left half
                lines.append("  LEFT HALF:")
                for row in range(rows_per_half):
                    row_start = row * cols
                    row_end = row_start + cols
                    row_keys = layer_keys[row_start:row_end]

                    # Show key names
                    key_names = [self.keycode_to_name(kc) for kc in row_keys]
                    max_width = max(len(name) for name in key_names) if key_names else 10
                    padded = [name.ljust(max_width) for name in key_names]
                    names_str = ' '.join(padded)
                    lines.append(f"    L{row}: {names_str}")

                lines.append("")
                lines.append("  RIGHT HALF:")

                # Display right half (columns are REVERSED in the matrix!)
                for row in range(rows_per_half, rows):
                    row_start = row * cols
                    row_end = row_start + cols
                    row_keys = layer_keys[row_start:row_end]

                    # REVERSE the columns for right half
                    row_keys = list(reversed(row_keys))

                    # Show key names
                    key_names = [self.keycode_to_name(kc) for kc in row_keys]
                    max_width = max(len(name) for name in key_names) if key_names else 10
                    padded = [name.ljust(max_width) for name in key_names]
                    names_str = ' '.join(padded)
                    lines.append(f"    R{row - rows_per_half}: {names_str}")
            else:
                # Display as matrix
                for row in range(rows):
                    row_start = row * cols
                    row_end = row_start + cols
                    row_keys = layer_keys[row_start:row_end]

                    # Show key names
                    key_names = [self.keycode_to_name(kc) for kc in row_keys]
                    max_width = max(len(name) for name in key_names) if key_names else 10
                    padded = [name.ljust(max_width) for name in key_names]
                    names_str = ' '.join(padded)
                    lines.append(f"    Row {row}: {names_str}")

            lines.append("")

        return '\n'.join(lines)

    def dump_keymap(self, rows: int, cols: int) -> str:
        """Dump all keymap layers"""
        if not self.layer_count or not rows or not cols:
            return "Layer count or matrix dimensions unknown"

        lines = []
        lines.append("=" * 70)
        lines.append("KEYMAP DATA")
        lines.append("=" * 70)
        lines.append("")

        # Detect if this is likely a split keyboard
        is_split = (rows % 2 == 0) and rows >= 8
        rows_per_half = rows // 2 if is_split else rows

        # Calculate total keymap size
        total_keys = rows * cols * self.layer_count
        total_bytes = total_keys * 2  # 2 bytes per keycode

        lines.append(f"Matrix: {rows} rows × {cols} columns")
        if is_split:
            lines.append(f"Split keyboard: {rows_per_half} rows per half")
        lines.append(f"Layers: {self.layer_count}")
        lines.append(f"Total keycodes expected: {total_keys} ({total_bytes} bytes)")
        lines.append("")

        # Read keymap in chunks
        offset = 0
        keymap_data = bytearray()

        while offset < total_bytes:
            chunk_size = min(28, total_bytes - offset)

            response = self.send_command(CMD_GET_KEYMAP_BUFFER, [
                (offset >> 8) & 0xFF,
                offset & 0xFF,
                chunk_size
            ])

            if response and response[0] == CMD_GET_KEYMAP_BUFFER:
                keymap_data.extend(response[4:4+chunk_size])
            else:
                lines.append(f"Failed to read at offset {offset}")
                break

            offset += chunk_size

        lines.append(f"Actually read: {len(keymap_data)} bytes")
        lines.append("")

        # Parse keycodes (big-endian: high byte first, low byte second)
        keycodes = []
        for i in range(0, len(keymap_data), 2):
            if i + 1 < len(keymap_data):
                keycode = (keymap_data[i] << 8) | keymap_data[i + 1]
                keycodes.append(keycode)

        # Calculate keys per layer
        keys_per_layer = rows * cols

        # Display layer by layer
        for layer in range(self.layer_count):

            lines.append(f"Layer {layer}:")
            lines.append("-" * 70)

            start_idx = layer * keys_per_layer
            end_idx = start_idx + keys_per_layer
            layer_keys = keycodes[start_idx:end_idx]

            if is_split:
                # Display left half
                lines.append("  LEFT HALF:")
                for row in range(rows_per_half):
                    row_start = row * cols
                    row_end = row_start + cols
                    row_keys = layer_keys[row_start:row_end]

                    # Show key names
                    key_names = [self.keycode_to_name(kc) for kc in row_keys]
                    # Pad to consistent width for readability
                    max_width = max(len(name) for name in key_names) if key_names else 10
                    padded = [name.ljust(max_width) for name in key_names]
                    names_str = ' '.join(padded)
                    lines.append(f"    L{row}: {names_str}")

                lines.append("")
                lines.append("  RIGHT HALF:")

                # Display right half (columns are REVERSED in the matrix!)
                for row in range(rows_per_half, rows):
                    row_start = row * cols
                    row_end = row_start + cols
                    row_keys = layer_keys[row_start:row_end]

                    # REVERSE the columns for right half
                    row_keys = list(reversed(row_keys))

                    # Show key names
                    key_names = [self.keycode_to_name(kc) for kc in row_keys]
                    # Pad to consistent width for readability
                    max_width = max(len(name) for name in key_names) if key_names else 10
                    padded = [name.ljust(max_width) for name in key_names]
                    names_str = ' '.join(padded)
                    lines.append(f"    R{row - rows_per_half}: {names_str}")
            else:
                # Display as matrix with both hex and names
                for row in range(rows):
                    row_start = row * cols
                    row_end = row_start + cols
                    row_keys = layer_keys[row_start:row_end]

                    # Show key names
                    key_names = [self.keycode_to_name(kc) for kc in row_keys]
                    # Pad to consistent width for readability
                    max_width = max(len(name) for name in key_names) if key_names else 10
                    padded = [name.ljust(max_width) for name in key_names]
                    names_str = ' '.join(padded)
                    lines.append(f"  Row {row}: {names_str}")

            lines.append("")

        lines.append("=" * 70)
        return "\n".join(lines)

    def dump_all_info(self, rows: int = None, cols: int = None, use_slow_dump: bool = False) -> str:
        """Dump all available information"""
        lines = []

        # Basic info
        lines.append(str(self))
        lines.append("")

        # Macros
        if self.macro_buffer_size:
            lines.append(self.dump_macros())
            lines.append("")

        # Keymap
        if rows and cols and self.layer_count:
            if use_slow_dump:
                lines.append(self.dump_keymap_slow(rows, cols))
            else:
                lines.append(self.dump_keymap(rows, cols))

        return "\n".join(lines)

    def __str__(self) -> str:
        """String representation of keyboard info"""
        lines = []
        lines.append("=" * 70)

        # Basic device info
        manufacturer = usb.util.get_string(self.device, self.device.iManufacturer) if self.device.iManufacturer else 'Unknown'
        product = usb.util.get_string(self.device, self.device.iProduct) if self.device.iProduct else 'Unknown'
        lines.append(f"Device: {manufacturer} {product}")

        # USB IDs
        vid = self.device.idVendor
        pid = self.device.idProduct
        lines.append(f"USB ID: {vid:04X}:{pid:04X}")

        # Serial number
        if self.device.iSerialNumber:
            serial = usb.util.get_string(self.device, self.device.iSerialNumber)
            lines.append(f"Serial: {serial}")

        # Bus/Address
        lines.append(f"Bus: {self.device.bus}, Address: {self.device.address}")

        # Interface used
        if self.interface_number is not None:
            lines.append(f"Interface: {self.interface_number}")

        lines.append("-" * 70)

        # VIA Protocol info
        if self.protocol_version is not None:
            lines.append(f"VIA Protocol Version: 0x{self.protocol_version:04X} (v{self.protocol_version})")
        else:
            lines.append("VIA Protocol Version: Failed to query")

        # Firmware info
        if self.firmware_version is not None:
            if self.firmware_version == 0:
                lines.append("Firmware Version: Not set (0x00000000)")
            else:
                lines.append(f"Firmware Version: 0x{self.firmware_version:08X}")
        else:
            lines.append("Firmware Version: N/A")

        # Uptime
        lines.append(f"Uptime: {self.format_uptime()}")
        if self.uptime_ms is not None:
            lines.append(f"        ({self.uptime_ms:,} ms)")

        # Layout options
        if self.layout_options is not None:
            lines.append(f"Layout Options: 0x{self.layout_options:08X}")
        else:
            lines.append("Layout Options: N/A")

        # Keymap info
        if self.layer_count is not None:
            lines.append(f"Layer Count: {self.layer_count}")
        else:
            lines.append("Layer Count: N/A")

        # Macro info
        if self.macro_count is not None:
            lines.append(f"Macro Count: {self.macro_count}")
        else:
            lines.append("Macro Count: N/A")

        if self.macro_buffer_size is not None:
            lines.append(f"Macro Buffer Size: {self.macro_buffer_size} bytes")
        else:
            lines.append("Macro Buffer Size: N/A")

        lines.append("=" * 70)

        return "\n".join(lines)


def find_via_keyboards(verbose=False) -> List[usb.core.Device]:
    """Find all VIA-capable keyboards connected to the system"""
    via_keyboards = []

    # Find all USB devices
    devices = usb.core.find(find_all=True)

    for device in devices:
        try:
            # Check if device has the RAW HID endpoints
            cfg = device.get_active_configuration()

            for intf in cfg:
                has_out = False
                has_in = False

                for ep in intf:
                    if ep.bEndpointAddress == RAW_OUT_EP:
                        has_out = True
                    elif ep.bEndpointAddress == RAW_IN_EP:
                        has_in = True

                if has_out and has_in:
                    if verbose:
                        try:
                            product = usb.util.get_string(device, device.iProduct) if device.iProduct else 'Unknown'
                        except:
                            product = 'Unknown'
                        print(f"Found VIA device: {device.idVendor:04X}:{device.idProduct:04X} {product}")

                    via_keyboards.append(device)
                    break  # Found the interface, no need to check others

        except Exception as e:
            # Skip devices we can't access
            if verbose:
                print(f"Skipping device {device.idVendor:04X}:{device.idProduct:04X}: {e}")
            continue

    return via_keyboards


def debug_list_all_usb_devices():
    """List all USB devices for debugging"""
    print("=" * 70)
    print("DEBUG MODE: Listing all USB devices")
    print("=" * 70)
    print()

    devices = list(usb.core.find(find_all=True))

    if not devices:
        print("No USB devices found!")
        return

    print(f"Found {len(devices)} USB device(s) total\n")

    for device in devices:
        try:
            manufacturer = usb.util.get_string(device, device.iManufacturer) if device.iManufacturer else ''
        except:
            manufacturer = ''

        try:
            product = usb.util.get_string(device, device.iProduct) if device.iProduct else ''
        except:
            product = ''

        print(f"{manufacturer} {product}")
        print(f"  USB ID: {device.idVendor:04X}:{device.idProduct:04X}")
        print(f"  Bus: {device.bus}, Address: {device.address}")

        try:
            cfg = device.get_active_configuration()
            print(f"  Interfaces: {cfg.bNumInterfaces}")

            for intf in cfg:
                print(f"    Interface {intf.bInterfaceNumber}:")
                for ep in intf:
                    direction = "IN" if ep.bEndpointAddress & 0x80 else "OUT"
                    print(f"      Endpoint 0x{ep.bEndpointAddress:02X} ({direction})")

                    # Check if this has VIA endpoints
                    if ep.bEndpointAddress == RAW_OUT_EP or ep.bEndpointAddress == RAW_IN_EP:
                        print(f"        *** Possible VIA endpoint ***")

        except Exception as e:
            print(f"    (Cannot read configuration: {e})")

        print()


def print_help():
    """Print help message"""
    print(__doc__)
    sys.exit(0)


def main():
    """Main function"""
    # Parse arguments
    debug_mode = '--debug' in sys.argv or '-d' in sys.argv
    verbose_mode = '--verbose' in sys.argv or '-v' in sys.argv
    trace_mode = '--trace' in sys.argv or '-t' in sys.argv
    dump_mode = '--dump' in sys.argv
    dump_slow_mode = '--dump-slow' in sys.argv
    dump_compare_mode = '--dump-compare' in sys.argv
    monitor_layers_mode = '--monitor-layers' in sys.argv
    if '--help' in sys.argv or '-h' in sys.argv:
        print_help()

    # Get matrix dimensions if provided
    matrix_rows = None
    matrix_cols = None
    for arg in sys.argv:
        if arg.startswith('--matrix='):
            try:
                dims = arg.split('=')[1]
                matrix_rows, matrix_cols = map(int, dims.split('x'))
            except:
                print("Invalid matrix format. Use --matrix=ROWSxCOLS (e.g., --matrix=5x6)")
                return 1

    # Get RGB brightness setting if provided
    set_brightness = None
    save_brightness = '--save' in sys.argv
    for arg in sys.argv:
        if arg.startswith('--brightness='):
            try:
                set_brightness = int(arg.split('=')[1])
                if not 0 <= set_brightness <= 255:
                    print("Brightness must be 0-255")
                    return 1
            except:
                print("Invalid brightness format. Use --brightness=VALUE (0-255)")
                return 1

    # Get RGB color setting if provided
    set_hue = None
    set_saturation = None
    for arg in sys.argv:
        if arg.startswith('--color='):
            try:
                color_parts = arg.split('=')[1].split(',')
                set_hue = int(color_parts[0])
                set_saturation = int(color_parts[1])
                if not (0 <= set_hue <= 255 and 0 <= set_saturation <= 255):
                    print("Hue and saturation must be 0-255")
                    return 1
            except:
                print("Invalid color format. Use --color=HUE,SAT (e.g., --color=128,255)")
                return 1

    # Get blink setting if provided
    blink_times = None
    for arg in sys.argv:
        if arg.startswith('--blink='):
            try:
                blink_times = int(arg.split('=')[1])
                if not 1 <= blink_times <= 10:
                    print("Blink times must be 1-10")
                    return 1
            except:
                print("Invalid blink format. Use --blink=TIMES (e.g., --blink=3)")
                return 1
        elif arg == '--blink':
            blink_times = 3  # Default to 3 blinks

    # Get monitor setting if provided
    monitor_mode = '--monitor' in sys.argv
    monitor_duration = None
    for arg in sys.argv:
        if arg.startswith('--monitor='):
            try:
                monitor_mode = True
                monitor_duration = float(arg.split('=')[1])
                if monitor_duration <= 0:
                    print("Monitor duration must be positive")
                    return 1
            except:
                print("Invalid monitor format. Use --monitor=SECONDS (e.g., --monitor=10)")
                return 1

    # Get keyboard selection if provided
    selected_keyboard_index = None
    selected_keyboard_vid = None
    selected_keyboard_pid = None
    for arg in sys.argv:
        if arg.startswith('--keyboard='):
            try:
                kb_spec = arg.split('=')[1]
                # Check if it's a number (index) or VID:PID format
                if ':' in kb_spec:
                    # VID:PID format
                    vid_str, pid_str = kb_spec.split(':')
                    selected_keyboard_vid = int(vid_str, 16)
                    selected_keyboard_pid = int(pid_str, 16)
                else:
                    # Index format
                    selected_keyboard_index = int(kb_spec)
                    if selected_keyboard_index < 1:
                        print("Keyboard index must be >= 1")
                        return 1
            except:
                print("Invalid keyboard format. Use --keyboard=INDEX or --keyboard=VID:PID")
                print("Example: --keyboard=1 or --keyboard=FEED:6060")
                return 1

    print("QMK VIA Keyboard Scanner (libusb version)")
    print("=" * 70)
    print()

    # Note: Matrix size validation moved to per-keyboard detection
    # to allow auto-detection for known keyboards

    # Debug mode - list all USB devices
    if debug_mode:
        debug_list_all_usb_devices()
        return 0

    # Find VIA keyboards
    print("Scanning for VIA-capable keyboards...")
    if verbose_mode:
        print()
    devices = find_via_keyboards(verbose=verbose_mode)

    if not devices:
        print("\nNo VIA-capable keyboards found.")
        print("\nMake sure:")
        print("  1. Your keyboard has RAW_ENABLE compiled in")
        print("  2. The keyboard is properly connected")
        print("  3. You have permissions to access USB devices")
        print("     (Linux: may need udev rules)")
        print("\nTip: Run with --debug to see all USB devices")
        return 1

    # Filter devices based on selection
    if selected_keyboard_index is not None:
        if selected_keyboard_index > len(devices):
            print(f"\nError: Keyboard #{selected_keyboard_index} not found (only {len(devices)} keyboard(s) detected)")
            print("\nAvailable keyboards:")
            for i, device in enumerate(devices, 1):
                vid = device.idVendor
                pid = device.idProduct
                manufacturer = usb.util.get_string(device, device.iManufacturer) if device.iManufacturer else "Unknown"
                product = usb.util.get_string(device, device.iProduct) if device.iProduct else "Unknown"
                print(f"  #{i}: {manufacturer} {product} ({vid:04X}:{pid:04X})")
            return 1
        # Select only the requested keyboard
        devices = [devices[selected_keyboard_index - 1]]
        print(f"\nSelected keyboard #{selected_keyboard_index}")
    elif selected_keyboard_vid is not None and selected_keyboard_pid is not None:
        # Filter by VID:PID
        matching_devices = [d for d in devices if d.idVendor == selected_keyboard_vid and d.idProduct == selected_keyboard_pid]
        if not matching_devices:
            print(f"\nError: No keyboard found with VID:PID {selected_keyboard_vid:04X}:{selected_keyboard_pid:04X}")
            print("\nAvailable keyboards:")
            for i, device in enumerate(devices, 1):
                vid = device.idVendor
                pid = device.idProduct
                manufacturer = usb.util.get_string(device, device.iManufacturer) if device.iManufacturer else "Unknown"
                product = usb.util.get_string(device, device.iProduct) if device.iProduct else "Unknown"
                print(f"  #{i}: {manufacturer} {product} ({vid:04X}:{pid:04X})")
            return 1
        devices = matching_devices
        print(f"\nSelected keyboard(s) with VID:PID {selected_keyboard_vid:04X}:{selected_keyboard_pid:04X}")

    print(f"\nFound {len(devices)} VIA-capable keyboard(s)\n")

    # Query each keyboard
    for i, device in enumerate(devices, 1):
        vid = device.idVendor
        pid = device.idProduct
        manufacturer = usb.util.get_string(device, device.iManufacturer) if device.iManufacturer else "Unknown"
        product = usb.util.get_string(device, device.iProduct) if device.iProduct else "Unknown"

        print(f"\nKeyboard #{i}: {manufacturer} {product} ({vid:04X}:{pid:04X})")
        print()

        keyboard = ViaKeyboard(device)

        if not keyboard.open():
            print("Failed to open device")
            continue

        # Detect keyboard type and matrix size
        keyboard.detect_keyboard_type()

        # Use detected matrix size if not provided via command line
        actual_matrix_rows = matrix_rows if matrix_rows is not None else keyboard.matrix_rows
        actual_matrix_cols = matrix_cols if matrix_cols is not None else keyboard.matrix_cols

        # Show detected keyboard info
        if keyboard.keyboard_name and keyboard.matrix_rows:
            print(f"Detected: {keyboard.keyboard_name} ({keyboard.matrix_rows}x{keyboard.matrix_cols} matrix)")
        elif matrix_rows and matrix_cols:
            print(f"Using manual matrix specification: {matrix_rows}x{matrix_cols}")
        print()

        # Test communication with trace
        if trace_mode:
            print("Testing communication:")
            keyboard.send_command(CMD_GET_PROTOCOL_VERSION, verbose=True)
            print()

        # Query information
        keyboard.query_info()

        # Set RGB brightness if requested
        if set_brightness is not None:
            print(f"Setting RGB brightness to {set_brightness}...")
            if keyboard.set_rgb_brightness(set_brightness, save=save_brightness, verbose=verbose_mode):
                print("✓ Brightness set successfully")
                if save_brightness:
                    print("✓ Saved to EEPROM (persistent)")
            else:
                print("✗ Failed to set brightness")

        # Set RGB color if requested
        if set_hue is not None and set_saturation is not None:
            print(f"Setting RGB color to H:{set_hue} S:{set_saturation}...")
            if keyboard.set_rgb_color(set_hue, set_saturation, save=save_brightness, verbose=verbose_mode):
                print("✓ Color set successfully")
                if save_brightness:
                    print("✓ Saved to EEPROM (persistent)")
            else:
                print("✗ Failed to set color")

        # Blink LEDs if requested
        if blink_times is not None:
            print(f"Blinking LEDs {blink_times} time(s)...")
            if keyboard.blink_leds(times=blink_times, verbose=verbose_mode):
                print("✓ Blink complete")
            else:
                print("✗ Failed to blink LEDs")

        # Monitor layers if requested
        if monitor_layers_mode:
            if actual_matrix_rows is None or actual_matrix_cols is None:
                print("Error: Could not detect matrix size. Please specify --matrix=ROWSxCOLS")
                keyboard.close()
                continue
            print()
            keyboard.monitor_layers(
                actual_matrix_rows,
                actual_matrix_cols,
                verbose=verbose_mode
            )
            # Don't display other info in monitor mode
            keyboard.close()
            continue

        # Monitor matrix if requested
        if monitor_mode:
            if actual_matrix_rows is None or actual_matrix_cols is None:
                print("Error: Could not detect matrix size. Please specify --matrix=ROWSxCOLS")
                keyboard.close()
                continue
            print()
            keyboard.monitor_matrix(
                actual_matrix_rows,
                actual_matrix_cols,
                duration=monitor_duration,
                verbose=verbose_mode
            )
            # Don't display other info in monitor mode
            keyboard.close()
            continue

        # Display RGB info
        if set_brightness is not None or set_hue is not None or dump_mode:
            brightness = keyboard.get_rgb_brightness()
            color = keyboard.get_rgb_color()
            if brightness is not None:
                print(f"Current RGB brightness: {brightness}/255 ({brightness*100//255}%)")
            if color is not None:
                print(f"Current RGB color: H:{color[0]} S:{color[1]}")
            print()

        # Display information
        if dump_compare_mode and actual_matrix_rows and actual_matrix_cols:
            print(keyboard.dump_keymap_compare(actual_matrix_rows, actual_matrix_cols))
        elif dump_mode and actual_matrix_rows and actual_matrix_cols:
            print(keyboard.dump_all_info(actual_matrix_rows, actual_matrix_cols, use_slow_dump=dump_slow_mode))
        elif dump_slow_mode and actual_matrix_rows and actual_matrix_cols:
            print(keyboard.dump_all_info(actual_matrix_rows, actual_matrix_cols, use_slow_dump=True))
        elif dump_mode:
            print(keyboard)
            print()
            print(keyboard.dump_macros())
        elif set_brightness is None and set_hue is None and blink_times is None and not monitor_mode:
            print(keyboard)

        # Close connection
        keyboard.close()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\nUnexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
