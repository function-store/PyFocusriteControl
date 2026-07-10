"""Minimal, stdlib-only client for the Focusrite Control Server local protocol.

Reverse-engineered protocol (see README) as originally documented by
Mathieu2301/Focusrite-Control-API, reimplemented here in pure Python.

Two layers:
  - :class:`Connection` / :func:`discover_port` — the raw protocol.
  - :class:`Focusrite` + :mod:`focusrite.requests` — an ergonomic high-level API.
"""

from . import requests
from .api import Focusrite
from .client import (
    Connection,
    FocusriteError,
    ServerNotFoundError,
    discover_port,
)

__all__ = [
    "Focusrite",
    "requests",
    "Connection",
    "discover_port",
    "FocusriteError",
    "ServerNotFoundError",
]
