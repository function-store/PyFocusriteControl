"""High-level, ergonomic client for the Focusrite Control Server.

Example
-------
    from focusrite import Focusrite, requests

    # Uses the (already-approved) client_key from your config.json:
    with Focusrite.connect_from_config() as fc:
        fc.mute(1107)                     # high-level helpers
        fc.set(1107, False)               # generic set (bool -> true/false)
        fc.write(requests.mute(1107))     # raw request, like Node's clientWrite
        print(fc.get(1107))               # read a value (best-effort)
        for cid, val in fc.watch(5):      # stream control changes for 5s
            print(cid, val)

Note: only an **approved** client_key can change values (see README "Authorise
this client"); any key can read/subscribe.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from . import requests as requests
from .client import Connection, discover_port

_ITEM_RE = re.compile(
    r'<item\b[^>]*\bid=["\'](\d+)["\'][^>]*\bvalue=["\']([^"\']*)["\']'
)
_DEVICE_MARKERS = ("<device", "devid=", "<mute")


def _load_config(path=None) -> dict:
    p = Path(path) if path else Path(__file__).resolve().parent.parent / "config.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


class Focusrite:
    """A connected session to the Control Server, wrapping a :class:`Connection`."""

    def __init__(self, connection: Connection):
        self.connection = connection

    # -- construction ------------------------------------------------------
    @classmethod
    @contextmanager
    def connect(
        cls,
        client_key: Optional[str] = None,
        hostname: str = "PyFocusriteControl",
        timeout: float = 3.0,
        ready_timeout: float = 1.0,
    ) -> Iterator["Focusrite"]:
        """Discover, connect, and yield a session (context manager).

        A random ``client_key`` is generated if none is given — fine for
        reading, but writes require an approved key (pass yours, or use
        :meth:`connect_from_config`).
        """
        port = discover_port(timeout=timeout)
        conn = Connection(
            port, client_key or str(uuid.uuid4()), hostname=hostname
        ).connect()
        fc = cls(conn)
        if ready_timeout:
            fc.wait_ready(ready_timeout)
        try:
            yield fc
        finally:
            conn.close()

    @classmethod
    def connect_from_config(cls, path=None, **kwargs):
        """Like :meth:`connect`, but takes client_key/hostname from config.json."""
        cfg = _load_config(path)
        kwargs.setdefault("hostname", cfg.get("hostname", "PyFocusriteControl"))
        return cls.connect(client_key=cfg.get("client_key"), **kwargs)

    # -- low level ---------------------------------------------------------
    def write(self, payload: str) -> None:
        """Send a raw request string (equivalent to Node's ``clientWrite``)."""
        self.connection.send(payload)

    def wait_ready(self, timeout: float = 1.0) -> bool:
        """Block until the device tree arrives (so subsequent sets are honored)."""
        return self.connection.read_until(
            lambda p: any(m in p for m in _DEVICE_MARKERS), timeout
        ) is not None

    # -- controls ----------------------------------------------------------
    def set(self, item_id, value) -> None:
        """Set a control. ``value`` may be a bool (-> 'true'/'false') or string."""
        self.connection.set_item(str(item_id), requests.token(value))

    def get(self, item_id, timeout: float = 1.0) -> Optional[str]:
        """Best-effort read of one control's value (None if not seen in window)."""
        return self.snapshot(timeout).get(str(item_id))

    def snapshot(self, timeout: float = 1.0) -> dict:
        """Map of {control_id: value} for every control seen within ``timeout``."""
        values: dict = {}
        for payload in self.connection.read(timeout):
            for item_id, value in _ITEM_RE.findall(payload):
                values[item_id] = value
        return values

    def raw(self, timeout: float = 1.0) -> str:
        """Concatenated raw XML received within ``timeout`` (for inspection)."""
        return "\n".join(self.connection.read(timeout))

    def mute(self, item_id) -> None:
        self.set(item_id, True)

    def unmute(self, item_id) -> None:
        self.set(item_id, False)

    def toggle(self, item_id, muted_now: bool) -> bool:
        """Set the opposite of ``muted_now`` and return the new muted state."""
        new_state = not muted_now
        self.set(item_id, new_state)
        return new_state

    def watch(self, seconds: float, ids=None) -> Iterator:
        """Yield (control_id, value) each time a control changes, for ``seconds``.

        Pass ``ids`` to limit to specific control ids.
        """
        want = None if ids is None else {str(i) for i in ids}
        last: dict = {}
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            for payload in self.connection.read(0.5):
                for item_id, value in _ITEM_RE.findall(payload):
                    if want is not None and item_id not in want:
                        continue
                    if last.get(item_id) != value:
                        last[item_id] = value
                        yield item_id, value
