#!/usr/bin/env python3
"""
MQTT Client for QMK Overlay Integration
Simplified transition from WebSocket to MQTT.
"""

import json
import os
import ssl
import threading
import time
from typing import Optional
from datetime import datetime, timezone
import paho.mqtt.client as mqtt

try:
    from astral import LocationInfo
    from astral.sun import elevation
    ASTRAL_AVAILABLE = True
except ImportError:
    ASTRAL_AVAILABLE = False

class MQTTHomeAssistantClient:
    """Client for Home Assistant via MQTT communication and brightness scaling."""

    def __init__(self,
                 mqtt_broker: str = "homeassistant.local",
                 mqtt_port: int = 1883,
                 mqtt_transport: str = "tcp",
                 mqtt_username: Optional[str] = None,
                 mqtt_password: Optional[str] = None,
                 use_tls: bool = False,
                 topic_prefix: str = "homeassistant/",
                 device_id: str = "keyboard1",
                 entity_id: str = "light.velke_svetlo_v_obyvaku",
                 color_entity_id: Optional[str] = None,
                 min_brightness: float = 0.25,
                 latitude: float = 49.19,
                 longitude: float = 16.61,
                 use_solar: bool = True):
        """
        Initialize MQTT Home Assistant client
        """
        self.broker = mqtt_broker
        self.port = mqtt_port
        self.transport = mqtt_transport
        self.username = mqtt_username
        self.password = mqtt_password or os.environ.get("MQTT_PASSWORD")
        self.use_tls = use_tls
        self.topic_prefix = topic_prefix.strip("/")
        self.device_id = device_id
        self.entity_id = entity_id
        self.color_entity_id = color_entity_id or entity_id
        self.min_brightness = max(0.0, min(1.0, min_brightness))
        self.latitude = latitude
        self.longitude = longitude
        self.use_solar = use_solar and ASTRAL_AVAILABLE

        if self.use_solar and not ASTRAL_AVAILABLE:
            print("[MQTT] Warning: Solar brightness requested but astral library not available")
            self.use_solar = False

        if self.use_solar:
            self.location = LocationInfo("User Location", "Region", "UTC", self.latitude, self.longitude)
        else:
            self.location = None

        self._connected = False
        self._running = False
        self._lock = threading.RLock()
        self._brightness_scale = 1.0
        
        # MQTT state vars
        self.client = None
        self._state_cache = {}  # entity_id -> state dict

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

    def _layer_topic(self) -> str:
        return f"qmk/{self.device_id}/layer"

    def _availability_topic(self) -> str:
        return f"qmk/{self.device_id}/availability"

    def connect(self) -> bool:
        """Connect to Home Assistant via MQTT."""
        print(f"[MQTT] Connecting to {self.broker}:{self.port} ({self.transport})...")
        self._running = True

        client_id = f"qmk-tools-{self.device_id}"
        # Support both paho-mqtt v1 and v2 callback APIs
        if hasattr(mqtt, "CallbackAPIVersion"):
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                       transport=self.transport, client_id=client_id)
        else:
            self.client = mqtt.Client(transport=self.transport, client_id=client_id)

        if self.username:
            self.client.username_pw_set(self.username, self.password)
        if self.use_tls:
            self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        self.client.reconnect_delay_set(min_delay=2, max_delay=30)

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.will_set(self._availability_topic(), payload="offline", qos=1, retain=True)

        try:
            self.client.connect_async(self.broker, self.port, keepalive=60)
            self.client.loop_start()

            # Give it a moment to connect
            time.sleep(2)
            if self._connected:
                print("[MQTT] Connected successfully")
                return True
        except Exception as e:
            print(f"[MQTT] Connection failed: {e}")

        return False

    def _on_connect(self, client, userdata, flags, *args):
        # v1 callback: args = (rc,)   v2 callback: args = (reason_code, properties)
        rc = args[0] if args else 0
        success = (not rc.is_failure) if hasattr(rc, "is_failure") else (rc == 0)
        if success:
            with self._lock:
                self._connected = True
            print("[MQTT] Connected to broker")
            self._publish(self._availability_topic(), "online", qos=1, retain=True)
        else:
            print(f"[MQTT] Connection failed with code {rc}")

    def _on_message(self, client, userdata, msg):
        # In an MQTT setup, we might receive state updates here.
        # For now, this serves as a placeholder for topic-specific logic.
        pass

    def disconnect(self):
        """Disconnect from Home Assistant."""
        self._running = False
        if self.client:
            self._publish(self._availability_topic(), "offline", qos=1, retain=True)
            self.client.disconnect()
            self.client.loop_stop()
        with self._lock:
            self._connected = False

    def start_polling(self):
        pass

    def stop_polling(self):
        self.disconnect()

    def _publish(self, topic: str, payload, qos: int = 0, retain: bool = False):
        """Publish a message to the specified topic. `payload` is JSON-encoded
        unless it's already a string (e.g. the plain "online"/"offline" markers)."""
        if self.client and self.client.is_connected():
            data = payload if isinstance(payload, str) else json.dumps(payload)
            self.client.publish(topic, data, qos=qos, retain=retain)
        else:
            print(f"[MQTT] Failed to publish to {topic}: client not connected")

    def publish_layer_state(self, layer_num: int, layer_name: str,
                             color_name: str, color_hex: str,
                             is_base_layer: Optional[bool] = None):
        """Publish the current keyboard layer as a retained state event.

        This is a pure state announcement, not a command: Home Assistant
        automations decide what to do with the color (apply it, scale it,
        ignore it) rather than qmk-tools dictating the light's final state.
        """
        payload = {
            "layer_num": layer_num,
            "layer_name": layer_name,
            "is_base_layer": is_base_layer if is_base_layer is not None else layer_num == 0,
            "color_name": color_name,
            "color_hex": color_hex,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._publish(self._layer_topic(), payload, qos=1, retain=True)
        print(f"[MQTT] Published layer state: {layer_name} ({color_hex})")

    def set_light_color(self, r: int, g: int, b: int, brightness: Optional[int] = None):
        """Set the color light to an RGB color via MQTT."""
        payload = {
            "entity_id": self.color_entity_id,
            "rgb_color": [r, g, b],
        }
        if brightness is not None:
            payload["brightness"] = brightness
        
        # We publish to a "request" topic that HA (or an integration) listens to
        self._publish(f"{self.topic_prefix}set_color", payload)

        # Optimistic update
        with self._lock:
            old = self.state_cache_get(self.color_entity_id)
            attr = dict(old.get("attributes", {}))
            attr["rgb_color"] = [r, g, b]
            if brightness is not None:
                attr["brightness"] = brightness
            self._update_local_cache(self.color_entity_id, "on", attr)

        print(f"[MQTT] Sent color {r},{g},{b} to {self.color_entity_id}")

    def restore_light_state(self, saved_state: dict):
        """Restore a previously captured light state via MQTT."""
        if saved_state.get("state") == "off":
            payload = {"entity_id": self.color_entity_id}
            self._publish(f"{self.topic_prefix}set_state", payload)
            self._update_local_cache(self.color_entity_id, "off", {})
            return

        payload = {"entity_id": self.color_entity_id}
        if saved_state.get("rgb_color") is not None:
            payload["rgb_color"] = saved_state["rgb_color"]
        elif saved_state.get("color_temp") is not None:
            payload["color_temp"] = saved_state["color_temp"]
        
        if saved_state.get("brightness") is not None:
            payload["brightness"] = saved_state["brightness"]

        self._publish(f"{self.topic_prefix}set_state", payload)
        
        # Optimistic update
        attr = {}
        if saved_state.get("rgb_color") is not None:
            attr["rgb_color"] = saved_state["rgb_color"]
        if saved_state.get("color_temp") is not None:
            attr["color_temp"] = saved_state["color_temp"]
        if saved_state.get("brightness") is not None:
            attr["brightness"] = saved_state["brightness"]
        
        self._update_local_cache(self.color_entity_id, "on", attr)

    def trigger_automation(self, entity_id: str):
        """Trigger a Home Assistant automation or script via MQTT."""
        topic = f"{self.topic_prefix}trigger"
        payload = {"entity_id": entity_id}
        self._publish(topic, payload)

    def _update_local_cache(self, eid: str, state: str, attrs: dict):
        with self._lock:
            self._state_cache[eid] = {
                "entity_id": eid,
                "state": state,
                "attributes": attrs
            }
            if eid == self.entity_id:
                # This matches the internal logic of the original script
                bri = attrs.get("brightness", 0)
                is_on = state == "on"
                self._calc_scale_local(bri, is_on)

    def _calc_scale_local(self, light_bri: int, is_on: bool):
        if not is_on or not light_bri or light_bri == 0:
            scale = self.min_brightness
        else:
            scale = self.min_brightness + (1.0 - self.min_brightness) * (light_bri / 255.0)
            scale = max(self.min_brightness, min(1.0, scale))
        
        solar_scale = self._calculate_solar_brightness()
        self._brightness_scale = max(scale, solar_scale)

    def _calculate_solar_brightness(self) -> float:
        if not self.use_solar:
            return self.min_brightness
        try:
            now = datetime.now()
            sun_elevation = elevation(observer=self.location.observer, date_time=now)
            if sun_elevation < 0:
                return self.min_brightness
            peak_elevation = 60.0
            scale = self.min_brightness + (1.0 - self.min_brightness) * (sun_elevation / peak_elevation)
            return max(self.min_brightness, min(1.0, scale))
        except Exception:
            return self.min_brightness

    def state_cache_get(self, eid: str) -> dict:
        with self._lock:
            return self._state_cache.get(eid, {})
        
    def get_light_color_state(self) -> Optional[dict]:
        """Mirror functionality of original."""
        data = self.state_cache_get(self.color_entity_id)
        if not data:
            return None
        attrs = data.get("attributes", {})
        return {
            "state": data.get("state", "off"),
            "brightness": attrs.get("brightness"),
            "rgb_color": attrs.get("rgb_color"),
            "color_temp": attrs.get("color_temp"),
        }
