#!/usr/bin/env python3
"""Test boblight priority system"""

import socket
import time

def test_priority(priority, color_name, r, g, b):
    """Test setting a color at a specific priority"""
    try:
        # Connect to boblightd
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(('localhost', 19333))

        # Handshake
        sock.sendall(b"hello\n")
        response = sock.recv(4096).decode('utf-8')
        print(f"[BOBLIGHT] Handshake: {response.strip()}")

        # Set priority
        sock.sendall(f"set priority {priority}\n".encode('utf-8'))
        print(f"[BOBLIGHT] Set priority to {priority}")

        # Get lights
        sock.sendall(b"get lights\n")
        response = sock.recv(4096).decode('utf-8')
        print(f"[BOBLIGHT] Lights: {response.strip()}")

        # Parse light names
        lines = response.strip().split('\n')
        light_names = []
        for line in lines[1:]:
            if line.startswith("light "):
                light_names.append(line.split()[1])

        # Set color for all lights
        print(f"Setting {color_name} (priority {priority})...")
        for light_name in light_names:
            command = f"set light {light_name} rgb {r:.6f} {g:.6f} {b:.6f}\n"
            sock.sendall(command.encode('utf-8'))

        # Sync
        sock.sendall(b"sync\n")
        print(f"✓ {color_name} set successfully")

        sock.close()
        return True

    except Exception as e:
        print(f"✗ Error: {e}")
        return False

if __name__ == "__main__":
    print("Testing boblight priority system")
    print("=" * 50)

    # Test low priority (should be overridden)
    print("\n1. Setting RED at priority 100 (low)")
    test_priority(100, "RED", 1.0, 0.0, 0.0)
    time.sleep(2)

    # Test medium priority
    print("\n2. Setting GREEN at priority 200 (medium)")
    test_priority(200, "GREEN", 0.0, 1.0, 0.0)
    time.sleep(2)

    # Test high priority (should override everything)
    print("\n3. Setting BLUE at priority 255 (high)")
    test_priority(255, "BLUE", 0.0, 0.0, 1.0)
    time.sleep(2)

    # Clear
    print("\n4. Clearing (BLACK) at priority 255")
    test_priority(255, "BLACK", 0.0, 0.0, 0.0)

    print("\nDone!")
