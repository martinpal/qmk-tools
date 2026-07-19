#!/usr/bin/env python3
"""
Home Assistant Client for QMK Overlay Integration

Connects to Home Assistant via WebSocket for low-latency communication.
Monitors a light entity's brightness in real-time (event-driven, no polling)
and provides color control for keyboard layer color sync with solar elevation
brightness scaling.
"""

import json
import os
import threading
import time
from typing import Optional
from datetime import datetime

try:
    import websocket
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False

try:
    from astral import LocationInfo
    from astral.sun import elevation
    ASTRAL_AVAILABLE = True
except ImportError:
    ASTRAL_AVAILABLE = False


class HomeAssistantClient:
    """Client for Home Assistant WebSocket communication and brightness scaling"""

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
            poll_interval: Unused with WebSocket (kept for API compatibility)
            latitude: Latitude for solar calculations (default: 49.19 = Brno, CZ)
            longitude: Longitude for solar calculations (default: 16.61 = Brno, CZ)
            use_solar: Enable solar brightness calculations (default: True)
        """
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

        if self.use_solar:
            self.location = LocationInfo("User Location", "Region", "UTC", self.latitude, self.longitude)
        else:
            self.location = None

        self._connected = False
        self._running = False
        self._lock = threading.RLock()  # Reentrant - _update_brightness_from_state called within lock
        self._msg_lock = threading.Lock()
        self._msg_id = 0
        self._brightness_scale = 1.0  # Default to 100% if HA unavailable

        # WebSocket state
        self._ws = None
        self._ws_thread = None
        self._state_cache = {}  # entity_id -> state dict
        self._connect_event = threading.Event()

        # Adaptive lighting support (detected at connect time)
        self._adaptive_lighting_switches = []  # List of switch entity_ids

    @property
    def brightness_scale(self) -> float:
        """Current brightness scale (thread-safe, 0.0-1.0)"""
        with self._lock:
            return self._brightness_scale

    @property
    def connected(self) -> bool:
        """Connection status"""
        with self._lock:
            return self._connected

    # --- Connection management ---

    def _build_ws_url(self) -> str:
        """Convert HTTP base URL to WebSocket URL"""
        url = self.base_url
        if url.startswith("https://"):
            url = "wss://" + url[8:]
        elif url.startswith("http://"):
            url = "ws://" + url[7:]
        return url.rstrip("/") + "/api/websocket"

    def connect(self) -> bool:
        """Connect to Home Assistant via WebSocket and authenticate."""
        if not WEBSOCKET_AVAILABLE:
            print("[HA] Error: websocket-client library not found")
            print("[HA] Install with: pip install websocket-client")
            return False

        if not self.token:
            print("[HA] Error: No access token provided")
            print("[HA] Create a long-lived access token in Home Assistant")
            print("[HA] Profile -> Long-Lived Access Tokens -> Create Token")
            print("[HA] Then pass it via --ha-token or HASS_TOKEN env var")
            return False

        print(f"[HA] Connecting to Home Assistant at {self.base_url}...")
        self._running = True
        self._connect_event.clear()
        self._ws_thread = threading.Thread(target=self._ws_run_forever, daemon=True)
        self._ws_thread.start()

        if self._connect_event.wait(timeout=10.0):
            if self._connected:
                print(f"[HA] Connected successfully")
                return True
            return False
        else:
            print("[HA] Connection timeout")
            return False

    def disconnect(self):
        """Disconnect from Home Assistant"""
        self._running = False
        if self._ws:
            self._ws.close()
        with self._lock:
            self._connected = False

    def start_polling(self):
        """No-op with WebSocket - events are pushed to us in real-time."""
        pass

    def stop_polling(self):
        """Stop the WebSocket connection."""
        self._running = False
        if self._ws:
            self._ws.close()

    # --- WebSocket thread ---

    def _ws_run_forever(self):
        """Run the WebSocket event loop with automatic reconnection."""
        while self._running:
            try:
                ws = websocket.WebSocketApp(
                    self._build_ws_url(),
                    on_open=self._on_ws_open,
                    on_message=self._on_ws_message,
                    on_error=self._on_ws_error,
                    on_close=self._on_ws_close,
                )
                with self._lock:
                    self._ws = ws
                ws.run_forever()
            except Exception as e:
                print(f"[HA] WebSocket error: {e}")

            with self._lock:
                self._connected = False
                self._brightness_scale = 1.0  # Fail-safe

            if self._running:
                print("[HA] Reconnecting in 5s...")
                time.sleep(5)

    def _on_ws_open(self, ws):
        print("[HA] WebSocket connected, authenticating...")

    def _on_ws_message(self, ws, message):
        data = json.loads(message)
        msg_type = data.get("type")

        if msg_type == "auth_required":
            ws.send(json.dumps({"type": "auth", "access_token": self.token}))

        elif msg_type == "auth_ok":
            with self._lock:
                self._connected = True
            self._connect_event.set()
            print("[HA] Authenticated")
            # Fetch initial states and subscribe to state changes
            self._send({"type": "get_states"})
            self._send({"type": "subscribe_events", "event_type": "state_changed"})

        elif msg_type == "auth_invalid":
            print(f"[HA] Auth failed: {data.get('message', 'unknown')}")
            self._connect_event.set()

        elif msg_type == "event":
            event = data.get("event", {})
            if event.get("event_type") == "state_changed":
                new_state = event.get("data", {}).get("new_state")
                entity_id = event.get("data", {}).get("entity_id")
                if new_state and entity_id:
                    with self._lock:
                        self._state_cache[entity_id] = new_state
                    if entity_id == self.entity_id:
                        self._update_brightness_from_state(new_state)

        elif msg_type == "result":
            result = data.get("result")
            if isinstance(result, list):
                # get_states returns all entity states - cache them
                for state in result:
                    eid = state.get("entity_id")
                    if eid:
                        with self._lock:
                            self._state_cache[eid] = state
                    if eid == self.entity_id:
                        self._update_brightness_from_state(state)
                # Verify entities exist
                with self._lock:
                    if self.entity_id not in self._state_cache:
                        print(f"[HA] Warning: Entity '{self.entity_id}' not found")
                    if self.color_entity_id not in self._state_cache:
                        print(f"[HA] Warning: Color entity '{self.color_entity_id}' not found")

                # Detect adaptive-lighting switches
                self._detect_adaptive_lighting()
            elif not data.get("success", True):
                error = data.get("error", {}).get("message", "unknown")
                print(f"[HA] Command failed: {error}")

    def _on_ws_error(self, ws, error):
        print(f"[HA] WebSocket error: {error}")

    def _on_ws_close(self, ws, code, message):
        print(f"[HA] WebSocket closed: {code} {message}")
        with self._lock:
            self._connected = False
            self._brightness_scale = 1.0  # Fail-safe

    def _send(self, data: dict) -> int:
        """Send a command over WebSocket with auto-incrementing ID."""
        with self._msg_lock:
            self._msg_id += 1
            msg_id = self._msg_id
        msg = dict(data)
        msg["id"] = msg_id
        try:
            if self._ws:
                self._ws.send(json.dumps(msg))
        except Exception as e:
            print(f"[HA] Error sending WebSocket message: {e}")
        return msg_id

    def _update_brightness_from_state(self, state: dict):
        """Update brightness scale from a state dict (event-driven)."""
        is_on = state.get("state") == "on"
        bri = state.get("attributes", {}).get("brightness", 0)
        scale = self._calculate_scale(bri, is_on)
        with self._lock:
            self._brightness_scale = scale

    # --- Color control API ---

    def get_light_color_state(self) -> Optional[dict]:
        """
        Get the cached state of the color light (instant, no network call).

        Returns:
            Dict with 'state', 'brightness', 'rgb_color', 'color_temp',
            or None if the entity is not yet cached.
        """
        with self._lock:
            state = self._state_cache.get(self.color_entity_id)
        if state is None:
            print(f"[HA] No cached state for '{self.color_entity_id}'")
            return None
        attrs = state.get("attributes", {})
        return {
            "state": state.get("state", "off"),
            "brightness": attrs.get("brightness"),
            "rgb_color": attrs.get("rgb_color"),
            "color_temp": attrs.get("color_temp"),
        }

    def _optimistic_cache_update(self, entity_id: str, state: str, attrs: dict):
        """Immediately update the local cache to reflect a command we just sent.

        This prevents race conditions where get_light_color_state() reads
        stale cache data before the WebSocket state_changed event arrives.
        """
        cached = {
            "entity_id": entity_id,
            "state": state,
            "attributes": attrs,
        }
        with self._lock:
            self._state_cache[entity_id] = cached
            # Also update brightness if this is the monitored entity
            if entity_id == self.entity_id:
                self._update_brightness_from_state(cached)

    def set_light_color(self, r: int, g: int, b: int, brightness: Optional[int] = None):
        """Set the color light to an RGB color via WebSocket."""
        service_data = {
            "entity_id": self.color_entity_id,
            "rgb_color": [r, g, b],
        }
        if brightness is not None:
            service_data["brightness"] = brightness
        self._send({
            "type": "call_service",
            "domain": "light",
            "service": "turn_on",
            "service_data": service_data,
        })

        # Optimistically update cache so a rapid save after this
        # doesn't capture the layer color as the "original" state
        with self._lock:
            old = self._state_cache.get(self.color_entity_id, {})
        old_attrs = dict(old.get("attributes", {}))
        old_attrs["rgb_color"] = [r, g, b]
        if brightness is not None:
            old_attrs["brightness"] = brightness
        self._optimistic_cache_update(self.color_entity_id, "on", old_attrs)

        print(f"[HA] Set light color to RGB({r}, {g}, {b})")

    def restore_light_state(self, saved_state: dict):
        """Restore a previously captured light state via WebSocket."""
        if saved_state.get("state") == "off":
            self._send({
                "type": "call_service",
                "domain": "light",
                "service": "turn_off",
                "service_data": {"entity_id": self.color_entity_id},
            })
            self._optimistic_cache_update(self.color_entity_id, "off", {})
            print("[HA] Restored light state: off")
            return

        service_data = {"entity_id": self.color_entity_id}
        if saved_state.get("rgb_color") is not None:
            service_data["rgb_color"] = saved_state["rgb_color"]
        elif saved_state.get("color_temp") is not None:
            service_data["color_temp"] = saved_state["color_temp"]
        if saved_state.get("brightness") is not None:
            service_data["brightness"] = saved_state["brightness"]

        self._send({
            "type": "call_service",
            "domain": "light",
            "service": "turn_on",
            "service_data": service_data,
        })

        # Optimistically update cache with the restored state so a rapid
        # subsequent layer activation saves the correct "original" state
        restored_attrs = {}
        if saved_state.get("rgb_color") is not None:
            restored_attrs["rgb_color"] = saved_state["rgb_color"]
        if saved_state.get("color_temp") is not None:
            restored_attrs["color_temp"] = saved_state["color_temp"]
        if saved_state.get("brightness") is not None:
            restored_attrs["brightness"] = saved_state["brightness"]
        self._optimistic_cache_update(self.color_entity_id, "on", restored_attrs)

        print(f"[HA] Restored light state: on, "
              f"rgb={saved_state.get('rgb_color')}, "
              f"brightness={saved_state.get('brightness')}")

    def trigger_automation(self, entity_id: str):
        """Trigger a Home Assistant automation or script via WebSocket.

        Detects whether the entity_id starts with 'script.' or 'automation.'
        and calls the appropriate service.
        """
        if entity_id.startswith("script."):
            self._send({
                "type": "call_service",
                "domain": "script",
                "service": "turn_on",
                "service_data": {"entity_id": entity_id},
            })
            print(f"[HA] Triggered script: {entity_id}")
        else:
            self._send({
                "type": "call_service",
                "domain": "automation",
                "service": "trigger",
                "service_data": {"entity_id": entity_id},
            })
            print(f"[HA] Triggered automation: {entity_id}")

    def _detect_adaptive_lighting(self):
        """Detect adaptive-lighting switches from the HA state cache."""
        with self._lock:
            switches = [eid for eid in self._state_cache
                        if eid.startswith("switch.adaptive_lighting_")
                        and not eid.endswith("_sleep_mode")
                        and not eid.endswith("_adapt_color")
                        and not eid.endswith("_adapt_brightness")]
        if switches:
            self._adaptive_lighting_switches = switches
            print(f"[HA] Adaptive Lighting detected: {switches}")

    def _clear_adaptive_lighting_manual_control(self):
        """Clear the 'manually controlled' flag on our light for all active
        adaptive-lighting switches, then force-apply current settings.

        This is needed because setting a light color via light.turn_on causes
        adaptive-lighting to mark the light as 'manually controlled' and pause
        adaptation. Clearing the flag and applying forces it to resume.
        """
        if not self._adaptive_lighting_switches:
            return

        for switch_eid in self._adaptive_lighting_switches:
            # Check if the switch is on
            with self._lock:
                sw_state = self._state_cache.get(switch_eid, {})
            if sw_state.get("state") != "on":
                continue

            # Clear manual control flag for our light
            self._send({
                "type": "call_service",
                "domain": "adaptive_lighting",
                "service": "set_manual_control",
                "service_data": {
                    "entity_id": switch_eid,
                    "lights": [self.color_entity_id],
                    "manual_control": False,
                },
            })

            # Force apply current adaptive settings to our light
            self._send({
                "type": "call_service",
                "domain": "adaptive_lighting",
                "service": "apply",
                "service_data": {
                    "entity_id": switch_eid,
                    "lights": [self.color_entity_id],
                },
            })
            print(f"[HA] Cleared manual control and applied adaptive-lighting: {switch_eid}")

    def restore_light_mode(self):
        """
        Find and re-trigger the most recently activated light-controlling entity.

        Queries HA for all scenes, scripts, automations, tags, and switches,
        finds the one with the most recent last_changed timestamp, and
        re-triggers it. This restores the correct light mode (adaptive-lighting,
        sun-following, dark scene, etc.) without qmk-tools needing to know about
        specific modes.

        For adaptive-lighting: clears the 'manually controlled' flag that was
        set when qmk-tools changed the light color, then forces re-application
        of the current adaptive settings.
        """
        try:
            # Entity domains that can control lights when triggered
            LIGHT_CONTROL_DOMAINS = (
                "scene.", "script.", "automation.", "tag.", "switch."
            )

            with self._lock:
                candidates = []
                for eid, state in self._state_cache.items():
                    if not eid.startswith(LIGHT_CONTROL_DOMAINS):
                        continue
                    # Skip automations that are off (disabled)
                    if eid.startswith("automation.") and state.get("state") != "on":
                        continue
                    # Skip non-light switches (only include adaptive-lighting)
                    if eid.startswith("switch.") and "adaptive_lighting" not in eid:
                        continue
                    # Skip adaptive-lighting sub-switches (sleep mode, adapt color, etc.)
                    if eid.startswith("switch.adaptive_lighting_") and any(
                        eid.endswith(suffix) for suffix in
                        ("_sleep_mode", "_adapt_color", "_adapt_brightness")
                    ):
                        continue
                    last_changed = state.get("last_changed", "")
                    if last_changed:
                        candidates.append((last_changed, eid, state))

            if not candidates:
                print("[HA] No light-controlling entities found for mode restore")
                # Still try to clear adaptive-lighting manual control
                self._clear_adaptive_lighting_manual_control()
                return

            # Sort by last_changed descending (most recent first)
            candidates.sort(key=lambda x: x[0], reverse=True)
            ts, eid, state = candidates[0]
            friendly = state.get("attributes", {}).get("friendly_name", eid)
            print(f"[HA] Most recent light mode: {eid} ({friendly}) at {ts}")

            # Re-trigger based on domain
            if eid.startswith("scene."):
                self._send({
                    "type": "call_service",
                    "domain": "scene",
                    "service": "turn_on",
                    "service_data": {"entity_id": eid},
                })
                print(f"[HA] Re-activated scene: {eid}")

            elif eid.startswith("script."):
                self._send({
                    "type": "call_service",
                    "domain": "script",
                    "service": "turn_on",
                    "service_data": {"entity_id": eid},
                })
                print(f"[HA] Re-triggered script: {eid}")

            elif eid.startswith("automation."):
                self._send({
                    "type": "call_service",
                    "domain": "automation",
                    "service": "trigger",
                    "service_data": {"entity_id": eid, "skip_condition": True},
                })
                print(f"[HA] Re-triggered automation: {eid}")

            elif eid.startswith("switch.adaptive_lighting"):
                # Adaptive-lighting switch was the most recent mode change.
                # Clear manual control and force-apply current settings.
                self._clear_adaptive_lighting_manual_control()

            elif eid.startswith("tag."):
                # Tags trigger automations via state changes. Find the automation
                # that was most recently triggered around the tag scan time.
                tag_eid = eid
                tag_ts = ts
                with self._lock:
                    best_auto = None
                    best_diff = float('inf')
                    for a_eid, a_state in self._state_cache.items():
                        if not a_eid.startswith("automation."):
                            continue
                        if a_state.get("state") != "on":
                            continue
                        # Use last_triggered from attributes (not last_changed)
                        a_ts = a_state.get("attributes", {}).get("last_triggered", "")
                        if not a_ts:
                            continue
                        try:
                            from datetime import datetime as dt
                            tag_time = dt.fromisoformat(tag_ts.replace("Z", "+00:00"))
                            auto_time = dt.fromisoformat(a_ts.replace("Z", "+00:00"))
                            diff = abs((tag_time - auto_time).total_seconds())
                            if diff < best_diff and diff < 60.0:
                                best_diff = diff
                                best_auto = a_eid
                        except (ValueError, TypeError):
                            continue

                if best_auto:
                    self._send({
                        "type": "call_service",
                        "domain": "automation",
                        "service": "trigger",
                        "service_data": {"entity_id": best_auto, "skip_condition": True},
                    })
                    print(f"[HA] Tag {tag_eid} -> triggered automation: {best_auto}")
                else:
                    print(f"[HA] Tag {tag_eid} scanned but no matching automation found")
                    # Fallback: clear adaptive-lighting if present
                    self._clear_adaptive_lighting_manual_control()

            else:
                # Generic switch - toggle off/on
                self._send({
                    "type": "call_service",
                    "domain": "switch",
                    "service": "turn_on",
                    "service_data": {"entity_id": eid},
                })
                print(f"[HA] Re-activated switch: {eid}")

            # Always clear adaptive-lighting manual control as a safety net,
            # in case adaptive-lighting is running alongside another mode
            self._clear_adaptive_lighting_manual_control()

        except Exception as e:
            print(f"[HA] Error restoring light mode: {e}")

    # --- Brightness calculation ---

    def _calculate_solar_brightness(self) -> float:
        """Calculate brightness based on solar elevation (sun position)."""
        if not self.use_solar:
            return self.min_brightness

        try:
            now = datetime.now()
            sun_elevation = elevation(observer=self.location.observer, dateandtime=now)

            if sun_elevation < 0:
                return self.min_brightness

            peak_elevation = 60.0
            scale = self.min_brightness + (1.0 - self.min_brightness) * (sun_elevation / peak_elevation)
            return max(self.min_brightness, min(1.0, scale))

        except Exception as e:
            print(f"[HA] Error calculating solar brightness: {e}")
            return self.min_brightness

    def _calculate_scale(self, light_bri: int, is_on: bool) -> float:
        """Calculate brightness scale from light brightness and solar elevation."""
        if not is_on or not light_bri or light_bri == 0:
            light_scale = self.min_brightness
        else:
            light_scale = self.min_brightness + (1.0 - self.min_brightness) * (light_bri / 255.0)
            light_scale = max(self.min_brightness, min(1.0, light_scale))

        solar_scale = self._calculate_solar_brightness()
        return max(light_scale, solar_scale)
