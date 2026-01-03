#!/usr/bin/env python3
"""
Corsair Mouse Monitor for ckb-next Integration

Monitors Corsair mouse events via ckb-next daemon and provides
callbacks for integration with QMK keyboard.

Works cooperatively with ckb-next GUI - uses dedicated notification
node to avoid conflicts.
"""

import threading
import time
import os
from typing import Callable, Dict, List, Optional


class CorsairMouseMonitor:
    """
    Monitor Corsair mouse events via ckb-next daemon.

    Designed to work cooperatively with ckb-next GUI:
    - Uses dedicated notification node (notify5 by default)
    - RGB changes are temporary and restore previous state
    - Button monitoring doesn't interfere with normal operation
    """

    def __init__(self, device_path: str = '/dev/input/ckb1', notify_node: int = 5):
        """
        Initialize mouse monitor.

        Args:
            device_path: Path to ckb device (e.g., '/dev/input/ckb1')
            notify_node: Notification node number (1-9, default 5)
        """
        self.device_path = device_path
        self.notify_node = notify_node
        self.notify_path = f'{device_path}/notify{notify_node}'
        self.cmd_path = f'{device_path}/cmd'

        # Callback lists
        self.callbacks: Dict[str, List[Callable]] = {
            'button_press': [],
            'button_release': [],
            'dpi_change': [],
        }

        # Thread management
        self.running = False
        self.thread: Optional[threading.Thread] = None

        # State tracking
        self.current_rgb: Dict[str, str] = {}
        self.rgb_lock = threading.Lock()

    def on_button_press(self, callback: Callable[[str], None]) -> None:
        """
        Register callback for button press events.

        Args:
            callback: Function that takes button name (e.g., 'mouse4')
        """
        self.callbacks['button_press'].append(callback)

    def on_button_release(self, callback: Callable[[str], None]) -> None:
        """
        Register callback for button release events.

        Args:
            callback: Function that takes button name (e.g., 'mouse4')
        """
        self.callbacks['button_release'].append(callback)

    def on_dpi_change(self, callback: Callable[[int], None]) -> None:
        """
        Register callback for DPI change events.

        Args:
            callback: Function that takes DPI stage (0-5)
        """
        self.callbacks['dpi_change'].append(callback)

    def start(self) -> bool:
        """
        Start monitoring in background thread.

        Returns:
            True if started successfully, False otherwise
        """
        # Check if device exists
        if not os.path.exists(self.device_path):
            print(f"Error: Device {self.device_path} not found")
            print("Is ckb-next-daemon running?")
            return False

        # Enable our dedicated notification node
        try:
            self._enable_notifications()
        except Exception as e:
            print(f"Error enabling notifications: {e}")
            return False

        # Start monitoring thread
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()

        print(f"Corsair mouse monitor started on {self.device_path}")
        print(f"Using notification node: notify{self.notify_node}")
        return True

    def stop(self) -> None:
        """Stop monitoring and cleanup."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)

        # Close notification node
        try:
            with open(self.cmd_path, 'w') as cmd:
                cmd.write(f'notifyoff {self.notify_node}\n')
                cmd.flush()
        except Exception as e:
            print(f"Warning: Could not close notification node: {e}")

        print("Corsair mouse monitor stopped")

    def _enable_notifications(self) -> None:
        """Enable ckb notifications for mouse buttons on our dedicated node."""
        with open(self.cmd_path, 'w') as cmd:
            # Activate device (required for SW control)
            cmd.write('active\n')

            # Create our dedicated notification node
            cmd.write(f'notifyon {self.notify_node}\n')

            # Enable notifications for all mouse buttons on our node
            # @N prefix routes notifications to that specific node
            cmd.write(f'@{self.notify_node} notify mouse1 mouse2 mouse3 mouse4 mouse5 mouse6 mouse7 mouse8 dpi sniper\n')

            cmd.flush()

        # Give daemon time to create the notification node
        time.sleep(0.1)

        # Verify notification node was created
        if not os.path.exists(self.notify_path):
            raise RuntimeError(f"Failed to create notification node: {self.notify_path}")

    def _monitor_loop(self) -> None:
        """Main monitoring loop - runs in background thread."""
        retry_count = 0
        max_retries = 5

        while self.running:
            try:
                with open(self.notify_path, 'r', buffering=1) as notify:
                    retry_count = 0  # Reset on successful open

                    while self.running:
                        line = notify.readline()
                        if not line:
                            time.sleep(0.01)
                            continue

                        self._handle_event(line.strip())

            except FileNotFoundError:
                retry_count += 1
                if retry_count > max_retries:
                    print(f"Error: Notification node disappeared after {max_retries} retries")
                    self.running = False
                    break

                print(f"Warning: Notification node not found, retrying ({retry_count}/{max_retries})...")
                time.sleep(1)

                # Try to recreate notification node
                try:
                    self._enable_notifications()
                except Exception as e:
                    print(f"Error recreating notification node: {e}")

            except Exception as e:
                print(f"Error in monitor loop: {e}")
                time.sleep(1)

    def _handle_event(self, line: str) -> None:
        """
        Parse and dispatch event from notification line.

        Args:
            line: Notification line (e.g., "key +mouse4")
        """
        if not line:
            return

        parts = line.split()
        if len(parts) < 2:
            return

        event_type = parts[0]

        if event_type == 'key':
            # Key press/release event
            key_state = parts[1]
            if key_state.startswith('+'):
                button = key_state[1:]
                for cb in self.callbacks['button_press']:
                    try:
                        cb(button)
                    except Exception as e:
                        print(f"Error in button_press callback: {e}")
            elif key_state.startswith('-'):
                button = key_state[1:]
                for cb in self.callbacks['button_release']:
                    try:
                        cb(button)
                    except Exception as e:
                        print(f"Error in button_release callback: {e}")

        elif event_type == 'dpisel':
            # DPI change event
            try:
                dpi_stage = int(parts[1])
                for cb in self.callbacks['dpi_change']:
                    try:
                        cb(dpi_stage)
                    except Exception as e:
                        print(f"Error in dpi_change callback: {e}")
            except (ValueError, IndexError):
                pass

    def set_rgb(self, zone: str, color: str) -> bool:
        """
        Set RGB color on mouse.

        Note: This will override any running animations. Use set_rgb_temporary()
        for non-intrusive color changes.

        Args:
            zone: 'all', 'logo', 'scroll', or specific zone name
            color: Hex color string (e.g., 'ff0000' for red)

        Returns:
            True if successful, False otherwise
        """
        try:
            with open(self.cmd_path, 'w') as cmd:
                cmd.write('active\n')
                if zone == 'all':
                    cmd.write(f'rgb {color}\n')
                else:
                    cmd.write(f'rgb {zone}:{color}\n')
                cmd.flush()

            # Track current RGB state
            with self.rgb_lock:
                self.current_rgb[zone] = color

            return True
        except Exception as e:
            print(f"Error setting RGB: {e}")
            return False

    def set_rgb_temporary(self, zone: str, color: str, duration: float = 1.0) -> bool:
        """
        Set RGB color temporarily, then restore to previous state.

        This is less intrusive than set_rgb() as it allows animations to continue.

        Args:
            zone: 'all', 'logo', 'scroll', or specific zone name
            color: Hex color string (e.g., 'ff0000' for red)
            duration: Seconds to show the color before restoring

        Returns:
            True if successful, False otherwise
        """
        # Get current color (best effort - may not match reality if animations running)
        with self.rgb_lock:
            original_color = self.current_rgb.get(zone, None)

        # Set new color
        if not self.set_rgb(zone, color):
            return False

        # Schedule restoration
        def restore():
            # If we knew the original color, restore it
            # Otherwise, don't restore (let animation continue)
            if original_color:
                self.set_rgb(zone, original_color)

        timer = threading.Timer(duration, restore)
        timer.daemon = True
        timer.start()

        return True

    def flash_rgb(self, zone: str, color: str, times: int = 3, interval: float = 0.2) -> bool:
        """
        Flash RGB color multiple times.

        Args:
            zone: 'all', 'logo', 'scroll', or specific zone name
            color: Hex color string to flash
            times: Number of flashes
            interval: Seconds between flashes

        Returns:
            True if successful, False otherwise
        """
        def flash_sequence():
            for _ in range(times):
                self.set_rgb(zone, color)
                time.sleep(interval)
                self.set_rgb(zone, '000000')  # Black
                time.sleep(interval)

        thread = threading.Thread(target=flash_sequence, daemon=True)
        thread.start()
        return True

    def get_device_info(self) -> Dict[str, str]:
        """
        Get basic device information.

        Returns:
            Dictionary with device info (model, serial, features, etc.)
        """
        info = {}

        try:
            with open(f'{self.device_path}/model', 'r') as f:
                info['model'] = f.read().strip()
        except:
            pass

        try:
            with open(f'{self.device_path}/serial', 'r') as f:
                info['serial'] = f.read().strip()
        except:
            pass

        try:
            with open(f'{self.device_path}/features', 'r') as f:
                info['features'] = f.read().strip()
        except:
            pass

        try:
            with open(f'{self.device_path}/fwversion', 'r') as f:
                info['firmware'] = f.read().strip()
        except:
            pass

        return info


def main():
    """Example usage and testing."""
    import sys

    print("Corsair Mouse Monitor - Test Mode")
    print("=" * 50)

    # Check if device exists
    if not os.path.exists('/dev/input/ckb1'):
        print("Error: /dev/input/ckb1 not found")
        print("Is ckb-next-daemon running?")
        sys.exit(1)

    # Create monitor
    mouse = CorsairMouseMonitor()

    # Show device info
    info = mouse.get_device_info()
    print("\nDevice Information:")
    for key, value in info.items():
        print(f"  {key}: {value}")
    print()

    # Register callbacks
    def on_press(button: str):
        print(f"Button pressed: {button}")

        # Flash red on button press
        if button.startswith('mouse'):
            mouse.flash_rgb('all', 'ff0000', times=2, interval=0.1)

    def on_release(button: str):
        print(f"Button released: {button}")

    def on_dpi(stage: int):
        print(f"DPI changed to stage: {stage}")
        # Flash different colors for different DPI stages
        colors = ['00ff00', '0000ff', 'ff00ff', 'ffff00', 'ff8800']
        color = colors[stage % len(colors)]
        mouse.flash_rgb('all', color, times=1, interval=0.3)

    mouse.on_button_press(on_press)
    mouse.on_button_release(on_release)
    mouse.on_dpi_change(on_dpi)

    # Start monitoring
    if not mouse.start():
        print("Failed to start monitoring")
        sys.exit(1)

    print("\nMonitoring mouse events...")
    print("Press Ctrl+C to exit")
    print()

    try:
        # Keep running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        mouse.stop()
        print("Goodbye!")


if __name__ == "__main__":
    main()
