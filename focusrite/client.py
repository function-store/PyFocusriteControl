"""Focusrite Control Server local protocol client (pure stdlib).

Protocol summary
----------------
1. Discovery: UDP broadcast ``<client-discovery app="SAFFIRE-CONTROL" version="4"/>``
   to ports 30096/30097/30098. The ControlServer replies with a
   ``<server-announcement ... port='NNNNN'/>`` datagram; we read the TCP port.
2. Connect: TCP to 127.0.0.1:<port>. Every message on the wire is framed as
   ``Length=XXXXXX <payload>`` where XXXXXX is the payload length as 6 lowercase
   hex digits, followed by a single space, followed by the raw XML payload.
3. Handshake: send ``<client-details client-key="..."/>`` then
   ``<device-subscribe devid="1" subscribe="true"/>``. Send ``<keep-alive/>``
   roughly every 3 seconds to stay connected.
4. State: after subscribing the server pushes a ``<device-...>`` tree plus live
   updates. Controls appear as ``<item id="N" value="V"/>``.
5. Set: ``<set devid="1"><item id="N" value="V"/></set>``.
"""

from __future__ import annotations

import os
import re
import socket
import time
from typing import Iterator, Optional


def _default_discovery_ports() -> tuple:
    override = os.environ.get("FOCUSRITE_DISCOVERY_PORTS")
    if override:
        return tuple(int(p) for p in override.replace(",", " ").split())
    return (30096, 30097, 30098)


DISCOVERY_PORTS = _default_discovery_ports()
DISCOVERY_MESSAGE = '<client-discovery app="SAFFIRE-CONTROL" version="4"/>'
LOCALHOST = "127.0.0.1"

_PORT_RE = re.compile(r"port=['\"](\d+)['\"]")


class FocusriteError(Exception):
    """Base error for this package."""


class ServerNotFoundError(FocusriteError):
    """Raised when the Focusrite Control Server can't be discovered."""


def frame(payload: str) -> bytes:
    """Wrap an XML payload in the ``Length=XXXXXX <payload>`` wire framing."""
    body = payload.encode("utf-8")
    header = "Length=%06x " % len(body)
    return header.encode("ascii") + body


def _iter_frames(buffer: bytearray) -> Iterator[str]:
    """Consume and yield complete framed payloads from ``buffer`` in place.

    Leaves any trailing partial frame in the buffer for the next read. Tolerant
    of leading junk: it scans forward to the next ``Length=`` marker.
    """
    while True:
        idx = buffer.find(b"Length=")
        if idx == -1:
            # No frame marker yet; keep only a small tail in case a marker is
            # split across reads.
            if len(buffer) > 7:
                del buffer[:-7]
            return
        # Drop anything before the marker.
        if idx:
            del buffer[:idx]
        # Need "Length=" (7) + 6 hex + 1 space = 14 bytes of header.
        if len(buffer) < 14:
            return
        hex_len = bytes(buffer[7:13])
        try:
            n = int(hex_len, 16)
        except ValueError:
            # Not a real header; skip this marker and keep scanning.
            del buffer[:7]
            continue
        payload_start = 14
        if len(buffer) < payload_start + n:
            return  # Wait for the rest of the payload.
        payload = bytes(buffer[payload_start:payload_start + n])
        del buffer[:payload_start + n]
        yield payload.decode("utf-8", "replace")


def discover_port(timeout: float = 3.0) -> int:
    """Discover the ControlServer TCP port. Raises ServerNotFoundError."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # On Windows, a UDP send to a closed/unreachable port makes the *next*
        # recvfrom raise WSAECONNRESET (WinError 10054). We send to several
        # ports (30096-30098) and to the broadcast address, so some sends will
        # bounce. Disable that behavior where supported, and tolerate it below.
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            try:
                sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except OSError:
                pass
        sock.bind(("", 0))
        msg = frame(DISCOVERY_MESSAGE)

        deadline = time.monotonic() + timeout
        next_send = 0.0
        sock.settimeout(0.4)
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_send:
                for port in DISCOVERY_PORTS:
                    # Broadcast (how the iOS app finds it) *and* localhost
                    # unicast (reliable when the server is on this machine).
                    for addr in ("255.255.255.255", LOCALHOST):
                        try:
                            sock.sendto(msg, (addr, port))
                        except OSError:
                            pass
                next_send = now + 1.0
            try:
                data, _addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except ConnectionResetError:
                # ICMP port-unreachable from a bounced send; keep listening.
                continue
            except OSError:
                continue
            match = _PORT_RE.search(data.decode("utf-8", "replace"))
            if match:
                return int(match.group(1))
        raise ServerNotFoundError(
            "No Focusrite Control Server responded on UDP "
            f"{DISCOVERY_PORTS} within {timeout:.0f}s. Is Focusrite Control "
            "(or its background Server) running?"
        )
    finally:
        sock.close()


class Connection:
    """A live TCP connection to the ControlServer.

    Use as a context manager. After :meth:`connect`, incoming framed payloads
    are available via :meth:`read` / :meth:`read_until`.
    """

    def __init__(
        self,
        port: int,
        client_key: str,
        hostname: str = "MyFocusriteControl",
        connect_timeout: float = 5.0,
    ):
        self.port = port
        self.client_key = client_key
        self.hostname = hostname
        self._connect_timeout = connect_timeout
        self._sock: Optional[socket.socket] = None
        self._buf = bytearray()
        self._last_keepalive = 0.0

    # -- lifecycle ---------------------------------------------------------
    def connect(self) -> "Connection":
        sock = socket.create_connection((LOCALHOST, self.port), self._connect_timeout)
        sock.settimeout(0.4)
        self._sock = sock
        # Present a hostname so the ControlServer can list us as an identifiable
        # remote client to approve (an unnamed client shows up blank and stays
        # unauthorised, so its `set` commands are silently ignored).
        self.send(
            f'<client-details client-key="{self.client_key}" '
            f'hostname="{self.hostname}"/>'
        )
        self.send('<device-subscribe devid="1" subscribe="true"/>')
        self._last_keepalive = time.monotonic()
        return self

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def __enter__(self) -> "Connection":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    # -- io ----------------------------------------------------------------
    def send(self, payload: str) -> None:
        assert self._sock is not None, "not connected"
        self._sock.sendall(frame(payload))

    def keep_alive(self) -> None:
        """Send a keep-alive if ~3s have elapsed since the last one."""
        now = time.monotonic()
        if now - self._last_keepalive >= 3.0:
            self.send("<keep-alive/>")
            self._last_keepalive = now

    def read(self, timeout: float) -> Iterator[str]:
        """Yield framed payloads received within ``timeout`` seconds.

        Sends keep-alives automatically. Returns when the deadline passes.
        """
        assert self._sock is not None, "not connected"
        deadline = time.monotonic() + timeout
        # Flush anything already buffered.
        yield from _iter_frames(self._buf)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self.keep_alive()
            # Cap the blocking recv to the time we actually have left, so a
            # short read returns promptly instead of blocking a fixed timeout.
            self._sock.settimeout(min(0.4, remaining))
            try:
                chunk = self._sock.recv(65535)
            except socket.timeout:
                continue
            except OSError as exc:
                raise FocusriteError(f"connection error: {exc}") from exc
            if not chunk:
                return  # server closed
            self._buf.extend(chunk)
            yield from _iter_frames(self._buf)

    def read_until(self, predicate, timeout: float):
        """Return the first payload for which ``predicate`` is true, or None.

        Lets callers stop as soon as the interesting frame arrives instead of
        waiting out a fixed timeout.
        """
        for payload in self.read(timeout):
            if predicate(payload):
                return payload
        return None

    def set_item(self, item_id: str, value: str, devid: str = "1") -> None:
        self.send(
            f'<set devid="{devid}"><item id="{item_id}" value="{value}"/></set>'
        )
