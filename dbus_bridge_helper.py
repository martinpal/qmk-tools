#!/usr/bin/env python3
"""
D-Bus Bridge Helper - runs as user to forward layer updates to GNOME Shell extension
This listens on a Unix socket and forwards messages to the D-Bus session bus.
"""

import socket
import os
import sys
import time

try:
    import dbus
except ImportError:
    print("Error: python3-dbus not installed")
    print("Install with: sudo apt install python3-dbus")
    sys.exit(1)

SOCKET_PATH = '/tmp/qmk-dbus-bridge.sock'

def setup_dbus():
    """Connect to the GNOME Shell extension via D-Bus"""
    try:
        bus = dbus.SessionBus()
        obj = bus.get_object('com.qmk.LayerIndicator', '/com/qmk/LayerIndicator')
        proxy = dbus.Interface(obj, 'com.qmk.LayerIndicator')
        print("Connected to GNOME Shell extension")
        return proxy
    except Exception as e:
        print(f"Error connecting to D-Bus: {e}")
        return None

def main():
    # Remove old socket if it exists
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    # Create Unix socket
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o666)  # Allow anyone to connect
    sock.listen(1)

    print(f"D-Bus bridge listening on {SOCKET_PATH}")

    # Connect to D-Bus
    proxy = setup_dbus()
    if not proxy:
        print("Failed to connect to GNOME Shell extension")
        return 1

    try:
        while True:
            conn, _ = sock.accept()
            try:
                # Keep connection alive and process multiple messages
                while True:
                    data = conn.recv(1024)
                    if not data:
                        break  # Connection closed by client

                    message = data.decode('utf-8').strip()
                    if message:
                        # Parse message: "layer_name:layer_color"
                        parts = message.split(':', 1)
                        if len(parts) == 2:
                            layer_name, layer_color = parts
                            try:
                                proxy.SetLayer(layer_name, layer_color)
                            except dbus.exceptions.DBusException as e:
                                # Extension was reloaded, try to reconnect
                                print(f"D-Bus error: {e}, attempting to reconnect...")
                                proxy = setup_dbus()
                                if proxy:
                                    try:
                                        proxy.SetLayer(layer_name, layer_color)
                                        print("Reconnected successfully")
                                    except Exception as e2:
                                        print(f"Reconnection failed: {e2}")
                                else:
                                    print("Reconnection failed")
            except Exception as e:
                print(f"Error processing connection: {e}")
            finally:
                conn.close()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        sock.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)

if __name__ == '__main__':
    sys.exit(main() or 0)
