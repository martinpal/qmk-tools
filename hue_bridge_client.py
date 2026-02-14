#!/usr/bin/env python3
"""
Philips Hue Bridge Client for QMK Overlay Integration

Connects to Philips Hue bridge and monitors a specific light's brightness.
Provides dynamic brightness scaling for boblight LEDs based on Hue light state
and solar elevation (time of day).
"""

import threading
import time
from typing import Optional
from datetime import datetime
import requests

try:
    from astral import LocationInfo
    from astral.sun import elevation
    ASTRAL_AVAILABLE = True
except ImportError:
    ASTRAL_AVAILABLE = False


class HueBridgeClient:
    """Client for polling Philips Hue bridge and providing brightness scaling"""

    def __init__(self,
                 bridge_ip: Optional[str] = None,
                 light_name: str = "Velké světlo v obýváku",
                 min_brightness: float = 0.25,
                 poll_interval: float = 5.0,
                 auto_discover: bool = True,
                 latitude: float = 49.19,
                 longitude: float = 16.61,
                 use_solar: bool = True):
        """
        Initialize Hue bridge client

        Args:
            bridge_ip: Manual bridge IP address (overrides auto-discovery)
            light_name: Name of the Hue light to monitor
            min_brightness: Minimum brightness when light is off (0.0-1.0, default: 0.25)
            poll_interval: Polling frequency in seconds (default: 5.0)
            auto_discover: Enable auto-discovery if bridge_ip not provided
            latitude: Latitude for solar calculations (default: 49.19 = Brno, CZ)
            longitude: Longitude for solar calculations (default: 16.61 = Brno, CZ)
            use_solar: Enable solar brightness calculations (default: True)
        """
        self.bridge_ip = bridge_ip
        self.light_name = light_name
        self.min_brightness = max(0.0, min(1.0, min_brightness))
        self.poll_interval = poll_interval
        self.auto_discover = auto_discover
        self.latitude = latitude
        self.longitude = longitude
        self.use_solar = use_solar and ASTRAL_AVAILABLE

        if self.use_solar and not ASTRAL_AVAILABLE:
            print("[HUE] Warning: Solar brightness requested but astral library not available")
            print("[HUE] Install with: pip install astral")
            self.use_solar = False

        # Create LocationInfo object for solar calculations
        if self.use_solar:
            self.location = LocationInfo("User Location", "Region", "UTC", self.latitude, self.longitude)
        else:
            self.location = None

        self.bridge = None
        self._connected = False
        self._running = False
        self._poll_thread = None
        self._lock = threading.Lock()
        self._brightness_scale = 1.0  # Default to 100% if Hue unavailable

    @property
    def brightness_scale(self) -> float:
        """
        Current brightness scale (thread-safe)

        Returns:
            Float between min_brightness and 1.0
        """
        with self._lock:
            return self._brightness_scale

    @property
    def connected(self) -> bool:
        """Connection status"""
        with self._lock:
            return self._connected

    def connect(self) -> bool:
        """
        Connect to Hue bridge (with auto-discovery or manual IP)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Import phue here to provide better error message if missing
            try:
                from phue import Bridge
            except ImportError:
                print("[HUE] Error: phue library not found")
                print("[HUE] Install with: pip install phue")
                return False

            # Determine bridge IP
            if self.bridge_ip is None and self.auto_discover:
                print("[HUE] Auto-discovering Hue bridge...")
                discovered_ip = self._discover_bridge()
                if discovered_ip:
                    self.bridge_ip = discovered_ip
                    print(f"[HUE] Discovered bridge at {self.bridge_ip}")
                else:
                    print("[HUE] Auto-discovery failed")
                    return False
            elif self.bridge_ip is None:
                print("[HUE] No bridge IP provided and auto-discovery disabled")
                return False

            # Connect to bridge
            print(f"[HUE] Connecting to bridge at {self.bridge_ip}...")
            self.bridge = Bridge(self.bridge_ip)

            # This will prompt to press button if not authenticated
            # Credentials are saved to ~/.python_hue automatically
            self.bridge.connect()

            # Verify we can read lights
            lights = self.bridge.get_light_objects('name')
            if self.light_name not in lights:
                print(f"[HUE] Warning: Light '{self.light_name}' not found")
                print(f"[HUE] Available lights: {list(lights.keys())}")
                print(f"[HUE] Continuing anyway (will use 100% brightness)")

            with self._lock:
                self._connected = True

            print(f"[HUE] Connected successfully")
            return True

        except Exception as e:
            print(f"[HUE] Connection failed: {e}")
            with self._lock:
                self._connected = False
            return False

    def disconnect(self):
        """Disconnect from Hue bridge"""
        with self._lock:
            self._connected = False
            self.bridge = None

    def start_polling(self):
        """Start background polling thread"""
        if self._running:
            print("[HUE] Polling already running")
            return

        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        print(f"[HUE] Started polling every {self.poll_interval}s")

    def stop_polling(self):
        """Stop background polling thread"""
        if not self._running:
            return

        print("[HUE] Stopping polling thread...")
        self._running = False

        if self._poll_thread:
            self._poll_thread.join(timeout=self.poll_interval + 1.0)
            self._poll_thread = None

        print("[HUE] Polling stopped")

    def _discover_bridge(self) -> Optional[str]:
        """
        Auto-discover bridge IP using Philips Hue discovery service

        Returns:
            Bridge IP address or None if not found
        """
        try:
            # Use official Philips Hue discovery service
            response = requests.get('https://discovery.meethue.com/', timeout=5.0)
            response.raise_for_status()
            bridges = response.json()

            if bridges and len(bridges) > 0:
                return bridges[0]['internalipaddress']
            else:
                print("[HUE] No bridges found via discovery service")
                return None

        except Exception as e:
            print(f"[HUE] Discovery error: {e}")
            return None

    def _poll_loop(self):
        """Background thread polling loop with error recovery"""
        retry_delay = 1.0  # Start with 1 second
        max_retry_delay = 30.0

        while self._running:
            try:
                if self._connected:
                    # Update brightness from Hue
                    self._update_brightness()
                    retry_delay = 1.0  # Reset on success
                else:
                    # Try to reconnect
                    print(f"[HUE] Attempting to reconnect...")
                    if self.connect():
                        print(f"[HUE] Reconnected successfully")
                        retry_delay = 1.0
                    else:
                        print(f"[HUE] Reconnection failed, retry in {retry_delay}s")
                        time.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, max_retry_delay)
                        continue

            except Exception as e:
                print(f"[HUE] Polling error: {e}")
                with self._lock:
                    self._connected = False
                    # Set brightness to 100% (fail-safe)
                    self._brightness_scale = 1.0

            # Wait for next poll
            time.sleep(self.poll_interval)

    def _update_brightness(self):
        """
        Query Hue light brightness and update brightness_scale

        Raises:
            Exception on error (caught by _poll_loop)
        """
        try:
            # Get light state
            is_on = self.bridge.get_light(self.light_name, 'on')
            bri = self.bridge.get_light(self.light_name, 'bri')

            # Calculate brightness scale
            scale = self._calculate_scale(bri, is_on)

            # Update shared state (thread-safe)
            with self._lock:
                self._brightness_scale = scale

        except Exception as e:
            # Check if light not found
            if "not found" in str(e).lower() or "not available" in str(e).lower():
                print(f"[HUE] Light '{self.light_name}' not available")
                # Try to list available lights for debugging
                try:
                    lights = self.bridge.get_light_objects('name')
                    print(f"[HUE] Available lights: {list(lights.keys())}")
                except:
                    pass
            else:
                print(f"[HUE] Error reading light: {e}")

            # Fail-safe: default to 100% brightness
            with self._lock:
                self._brightness_scale = 1.0

            # Re-raise to trigger reconnection logic
            raise

    def _calculate_solar_brightness(self) -> float:
        """
        Calculate brightness based on solar elevation (sun position)

        Returns:
            Brightness scale (min_brightness to 1.0) based on sun elevation

        Algorithm:
            - Sun below horizon (elevation < 0°) → min_brightness
            - Sun at horizon (elevation = 0°) → min_brightness
            - Sun at peak (elevation ~60° for Brno) → 1.0
            - Linear interpolation between 0° and 60°
        """
        if not self.use_solar:
            return self.min_brightness

        try:
            # Get current sun elevation in degrees
            now = datetime.now()
            sun_elevation = elevation(observer=self.location.observer, dateandtime=now)

            # Map elevation to brightness
            # Below horizon: minimum brightness
            if sun_elevation < 0:
                return self.min_brightness

            # Peak elevation for Brno is around 60-65° (summer solstice)
            # Use 60° as reference for 100% brightness
            peak_elevation = 60.0

            # Linear mapping from 0° to peak_elevation
            scale = self.min_brightness + (1.0 - self.min_brightness) * (sun_elevation / peak_elevation)

            # Clamp to valid range
            return max(self.min_brightness, min(1.0, scale))

        except Exception as e:
            print(f"[HUE] Error calculating solar brightness: {e}")
            return self.min_brightness

    def _calculate_scale(self, hue_bri: int, is_on: bool) -> float:
        """
        Calculate brightness scale from Hue brightness value and solar elevation

        Uses max(hue_brightness, solar_brightness) to combine both sources.

        Args:
            hue_bri: Hue brightness (1-254, or 0 if off)
            is_on: Light on/off state

        Returns:
            Brightness scale (min_brightness to 1.0)

        Formula:
            hue_scale = min_brightness + (1.0 - min_brightness) * (hue_bri / 254)
            solar_scale = calculated from sun elevation
            final_scale = max(hue_scale, solar_scale)

        Examples:
            - Hue off, night → 0.25 (min_brightness)
            - Hue off, daytime → solar brightness (e.g., 0.7)
            - Hue at 50%, night → 0.625
            - Hue at 100%, any time → 1.0
        """
        # Calculate Hue light brightness
        if not is_on or hue_bri == 0:
            hue_scale = self.min_brightness
        else:
            # Linear interpolation: min + (max - min) * (value / 254)
            hue_scale = self.min_brightness + (1.0 - self.min_brightness) * (hue_bri / 254.0)
            hue_scale = max(self.min_brightness, min(1.0, hue_scale))

        # Calculate solar brightness if enabled
        solar_scale = self._calculate_solar_brightness()

        # Return the brighter of the two
        return max(hue_scale, solar_scale)
