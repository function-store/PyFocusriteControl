"""Minimal, stdlib-only client for the Focusrite Control Server local protocol.

Reverse-engineered protocol (see README) as originally documented by
Mathieu2301/Focusrite-Control-API, reimplemented here in pure Python.
"""

from .client import (
    FocusriteError,
    ServerNotFoundError,
    discover_port,
    Connection,
)

__all__ = [
    "FocusriteError",
    "ServerNotFoundError",
    "discover_port",
    "Connection",
]
