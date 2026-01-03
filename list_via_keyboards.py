#!/usr/bin/env python3
"""
QMK VIA Keyboard Scanner (with debug mode)

This script discovers all VIA-capable QMK keyboards connected to the system
and displays detailed information about each one.

Requirements:
    pip install hidapi

Usage:
    python3 list_via_keyboards.py           # Normal mode
    python3 list_via_keyboards.py --debug   # Show all HID devices
    python3 list_via_keyboards.py --help    # Show help
"""

import hid
import sys
from typing import List, Dict, Optional

# VIA Protocol Constants
VIA_USAGE_PAGE = 0xFF60
VIA_USAGE_ID = 0x61
RAW_EPSIZE = 32

# Command IDs
CMD_GET_PROTOCOL_VERSION = 0x01
CMD_GET_KEYBOARD_VALUE = 0x02
CMD_GET_LAYER_COUNT = 0x11
CMD_GET_MACRO_COUNT = 0x0C
CMD_GET_MACRO_BUFFER_SIZE = 0x0D

# Keyboard Value IDs
ID_UPTIME = 0x01
ID_LAYOUT_OPTIONS = 0x02
ID_FIRMWARE_VERSION = 0x04


class ViaKeyboard:
    """Represents a VIA-capable keyboard"""

    def __init__(self, device_info: Dict):
        self.device_info = device_info
        self.device = None
        self.protocol_version = None
        self.uptime_ms = None
        self.firmware_version = None
        self.layer_count = None
        self.macro_count = None
        self.macro_buffer_size = None
        self.layout_options = None

    def open(self) -> bool:
        """Open connection to the keyboard"""
        try:
            self.device = hid.device()
            self.device.open_path(self.device_info['path'])
            return True
        except Exception as e:
            print(f"Error opening device: {e}", file=sys.stderr)
            return False

    def close(self):
        """Close connection to the keyboard"""
        if self.device:
            self.device.close()
            self.device = None

    def send_command(self, command_id: int, params: List[int] = None) -> Optional[bytearray]:
        """Send a command and receive response"""
        if not self.device:
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
            # Send command
            self.device.write(packet)

            # Receive response
            response = self.device.read(RAW_EPSIZE, timeout_ms=1000)

            if not response:
                return None

            # Check for unhandled command
            if response[0] == 0xFF:
                return None

            return bytearray(response)

        except Exception as e:
            print(f"Error during communication: {e}", file=sys.stderr)
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

    def __str__(self) -> str:
        """String representation of keyboard info"""
        lines = []
        lines.append("=" * 70)

        # Basic device info
        manufacturer = self.device_info.get('manufacturer_string', 'Unknown')
        product = self.device_info.get('product_string', 'Unknown')
        lines.append(f"Device: {manufacturer} {product}")

        # USB IDs
        vid = self.device_info.get('vendor_id', 0)
        pid = self.device_info.get('product_id', 0)
        lines.append(f"USB ID: {vid:04X}:{pid:04X}")

        # Serial number
        serial = self.device_info.get('serial_number', '')
        if serial:
            lines.append(f"Serial: {serial}")

        # Path
        path = self.device_info.get('path', b'').decode('utf-8', errors='ignore')
        lines.append(f"Path: {path}")

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


def find_via_keyboards(verbose=False) -> List[Dict]:
    """Find all VIA-capable keyboards connected to the system"""
    devices = hid.enumerate()
    via_keyboards = []

    for device in devices:
        # First try: Check for VIA usage page and usage ID (works on macOS/Windows)
        if device.get('usage_page') == VIA_USAGE_PAGE and \
           device.get('usage') == VIA_USAGE_ID:
            via_keyboards.append(device)
            continue

        # Second try: On Linux, hidapi often reports usage_page as 0
        # We need to probe devices that might be VIA keyboards
        usage_page = device.get('usage_page', 0)

        # Only probe if usage_page is 0 (unknown on Linux)
        if usage_page != 0:
            continue

        # Try to probe the device
        if verbose:
            vid = device.get('vendor_id', 0)
            pid = device.get('product_id', 0)
            interface = device.get('interface_number', -1)
            path = device.get('path', b'').decode('utf-8', errors='ignore')
            print(f"Probing {vid:04X}:{pid:04X} if:{interface} {path}...", end=' ')

        result = probe_via_device(device)

        if verbose:
            print("VIA!" if result else "no")

        if result:
            via_keyboards.append(device)

    return via_keyboards


def probe_via_device(device_info: Dict) -> bool:
    """Probe a device to see if it responds to VIA protocol"""
    try:
        device = hid.device()
        device.open_path(device_info['path'])

        # Try to get protocol version
        packet = bytearray(RAW_EPSIZE)
        packet[0] = CMD_GET_PROTOCOL_VERSION

        device.write(packet)
        response = device.read(RAW_EPSIZE, timeout_ms=500)

        device.close()

        # Check if we got a valid VIA response
        if response and len(response) >= 3:
            if response[0] == CMD_GET_PROTOCOL_VERSION:
                # Valid VIA response
                return True

        return False

    except Exception:
        # Failed to open or communicate - not a VIA device
        return False


def debug_list_all_hid_devices():
    """List all HID devices for debugging"""
    print("=" * 70)
    print("DEBUG MODE: Listing all HID devices")
    print("=" * 70)
    print()

    devices = hid.enumerate()

    if not devices:
        print("No HID devices found!")
        return

    print(f"Found {len(devices)} HID device(s) total\n")

    # Group by vendor/product
    device_map = {}
    for device in devices:
        vid = device.get('vendor_id', 0)
        pid = device.get('product_id', 0)
        key = (vid, pid)

        if key not in device_map:
            device_map[key] = []
        device_map[key].append(device)

    # Display grouped devices
    for (vid, pid), dev_list in sorted(device_map.items()):
        manufacturer = dev_list[0].get('manufacturer_string', 'Unknown')
        product = dev_list[0].get('product_string', 'Unknown')

        print(f"{manufacturer} {product}")
        print(f"  USB ID: {vid:04X}:{pid:04X}")
        print(f"  Interfaces: {len(dev_list)}")

        for i, dev in enumerate(dev_list, 1):
            usage_page = dev.get('usage_page', 0)
            usage = dev.get('usage', 0)
            interface = dev.get('interface_number', -1)
            path = dev.get('path', b'').decode('utf-8', errors='ignore')

            print(f"    [{i}] Interface: {interface}, Usage Page: 0x{usage_page:04X}, Usage: 0x{usage:02X}")

            # Check if this is VIA-capable
            if usage_page == VIA_USAGE_PAGE and usage == VIA_USAGE_ID:
                print(f"        *** VIA-CAPABLE (0x{VIA_USAGE_PAGE:04X}:0x{VIA_USAGE_ID:02X}) ***")

            if len(path) < 80:
                print(f"        Path: {path}")

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
    if '--help' in sys.argv or '-h' in sys.argv:
        print_help()

    print("QMK VIA Keyboard Scanner")
    print("=" * 70)
    print()

    # Debug mode - list all HID devices
    if debug_mode:
        debug_list_all_hid_devices()
        return 0

    # Find VIA keyboards
    print("Scanning for VIA-capable keyboards...")
    if verbose_mode:
        print()
    devices = find_via_keyboards(verbose=verbose_mode)

    if not devices:
        print("\nNo VIA-capable keyboards found.")
        print("\nMake sure:")
        print("  1. Your keyboard has RAW_ENABLE and VIA_ENABLE compiled in")
        print("  2. The keyboard is properly connected")
        print("  3. You have permissions to access HID devices")
        print("     (Linux: check udev rules)")
        print("\nTip: Run with --debug to see all HID devices")
        return 1

    print(f"\nFound {len(devices)} VIA-capable keyboard(s)\n")

    # Query each keyboard
    for i, device_info in enumerate(devices, 1):
        print(f"\nKeyboard #{i}:")
        print()

        keyboard = ViaKeyboard(device_info)

        if not keyboard.open():
            print("Failed to open device")
            continue

        # Query information
        keyboard.query_info()

        # Display information
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
