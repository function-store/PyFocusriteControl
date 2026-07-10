#!/usr/bin/env python3
"""fc.py - control Focusrite Scarlett monitor/speaker mute from the command line.

Pure standard-library. No pip install required.

Typical workflow
----------------
1.  py fc.py discover            # confirm the ControlServer is reachable
2.  py fc.py monitor             # then toggle "Mute" on your speaker output in
                                 # the Focusrite Control app and note the id
                                 # that flips -> that's your mute parameter id.
3.  py fc.py bind-mute <id>      # save it (optionally --muted/--unmuted values)
4.  py fc.py mute | unmute | toggle | status

Run `py fc.py <command> -h` for per-command help.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

# Allow running as a plain script (py fc.py ...) without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from focusrite import Connection, ServerNotFoundError, discover_port  # noqa: E402
from focusrite.client import FocusriteError  # noqa: E402

# When launched via pythonw.exe / a hidden window there is no console, so
# sys.stdout / sys.stderr are None and any print() would crash. Send them to
# the void instead, so a hotkey toggle runs silently and reliably.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")


ROOT = Path(__file__).resolve().parent
# config/state live next to the script unless overridden (tests point this at a
# temp dir so they never touch a real user config).
_HOME = Path(os.environ.get("FOCUSRITE_CONFIG_DIR") or ROOT)
CONFIG_PATH = _HOME / "config.json"
STATE_PATH = _HOME / "state.json"

DEFAULT_CONFIG = {
    "client_key": None,          # stable UUID, generated on first run
    "hostname": "MyFocusriteControl",  # name shown in the FC app for approval
    "devid": "1",
    "mute_item_id": None,        # discovered per model (step 2/3 above)
    "value_muted": "true",
    "value_unmuted": "false",
    "discovery_timeout": 3.0,
}

_APPROVAL_TAG_RE = re.compile(r"<approval\b[^>]*/?>")
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def parse_approvals(text: str):
    """Yield attribute dicts for every <approval .../> tag in ``text``."""
    for tag in _APPROVAL_TAG_RE.findall(text):
        yield dict(_ATTR_RE.findall(tag))

_ITEM_RE = re.compile(r'<item\b[^>]*\bid=["\'](\d+)["\'][^>]*\bvalue=["\']([^"\']*)["\']')


# --------------------------------------------------------------------------
# config / state helpers
# --------------------------------------------------------------------------
def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"warning: could not read {CONFIG_PATH.name}: {exc}", file=sys.stderr)
    if not cfg.get("client_key"):
        cfg["client_key"] = str(uuid.uuid4())
        save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(**kwargs) -> None:
    """Merge keys into state.json (e.g. muted=..., port=...)."""
    st = load_state()
    st.update(kwargs)
    st["ts"] = time.time()
    STATE_PATH.write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")


def _connect_on_port(cfg: dict, port: int) -> Connection:
    return Connection(
        port, cfg["client_key"], hostname=cfg.get("hostname", "MyFocusriteControl")
    ).connect()


def connect(cfg: dict) -> Connection:
    """Discover the server and connect (used by the non-latency-critical cmds)."""
    port = discover_port(timeout=float(cfg["discovery_timeout"]))
    save_state(port=port)
    return _connect_on_port(cfg, port)


def _prime(conn: Connection, target: str, timeout: float = 0.8):
    """Wait until the device tree arrives; capture ``target``'s live value.

    Returns (got_any_frame, live_value_or_None). Waiting for the device
    arrival (rather than a fixed sleep) is what makes set commands both fast
    and reliably honored.
    """
    seen = {"any": False, "val": None}

    def pred(p: str) -> bool:
        seen["any"] = True
        if target:
            for i, v in _ITEM_RE.findall(p):
                if i == target:
                    seen["val"] = v
        return "<device" in p or "devid=" in p or "<mute" in p

    conn.read_until(pred, timeout)
    return seen["any"], seen["val"]


def open_conn(cfg: dict, prime: bool = True):
    """Fast-path connect: reuse the cached port, else discover.

    With ``prime=True`` it waits for the device tree (reliable, and captures the
    live mute value). With ``prime=False`` it returns as soon as the socket is
    open (fastest; the caller relies on saved state). Returns
    (connection, live_mute_value_or_None).
    """
    target = str(cfg.get("mute_item_id") or "")
    cached = load_state().get("port")
    if cached:
        try:
            conn = _connect_on_port(cfg, int(cached))
            if not prime:
                return conn, None
            got, live = _prime(conn, target)
            if got:
                return conn, live
            conn.close()
        except OSError:
            pass  # stale/refused port -> rediscover below
    port = discover_port(timeout=float(cfg["discovery_timeout"]))
    save_state(port=port)
    conn = _connect_on_port(cfg, port)
    if not prime:
        return conn, None
    _, live = _prime(conn, target)
    return conn, live


def _item_is(payload: str, item: str, value: str) -> bool:
    return any(i == item and v == value for i, v in _ITEM_RE.findall(payload))


def _apply(cfg: dict, item: str, value: str, confirm_timeout: float = 0.6) -> bool:
    """Connect (fast), send a set, wait briefly for the echo. Returns confirmed."""
    conn, _live = open_conn(cfg)
    try:
        conn.set_item(item, value, devid=cfg["devid"])
        echoed = conn.read_until(lambda p: _item_is(p, item, value), confirm_timeout)
    finally:
        conn.close()
    return echoed is not None


def read_item_values(conn: Connection, seconds: float) -> dict:
    """Collect the latest value seen for every item id over ``seconds``."""
    values: dict[str, str] = {}
    for payload in conn.read(seconds):
        for item_id, value in _ITEM_RE.findall(payload):
            values[item_id] = value
    return values


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_discover(args, cfg) -> int:
    port = discover_port(timeout=float(cfg["discovery_timeout"]))
    print(f"Focusrite Control Server found on 127.0.0.1:{port}")
    return 0


def cmd_monitor(args, cfg) -> int:
    print("Connecting... once connected, toggle the *Mute* button on your")
    print("speaker/monitor output inside the Focusrite Control app.")
    print("The item id whose value flips is your mute parameter.\n")
    seen: dict[str, str] = {}
    with connect(cfg) as conn:
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            for payload in conn.read(0.5):
                if args.raw:
                    print(payload)
                for item_id, value in _ITEM_RE.findall(payload):
                    if seen.get(item_id) != value:
                        change = "  <-- CHANGED" if item_id in seen else ""
                        seen[item_id] = value
                        print(f"id={item_id:<5} value={value!r}{change}")
    print(f"\nDone. {len(seen)} distinct control(s) observed.")
    return 0


def cmd_dump(args, cfg) -> int:
    """Save the raw XML the server pushes after subscribing."""
    out = Path(args.out) if args.out else (ROOT / "device-dump.xml")
    chunks = []
    with connect(cfg) as conn:
        for payload in conn.read(args.seconds):
            chunks.append(payload)
    out.write_text("\n".join(chunks), encoding="utf-8")
    print(f"Wrote {len(chunks)} payload(s) to {out}")
    return 0


def _require_mute_id(cfg) -> str:
    mute_id = cfg.get("mute_item_id")
    if not mute_id:
        print(
            "No mute parameter configured yet. Run `py fc.py monitor`, toggle "
            "mute in the app to find the id, then `py fc.py bind-mute <id>`.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return str(mute_id)


def cmd_bind_mute(args, cfg) -> int:
    cfg["mute_item_id"] = str(args.item_id)
    if args.muted is not None:
        cfg["value_muted"] = args.muted
    if args.unmuted is not None:
        cfg["value_unmuted"] = args.unmuted
    save_config(cfg)
    print(
        f"Saved: mute item id={cfg['mute_item_id']} "
        f"(muted={cfg['value_muted']!r}, unmuted={cfg['value_unmuted']!r})"
    )
    return 0


def _set_mute(cfg, muted: bool) -> int:
    mute_id = _require_mute_id(cfg)
    value = cfg["value_muted"] if muted else cfg["value_unmuted"]
    ok = _apply(cfg, mute_id, value)
    save_state(muted=muted)
    state = "MUTED" if muted else "UNMUTED"
    print(f"{state}" + (" (confirmed)" if ok else " (sent)"))
    return 0


def cmd_mute(args, cfg) -> int:
    return _set_mute(cfg, True)


def cmd_unmute(args, cfg) -> int:
    return _set_mute(cfg, False)


def cmd_status(args, cfg) -> int:
    mute_id = _require_mute_id(cfg)
    conn, live = open_conn(cfg, prime=True)
    conn.close()
    if live is None:
        st = load_state()
        note = "" if "muted" in st else " (never set by us)"
        guess = "MUTED" if st.get("muted") else "UNMUTED"
        print(f"{guess} (saved state{note})")
        return 0
    muted = live == cfg["value_muted"]
    print(f"{'MUTED' if muted else 'UNMUTED'} (item {mute_id} = {live!r})")
    return 0


def _toggle(cfg, wait: bool) -> int:
    mute_id = _require_mute_id(cfg)
    # prime only when waiting: that's when a live value is worth capturing.
    conn, live = open_conn(cfg, prime=wait)
    try:
        if live is not None:
            muted_now = live == cfg["value_muted"]
        else:
            muted_now = bool(load_state().get("muted", False))
        new_muted = not muted_now
        value = cfg["value_muted"] if new_muted else cfg["value_unmuted"]
        conn.set_item(mute_id, value, devid=cfg["devid"])
        confirmed = None
        if wait:
            confirmed = conn.read_until(lambda p: _item_is(p, mute_id, value), 0.7)
        else:
            conn.read_until(lambda p: False, 0.05)  # brief flush before close
    finally:
        conn.close()
    save_state(muted=new_muted)
    label = "MUTED" if new_muted else "UNMUTED"
    if wait:
        print(f"{label}" + (" (confirmed)" if confirmed else " (no echo)"))
    else:
        print(label)
    return 0


def cmd_toggle(args, cfg) -> int:
    return _toggle(cfg, wait=args.wait)


def cmd_pair(args, cfg) -> int:
    """Get this client authorised so its `set` commands are honored.

    Presents our hostname to the ControlServer and watches the approval state.
    Approve this client in the Focusrite Control desktop app (its remote-device
    / "allow to connect" prompt) while this runs. Because our client_key is
    stable, approval persists across future runs.
    """
    host = cfg.get("hostname", "MyFocusriteControl")
    print(f"Connecting as hostname={host!r}")
    print(f"client_key={cfg['client_key']}\n")
    print("=> Open the Focusrite Control DESKTOP app now and approve this client")
    print("   (look for an allow/approve prompt, or a Remote Control/Devices")
    print(f"   setting). It should appear named {host!r} (or blank).\n")

    seen: dict = {}
    responded: set = set()
    authorised_ours = set()

    def is_ours(hn: str) -> bool:
        return hn == host or hn == ""

    with connect(cfg) as conn:
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            for payload in conn.read(0.5):
                for a in parse_approvals(payload):
                    hid = a.get("id", "?")
                    hn = a.get("hostname", "")
                    typ = a.get("type", "?")
                    auth = a.get("authorised", "?")
                    state = (hn, typ, auth)
                    if seen.get(hid) != state:
                        seen[hid] = state
                        tag = "  <-- us" if is_ours(hn) else ""
                        print(f"approval: id={hid} hostname={hn!r} "
                              f"type={typ} authorised={auth}{tag}")
                        # Optionally answer the handshake from our side.
                        if (args.respond and is_ours(hn) and typ == "request"
                                and hid not in responded):
                            responded.add(hid)
                            conn.send(f'<approval hostname="{host}" id="{hid}" '
                                      f'type="response" authorised="true"/>')
                            print(f"  -> sent affirmative approval response for {hid}")
                    if is_ours(hn) and auth == "true":
                        authorised_ours.add(hid)
            if authorised_ours:
                print(f"\nAUTHORISED (id={sorted(authorised_ours)}).")
                print("Now run:  py fc.py mute")
                return 0

    print("\nStill not authorised.")
    print("- Make sure the Focusrite Control DESKTOP app is actually open.")
    print("- If you saw no prompt, try again with:  py fc.py pair --respond")
    print("- Tell me what the approval lines above showed and I'll adjust.")
    return 1


def cmd_probe(args, cfg) -> int:
    """Diagnose a control: show its raw element, current value, and test a set.

    Helps when mute/toggle report success but nothing happens. It surfaces the
    exact XML the device uses for the item (so we can see the real value tokens
    and structure) and any approval/error messages from the server.
    """
    item = str(args.item_id)
    signals = ("approv", "denied", "reject", "unauthor", "error", "not-allowed",
               "permission", "pending")

    with connect(cfg) as conn:
        # Initial burst (server's response to our handshake).
        head = list(conn.read(1.5))
        interesting = [p for p in head
                       if any(s in p.lower() for s in signals)]
        if interesting:
            print("== server messages that may indicate approval/permission ==")
            for p in interesting:
                print("  " + p[:400])
            print()

        blob = "\n".join(head)
        # Every element that mentions this id (as its id, or referencing it).
        elems = re.findall(r"<[^<>]*\b%s\b[^<>]*>" % re.escape(item), blob)
        print(f"== raw XML mentioning id {item} ({len(elems)} match) ==")
        for e in dict.fromkeys(elems):        # de-dupe, keep order
            print("  " + e)
        vals = {i: v for i, v in _ITEM_RE.findall(blob)}
        current = vals.get(item)
        print(f"\ncurrent value of item {item}: {current!r}")

        if args.set is not None:
            print(f"\n== sending: set item {item} = {args.set!r} ==")
            conn.set_item(item, args.set, devid=cfg["devid"])
            after = read_item_values(conn, 1.2)
            echoed = after.get(item)
            if echoed is None:
                print("  no echo/change seen from device (write may be ignored)")
            elif echoed == args.set:
                print(f"  device now reports {echoed!r}  <-- write took effect")
            else:
                print(f"  device now reports {echoed!r} (not the value we sent)")
    return 0


def cmd_set(args, cfg) -> int:
    """Raw escape hatch: set any item to any value."""
    ok = _apply(cfg, str(args.item_id), args.value)
    print(f"sent item {args.item_id} = {args.value!r}"
          + (" (confirmed)" if ok else ""))
    return 0


# --------------------------------------------------------------------------
# arg parsing
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fc.py", description="Control Focusrite Scarlett monitor mute."
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("discover", help="find and print the ControlServer port")

    m = sub.add_parser("monitor", help="watch control changes to find the mute id")
    m.add_argument("--seconds", type=float, default=60.0, help="how long to watch")
    m.add_argument("--raw", action="store_true", help="also print raw XML payloads")

    d = sub.add_parser("dump", help="save the raw device XML to a file")
    d.add_argument("--seconds", type=float, default=3.0)
    d.add_argument("--out", help="output path (default device-dump.xml)")

    b = sub.add_parser("bind-mute", help="save which item id is the mute control")
    b.add_argument("item_id", help="the item id that toggles mute")
    b.add_argument("--muted", help="value that means muted (default 'true')")
    b.add_argument("--unmuted", help="value that means unmuted (default 'false')")

    sub.add_parser("mute", help="mute the speaker output")
    sub.add_parser("unmute", help="unmute the speaker output")
    tg = sub.add_parser("toggle", help="toggle the speaker output mute")
    tg.add_argument("-w", "--wait", action="store_true",
                    help="prime + confirm via the device (slower, certain)")
    sub.add_parser("status", help="print current mute state")

    pa = sub.add_parser("pair", help="get this client authorised in the FC app")
    pa.add_argument("--seconds", type=float, default=90.0, help="how long to wait")
    pa.add_argument("--respond", action="store_true",
                    help="also answer the approval handshake from our side")

    pr = sub.add_parser("probe", help="diagnose a control (raw XML + set test)")
    pr.add_argument("item_id", help="item id to inspect, e.g. 1107")
    pr.add_argument("--set", help="also try setting this value and read it back")

    s = sub.add_parser("set", help="raw: set any item id to any value")
    s.add_argument("item_id")
    s.add_argument("value")

    return p


COMMANDS = {
    "discover": cmd_discover,
    "monitor": cmd_monitor,
    "dump": cmd_dump,
    "bind-mute": cmd_bind_mute,
    "mute": cmd_mute,
    "unmute": cmd_unmute,
    "toggle": cmd_toggle,
    "status": cmd_status,
    "pair": cmd_pair,
    "probe": cmd_probe,
    "set": cmd_set,
}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config()
    try:
        return COMMANDS[args.command](args, cfg)
    except ServerNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except FocusriteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
