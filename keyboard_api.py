#!/usr/bin/env python3
"""Local HTTP API that lets other processes put the keyboard to sleep or wake it.

Only the overlay may talk to the keyboard over USB (one claimed interface, no
request ids in the VIA protocol), so HTTP handlers never touch USB: they queue
a request for the keyboard monitor thread, which runs it between matrix polls
(KeyboardGateway.service), and wait for the result.

    POST /api/v1/keyboard/sleep   put the keyboard to sleep (idempotent)
    POST /api/v1/keyboard/wake    wake it (idempotent)
    GET  /api/v1/keyboard         current state
    GET  /api/v1/health           the overlay is alive

The server binds to 127.0.0.1 only and has no authentication. Requests that carry
an Origin header or a foreign Host header are rejected, so a web page cannot
trigger it from the browser.
"""

import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple

DEFAULT_PORT = 8765
REQUEST_TIMEOUT = 2.0      # seconds a client waits for the USB thread
MAX_BODY = 4096            # bytes of request body we are willing to read and discard
SLEEP_POLL_INTERVAL = 1.0  # seconds between state queries while the keyboard sleeps
SLEEP_POLL_FAILURES = 5    # failed queries after which we stop assuming "asleep"

# action name -> value of byte 1 in the firmware's command
ACTIONS = {"wake": 0, "sleep": 1, "query": 2}


class _Request:
    def __init__(self, action: str):
        self.action = action
        self.done = threading.Event()
        self.cancelled = False
        self.result: Tuple[int, dict] = (500, {"error": "internal"})


class KeyboardGateway:
    """Hands API requests to the keyboard monitor thread and tracks the sleep state."""

    def __init__(self):
        self._queue = queue.Queue()
        self.connected = True
        self.state = "unknown"           # "awake" | "asleep" | "unknown"
        self.resume_pending = False      # set when the keyboard woke: the monitor resyncs its matrix state
        self._failures = 0
        self._next_sleep_poll = 0.0

    @property
    def asleep(self) -> bool:
        return self.state == "asleep"

    # -- called from HTTP threads ------------------------------------------

    def request(self, action: str, timeout: float = REQUEST_TIMEOUT) -> Tuple[int, dict]:
        """Run `action` ("sleep" | "wake" | "query") on the USB thread; returns (http status, body)."""
        if not self.connected:
            return 503, {"error": "keyboard_disconnected"}
        req = _Request(action)
        self._queue.put(req)
        if not req.done.wait(timeout):
            req.cancelled = True
            return 504, {"error": "timeout"}
        return req.result

    # -- called from the keyboard monitor thread ----------------------------

    def service(self, keyboard) -> None:
        """Run all queued requests. Must be called from the thread that owns the USB device."""
        while True:
            try:
                req = self._queue.get_nowait()
            except queue.Empty:
                return
            if req.cancelled:
                continue
            req.result = self._execute(keyboard, req.action)
            req.done.set()

    def refresh(self, keyboard) -> None:
        """Query the state once (used at startup)."""
        self._execute(keyboard, "query")

    def poll_while_asleep(self, keyboard) -> None:
        """Query about once a second while asleep to notice a wake (key press or encoder turn).

        After repeated failures (e.g. the keyboard was unplugged) the state becomes
        "unknown" so that normal polling and reconnection take over.
        """
        now = time.time()
        if now < self._next_sleep_poll:
            return
        self._next_sleep_poll = now + SLEEP_POLL_INTERVAL
        status, _ = self._execute_raw(keyboard, "query")
        if status != "ok":
            self._failures += 1
            if self._failures >= SLEEP_POLL_FAILURES:
                self._set_state("unknown")

    def _execute(self, keyboard, action: str) -> Tuple[int, dict]:
        status, state = self._execute_raw(keyboard, action)
        if status == "ok":
            return 200, {"keyboard": "connected", "state": state}
        if status == "unsupported":
            return 501, {"error": "unsupported"}
        return 504, {"error": "timeout"}

    def _execute_raw(self, keyboard, action: str) -> Tuple[str, Optional[str]]:
        status, state = keyboard.host_sleep_command(ACTIONS[action])
        if status == "ok":
            self._failures = 0
            self._set_state(state)
        return status, state

    def _set_state(self, state: str) -> None:
        if self.state == "asleep" and state != "asleep":
            self.resume_pending = True
        if state == "asleep":
            self._next_sleep_poll = time.time() + SLEEP_POLL_INTERVAL
        self.state = state


class _Handler(BaseHTTPRequestHandler):
    gateway: KeyboardGateway = None  # set on the generated subclass
    server_version = "qmk-overlay"
    protocol_version = "HTTP/1.1"

    ROUTES = {
        ("GET", "/api/v1/health"): None,
        ("GET", "/api/v1/keyboard"): "query",
        ("POST", "/api/v1/keyboard/sleep"): "sleep",
        ("POST", "/api/v1/keyboard/wake"): "wake",
    }

    def log_message(self, fmt, *args):  # keep the overlay's console quiet
        pass

    def _send(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _host_allowed(self) -> bool:
        host = self.headers.get("Host") or ""
        if host.startswith("["):  # IPv6 literal, e.g. [::1]:8765
            name = host.split("]")[0] + "]"
        else:
            name = host.rsplit(":", 1)[0] if ":" in host else host
        return name in ("127.0.0.1", "localhost", "[::1]")

    def _handle(self, method: str) -> None:
        # Drain the body (we need none) so keep-alive connections stay in sync
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self.close_connection = True
            return self._send(400, {"error": "bad_request"})
        if length:
            self.rfile.read(length)

        if self.headers.get("Origin") is not None or not self._host_allowed():
            return self._send(403, {"error": "forbidden"})

        path = self.path.split("?", 1)[0].rstrip("/")
        if (method, path) in self.ROUTES:
            action = self.ROUTES[(method, path)]
            if action is None:
                return self._send(200, {"ok": True})
            status, body = self.gateway.request(action)
            return self._send(status, body)
        if any(p == path for (_, p) in self.ROUTES):
            return self._send(405, {"error": "method_not_allowed"})
        return self._send(404, {"error": "not_found"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")


class ApiServer:
    """HTTP server on 127.0.0.1 running in a daemon thread."""

    def __init__(self, gateway: KeyboardGateway, port: int = DEFAULT_PORT):
        handler = type("Handler", (_Handler,), {"gateway": gateway})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="keyboard-api", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
