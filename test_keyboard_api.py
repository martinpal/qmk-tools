import http.client
import json
import threading
import time
import unittest

import keyboard_api


class FakeKeyboard:
    """Stands in for the VIA keyboard: remembers the sleep state like the firmware."""

    def __init__(self):
        self.asleep = False
        self.mode = "ok"   # "ok" | "unsupported" | "no_answer"
        self.calls = []

    def host_sleep_command(self, action):
        self.calls.append(action)
        if self.mode != "ok":
            return self.mode, None
        if action == 1:
            self.asleep = True
        elif action == 0:
            self.asleep = False
        return "ok", "asleep" if self.asleep else "awake"


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.kb = FakeKeyboard()
        self.gateway = keyboard_api.KeyboardGateway()
        self.server = keyboard_api.ApiServer(self.gateway, port=0)
        self.server.start()
        self.running = True
        self.usb = threading.Thread(target=self._usb_loop, daemon=True)
        self.usb.start()

    def tearDown(self):
        self.running = False
        self.server.stop()
        self.usb.join(1)

    def _usb_loop(self):
        while self.running:
            self.gateway.service(self.kb)
            time.sleep(0.005)

    def call(self, method, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        conn.request(method, path, headers=headers or {})
        resp = conn.getresponse()
        body = json.loads(resp.read())
        conn.close()
        return resp.status, body


class TestApi(ApiTestCase):
    def test_health(self):
        self.assertEqual(self.call("GET", "/api/v1/health"), (200, {"ok": True}))

    def test_sleep_wake_query(self):
        self.assertEqual(self.call("POST", "/api/v1/keyboard/sleep"),
                         (200, {"keyboard": "connected", "state": "asleep"}))
        self.assertTrue(self.gateway.asleep)
        self.assertEqual(self.call("GET", "/api/v1/keyboard")[1]["state"], "asleep")
        self.assertEqual(self.call("POST", "/api/v1/keyboard/wake")[1]["state"], "awake")
        self.assertFalse(self.gateway.asleep)
        self.assertEqual(self.kb.calls, [1, 2, 0])

    def test_idempotent(self):
        for _ in range(2):
            self.assertEqual(self.call("POST", "/api/v1/keyboard/sleep")[1]["state"], "asleep")

    def test_unsupported_firmware(self):
        self.kb.mode = "unsupported"
        self.assertEqual(self.call("POST", "/api/v1/keyboard/sleep"), (501, {"error": "unsupported"}))

    def test_timeout(self):
        self.kb.mode = "no_answer"
        self.assertEqual(self.call("GET", "/api/v1/keyboard"), (504, {"error": "timeout"}))

    def test_disconnected(self):
        self.gateway.connected = False
        self.assertEqual(self.call("GET", "/api/v1/keyboard"), (503, {"error": "keyboard_disconnected"}))
        self.assertEqual(self.kb.calls, [])

    def test_routing_errors(self):
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        self.assertEqual(self.call("GET", "/api/v1/keyboard/sleep")[0], 405)
        self.assertEqual(self.call("POST", "/api/v1/keyboard")[0], 405)

    def test_browser_requests_rejected(self):
        status, _ = self.call("POST", "/api/v1/keyboard/sleep", {"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        status, _ = self.call("POST", "/api/v1/keyboard/sleep", {"Host": "evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(self.kb.calls, [])

    def test_localhost_host_header_allowed(self):
        status, _ = self.call("GET", "/api/v1/health", {"Host": "localhost:8765"})
        self.assertEqual(status, 200)

    def test_binds_to_loopback_only(self):
        self.assertEqual(self.server.httpd.server_address[0], "127.0.0.1")

    def test_cancelled_request_is_not_executed(self):
        # a request that timed out before the USB thread got to it must not run later
        self.running = False
        self.usb.join(1)
        status, _ = self.gateway.request("sleep", timeout=0.05)
        self.assertEqual(status, 504)
        self.gateway.service(self.kb)
        self.assertEqual(self.kb.calls, [])
        self.assertFalse(self.kb.asleep)


class TestSleepPolling(unittest.TestCase):
    def setUp(self):
        self.kb = FakeKeyboard()
        self.gateway = keyboard_api.KeyboardGateway()

    def test_refresh_sets_state(self):
        self.kb.asleep = True
        self.gateway.refresh(self.kb)
        self.assertEqual(self.gateway.state, "asleep")

    def test_wake_detected_by_polling(self):
        self.kb.asleep = True
        self.gateway.refresh(self.kb)
        self.kb.asleep = False  # woken by a key press / encoder turn
        self.gateway._next_sleep_poll = 0
        self.gateway.poll_while_asleep(self.kb)
        self.assertEqual(self.gateway.state, "awake")
        self.assertTrue(self.gateway.resume_pending)

    def test_polling_is_rate_limited(self):
        self.kb.asleep = True
        self.gateway.refresh(self.kb)
        n = len(self.kb.calls)
        self.gateway.poll_while_asleep(self.kb)   # too soon after going to sleep
        self.assertEqual(len(self.kb.calls), n)

    def test_unknown_after_repeated_failures(self):
        self.kb.asleep = True
        self.gateway.refresh(self.kb)
        self.kb.mode = "no_answer"
        for _ in range(keyboard_api.SLEEP_POLL_FAILURES):
            self.gateway._next_sleep_poll = 0
            self.gateway.poll_while_asleep(self.kb)
        self.assertEqual(self.gateway.state, "unknown")
        self.assertTrue(self.gateway.resume_pending)


if __name__ == "__main__":
    unittest.main()
