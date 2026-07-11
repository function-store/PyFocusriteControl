"""Builders for Focusrite Control request strings.

This mirrors the ``requests`` namespace of the original Node library, but as
composable functions instead of hard-coded per-model constants (control ids
differ per interface — discover yours with ``py fc.py monitor``).

Define your own named constants on top of these::

    from focusrite import requests

    MONITOR_MUTE = 1107          # from `fc.py monitor` on your device
    fc.write(requests.mute(MONITOR_MUTE))       # like Node's clientWrite(...)
    fc.write(requests.set_item(23, True))       # generic
"""

from __future__ import annotations


def token(value) -> str:
    """Render a Python value as a protocol token (bool -> 'true'/'false')."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def set_item(item_id, value, devid="1") -> str:
    """A ``<set>`` request for one control, e.g. set_item(1107, True)."""
    return f'<set devid="{devid}"><item id="{item_id}" value="{token(value)}"/></set>'


def mute(item_id, devid="1") -> str:
    return set_item(item_id, True, devid)


def unmute(item_id, devid="1") -> str:
    return set_item(item_id, False, devid)


# -- handshake / protocol messages (usually sent for you by Connection) --
def client_details(client_key, hostname="PyFocusriteControl") -> str:
    return f'<client-details client-key="{client_key}" hostname="{hostname}"/>'


def device_subscribe(devid="1", subscribe=True) -> str:
    return f'<device-subscribe devid="{devid}" subscribe="{token(subscribe)}"/>'


KEEP_ALIVE = "<keep-alive/>"
