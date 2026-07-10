#!/usr/bin/env python3
"""
Home Assistant Client for QMK Overlay Integration

Connects to a Home Assistant instance and monitors a specific light entity's
brightness. Provides dynamic brightness scaling for boblight LEDs based on the
Home Assistant light state and solar elevation (time of day).
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


class HomeAssistantClient:
    """Client for polling Home Assistant and providing brightness scaling"""

    def __init__(self,
                 base_url: str = "http://homeassistant.local:8123",
                 token: Optional[str] = None,
                 entity_id: str = "light.velke_svetlo_v_obyvaku",
                 color_entity_id: Optional[str] = None,
                 min_brightness: float = 0.25,
                 poll_interval: float = 5.0,
                 latitude: float = 49.19,
                 longitude: float = 16.61,
                 use_solar: bool = True):
        """
        Initialize Home Assistant client

        Args:
            base_url: Home Assistant base URL (e.g. http://homeassistant.local:8123)
            token: Long-lived access token (or set via HASS_TOKEN env var)
            entity_id: Light entity_id to monitor for brightness (e.g. light.living_room)
            color_entity_id: Light entity_id to control color on (defaults to entity_id)
            min_brightness: Minimum brightness when light is off (0.0-1.0, default: 0.25)
            poll_interval: Polling frequency in seconds (default: 5.0)
            latitude: Latitude for solar calculations (default: 49.19 = Brno, CZ)
            longitude: Longitude for solar calculations (default: 16.61 = Brno, CZ)
            use_solar: Enable solar brightness calculations (default: True)
        """
        import os
        self.base_url = base_url.rstrip("/")
        self.token = token or os.environ.get("HASS_TOKEN")
        self.entity_id = entity_id
        self.color_entity_id = color_entity_id or entity_id
        self.min_brightness = max(0.0, min(1.0, min_brightness))
        self.poll_interval = poll_interval
        self.latitude = latitude
        self.longitude = longitude
        self.use_solar = use_solar and ASTRAL_AVAILABLE

        if self.use_solar and not ASTRAL_AVAILABLE:
            print("[HA] Warning: Solar brightness requested but astral library not available")
            print("[HA] Install with: pip install astral")
            self.use_solar = False

        # Create LocationInfo object for solar calculations
        if self.use_solar:
            self.location = LocationInfo("User Location", "Region", "UTC", self.latitude, self.longitude)
        else:
            self.location = None

        self._connected = False
        self._running = False
        self._poll_thread = None
        self._lock = threading.Lock()
        self._brightness_scale = 1.0  # Default to 100% if HA unavailable

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
        Verify connection to Home Assistant

        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.token:
                print("[HA] Error: No access token provided")
                print("[HA] Create a long-lived access token in Home Assistant")
                print("[HA] Profile -> Long-Lived Access Tokens -> Create Token")
                print("[HA] Then pass it via --ha-token or HASS_TOKEN env var")
                return False

            # Verify connectivity by fetching the light entity state
            print(f"[HA] Connecting to Home Assistant at {self.base_url}...")
            state = self._get_entity_state()

            if state is None:
                print(f"[HA] Warning: Entity '{self.entity_id}' not found")
                print("[HA] Continuing anyway (will use 100% brightness)")
            else:
                attrs = state.get("attributes", {})
                friendly_name = attrs.get("friendly_name", self.entity_id)
                current_state = state.get("state", "unknown")
                print(f"[HA] Found light '{friendly_name}' (currently {current_state})")

            with self._lock:
                self._connected = True

            print(f"[HA] Connected successfully")
            return True

        except Exception as e:
            print(f"[HA] Connection failed: {e}")
            with self._lock:
                self._connected = False
            return False

    def disconnect(self):
        """Disconnect from Home Assistant"""
        with self._lock:
            self._connected = False

    def start_polling(self):
        """Start background polling thread"""
        if self._running:
            print("[HA] Polling already running")
            return

        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        print(f"[HA] Started polling every {self.poll_interval}s")

    def stop_polling(self):
        """Stop background polling thread"""
        if not self._running:
            return

        print("[HA] Stopping polling thread...")
        self._running = False

        if self._poll_thread:
            self._poll_thread.join(timeout=self.poll_interval + 1.0)
            self._poll_thread = None

        print("[HA] Polling stopped")

    def _get_entity_state(self, entity_id: Optional[str] = None) -> Optional[dict]:
        """
        Fetch the current state of a light entity

        Args:
            entity_id: Entity to query (defaults to the brightness entity)

        Returns:
            State dict (with 'state' and 'attributes') or None if not found
        """
        entity = entity_id or self.entity_id
        url = f"{self.base_url}/api/states/{entity}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        response = requests.get(url, headers=headers, timeout=5.0)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def _call_service(self, domain: str, service: str, data: dict):
        """Call a Home Assistant service via the REST API"""
        url = f"{self.base_url}/api/services/{domain}/{service}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=headers, json=data, timeout=5.0)
        response.raise_for_status()
        return response.json()

    def get_light_color_state(self) -> Optional[dict]:
        """
        Capture the current state of the color light for later restoration.

        Returns:
            Dict with 'state', 'brightness', 'rgb_color', 'color_temp',
            or None if the entity can't be read.
        """
        try:
            state = self._get_entity_state(self.color_entity_id)
            if state is None:
                print(f"[HA] Color entity '{self.color_entity_id}' not found")
                return None

            attrs = state.get("attributes", {})
            return {
                "state": state.get("state", "off"),
                "brightness": attrs.get("brightness"),
                "rgb_color": attrs.get("rgb_color"),
                "color_temp": attrs.get("color_temp"),
            }
        except Exception as e:
            print(f"[HA] Error reading color light state: {e}")
            return None

    def set_light_color(self, r: int, g: int, b: int, brightness: Optional[int] = None):
        """
        Set the color light to an RGB color.

        Args:
            r: Red 0-255
            g: Green 0-255
            b: Blue 0-255
            brightness: Optional brightness 0-255 (if None, keep current)
        """
        try:
            data = {
                "entity_id": self.color_entity_id,
                "rgb_color": [r, g, b],
            }
            if brightness is not None:
                data["brightness"] = brightness
            self._call_service("light", "turn_on", data)
            print(f"[HA] Set light color to RGB({r}, {g}, {b})")
        except Exception as e:
            print(f"[HA] Error setting light color: {e}")

    def restore_light_state(self, saved_state: dict):
        """
        Restore a previously captured light state (from get_light_color_state).

        Args:
            saved_state: Dict from get_light_color_state()
        """
        try:
            if saved_state.get("state") == "off":
                self._call_service("light", "turn_off", {
                    "entity_id": self.color_entity_id
                })
                print(f"[HA] Restored light state: off")
                return

            data = {"entity_id": self.color_entity_id}

            # Prefer rgb_color, fall back to color_temp, then just turn on
            if saved_state.get("rgb_color") is not None:
                data["rgb_color"] = saved_state["rgb_color"]
            elif saved_state.get("color_temp") is not None:
                data["color_temp"] = saved_state["color_temp"]

            if saved_state.get("brightness") is not None:
                data["brightness"] = saved_state["brightness"]

            self._call_service("light", "turn_on", data)
            print(f"[HA] Restored light state: on, "
                  f"rgb={saved_state.get('rgb_color')}, "
                  f"brightness={saved_state.get('brightness')}")
        except Exception as e:
            print(f"[HA] Error restoring light state: {e}")

    def _poll_loop(self):
        """Background thread polling loop with error recovery"""
        retry_delay = 1.0  # Start with 1 second
        max_retry_delay = 30.0

        while self._running:
            try:
                if self._connected:
                    # Update brightness from Home Assistant
                    self._update_brightness()
                    retry_delay = 1.0  # Reset on success
                else:
                    # Try to reconnect
                    print(f"[HA] Attempting to reconnect...")
                    if self.connect():
                        print(f"[HA] Reconnected successfully")
                        retry_delay = 1.0
                    else:
                        print(f"[HA] Reconnection failed, retry in {retry_delay}s")
                        time.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, max_retry_delay)
                        continue

            except Exception as e:
                print(f"[HA] Polling error: {e}")
                with self._lock:
                    self._connected = False
                    # Set brightness to 100% (fail-safe)
                    self._brightness_scale = 1.0

            # Wait for next poll
            time.sleep(self.poll_interval)

    def _update_brightness(self):
        """
        Query Home Assistant light brightness and update brightness_scale

        Raises:
            Exception on error (caught by _poll_loop)
        """
        try:
            # Get light state
            state = self._get_entity_state()

            if state is None:
                print(f"[HA] Entity '{self.entity_id}' not available")
                # Fail-safe: default to 100% brightness
                with self._lock:
                    self._brightness_scale = 1.0
                # Re-raise to trigger reconnection logic
                raise ValueError(f"Entity '{self.entity_id}' not found")

            is_on = state.get("state", "off") == "on"
            bri = state.get("attributes", {}).get("brightness", 0)

            # Calculate brightness scale
            scale = self._calculate_scale(bri, is_on)

            # Update shared state (thread-safe)
            with self._lock:
                self._brightness_scale = scale

        except Exception as e:
            # Check if entity not found
            if "not found" in str(e).lower() or "not available" in str(e).lower():
                print(f"[HA] Entity '{self.entity_id}' not available")
            else:
                print(f"[HA] Error reading light: {e}")

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
            print(f"[HA] Error calculating solar brightness: {e}")
            return self.min_brightness

    def _calculate_scale(self, light_bri: int, is_on: bool) -> float:
        """
        Calculate brightness scale from light brightness value and solar elevation

        Uses max(light_brightness, solar_brightness) to combine both sources.

        Args:
            light_bri: Home Assistant brightness (0-255, or 0/None if off)
            is_on: Light on/off state

        Returns:
            Brightness scale (min_brightness to 1.0)

        Formula:
            light_scale = min_brightness + (1.0 - min_brightness) * (light_bri / 255)
            solar_scale = calculated from sun elevation
            final_scale = max(light_scale, solar_scale)

        Examples:
            - Light off, night → 0.25 (min_brightness)
            - Light off, daytime → solar brightness (e.g., 0.7)
            - Light at 50%, night → 0.625
            - Light at 100%, any time → 1.0
        """
        # Calculate light brightness
        if not is_on or not light_bri or light_bri == 0:
            light_scale = self.min_brightness
        else:
            # Home Assistant brightness range is 0-255
            # Linear interpolation: min + (max - min) * (value / 255)
            light_scale = self.min_brightness + (1.0 - self.min_brightness) * (light_bri / 255.0)
            light_scale = max(self.min_brightness, min(1.0, light_scale))

        # Calculate solar brightness if enabled
        solar_scale = self._calculate_solar_brightness()

        # Return the brighter of the two
        return max(light_scale, solar_scale)
