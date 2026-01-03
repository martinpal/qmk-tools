#!/usr/bin/env python3
"""
Test script for GNOME Shell layer indicator D-Bus interface
"""

import time

try:
    import dbus
    bus = dbus.SessionBus()
    print("D-Bus session bus connected")

    # Try to get the indicator object
    try:
        obj = bus.get_object('com.qmk.LayerIndicator', '/com/qmk/LayerIndicator')
        proxy = dbus.Interface(obj, 'com.qmk.LayerIndicator')
        print("Connected to QMK Layer Indicator extension")

        # Get current layer
        current = proxy.GetLayer()
        print(f"Current layer: {current[0]} ({current[1]})")

        # Test updating the indicator
        test_layers = [
            ("Base", "#787878"),
            ("Game", "#00ffff"),
            ("Lower", "#ff3232"),
            ("Raise", "#6496ff"),
            ("Adjust", "#32ff32"),
        ]

        print("\nTesting layer updates...")
        for layer_name, layer_color in test_layers:
            print(f"Setting: {layer_name} ({layer_color})")
            proxy.SetLayer(layer_name, layer_color)
            time.sleep(1)

        print("\nTest complete!")

    except dbus.DBusException as e:
        print(f"Error: Could not connect to QMK Layer Indicator extension")
        print(f"Make sure the GNOME Shell extension is enabled and loaded")
        print(f"Error details: {e}")

except ImportError:
    print("Error: dbus-python not installed")
    print("Install with: pip install dbus-python")
