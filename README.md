# MyFocusriteControl

> Mute, unmute, or toggle **just the speaker/monitor output** of a Focusrite
> Scarlett interface from the command line — so you can bind a hotkey (or a
> hardware button) and auto-mute your speakers at logon.

![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![Dependencies](https://img.shields.io/badge/dependencies-none%20(stdlib)-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

Focusrite Control can mute the monitor output independently of headphones, but
it has **no official API and no hotkey**. This tool talks to the local
**Focusrite Control Server** over its (undocumented, reverse-engineered) UDP
discovery + framed-XML protocol — the same mechanism the app itself uses — to
flip that mute in a few milliseconds. It's pure Python standard library: no
`pip install`, no Node, no dependencies.

---

## Features

- 🔇 Mute **only** the monitor/speaker output, leaving headphones untouched.
- ⚡ Fast: a toggle completes in ~100 ms (cached discovery + no fixed waits).
- ⌨️ Hotkey-ready, including a **windowless launcher** (no console flash) that
  works with launchers like **Logitech G HUB**.
- 🚀 **Auto-mute at logon** via a hidden scheduled task.
- 🧩 Model-agnostic: a discovery mode finds the correct mute parameter for your
  specific Scarlett.
- 🪶 Zero third-party dependencies (Python standard library only).

## Requirements

- **Windows** with Python 3.8+ (the `py` launcher). Verify: `py -3 --version`.
- **Focusrite Control** installed, with its background **Server** running (it
  starts with Windows; you don't need the app window open, but it must be
  installed). If discovery fails, open the Focusrite Control app once.

## Install

```powershell
git clone https://github.com/<you>/MyFocusriteControl.git
cd MyFocusriteControl
py -3 fc.py discover      # should print: Focusrite Control Server found on 127.0.0.1:NNNNN
```

There is nothing to build for the CLI itself. (The optional hotkey `.exe` is
built later with a one-line script.)

## Setup

Two one-time steps: find your interface's mute parameter, then authorise this
client so the server accepts its commands.

### 1. Find your mute parameter

The numeric control id for the monitor mute differs per model, so discover it on
your actual device:

```powershell
py -3 fc.py monitor
```

With `monitor` running, **click the Mute button on your speaker output inside
the Focusrite Control app**. The control id whose value flips is your mute
parameter. Save it (replace `1107` with what you saw):

```powershell
py -3 fc.py bind-mute 1107
```

This writes `config.json` (which also stores a stable `client_key`). If nothing
obvious flips, run `py -3 fc.py dump` and inspect `device-dump.xml`.

### 2. Authorise this client (one-time)

The Control Server ignores `set` commands from clients that aren't **approved**.
Recent Focusrite Control versions have no approval UI, so approve this client
directly in the server's allowlist. First run any command once (e.g.
`py -3 fc.py pair`) so the server records this client, then flip its line to
`approved`:

```powershell
$f = "C:\ProgramData\Focusrite\Focusrite Control\Server\Authorisation\auth.csv"
Copy-Item $f "$f.bak" -Force
(Get-Content $f -Raw) -replace ',MyFocusriteControl,not approved', ',MyFocusriteControl,approved' |
    Set-Content $f -NoNewline -Encoding ascii
Get-Content $f
```

The file is `client-key,hostname,status`; your line should now read
`...,MyFocusriteControl,approved`. This persists (the `client_key` is stable).
Check status anytime with `py -3 fc.py pair` (it prints each client's
`authorised=` flag). Revert with `Copy-Item "$f.bak" $f -Force`.

## Usage

```powershell
py -3 fc.py mute            # mute the speakers
py -3 fc.py unmute          # unmute
py -3 fc.py toggle          # flip, fast (uses saved state) — best for a hotkey
py -3 fc.py toggle --wait   # flip, then confirm against the device (slower, certain)
py -3 fc.py status          # show current mute state
```

The device doesn't report the monitor-mute state on connect, so `toggle` tracks
it in `state.json` and flips that — fast and reliable as long as changes go
through this tool. `toggle --wait` additionally reads the device (catching a live
value if one is offered) and waits for the change to echo back.

## Hotkey (no console flash)

Bind your key or hardware button to **`scripts\toggle.exe`** — a tiny windowless
executable that launches `pythonw fc.py toggle` with no console window. Build it
once:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-launcher.ps1
```

Then point your hotkey tool at the resulting `scripts\toggle.exe`.

> **Why an `.exe`?** Launchers such as Logitech G HUB run real executables (and
> `.cmd`) but silently ignore `.vbs`/`.lnk`/scripts. A Windows-subsystem `.exe`
> is the reliable, flash-free option. It auto-detects Python, so it's portable.

If your launcher can pass arguments, one exe covers everything:
`toggle.exe mute`, `toggle.exe unmute`, `toggle.exe "toggle --wait"` (no args ⇒
`toggle`). For terminals or launchers that run scripts, `scripts\toggle.cmd`
(and `mute.cmd` / `unmute.cmd`) also work but briefly show a console.

## Auto-mute at logon

Register a hidden scheduled task that mutes the speakers each time you sign in
(it retries for a bit in case the device isn't ready yet at logon):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-startup-task.ps1
```

Test immediately with `Start-ScheduledTask -TaskName FocusriteMuteOnLogon`, then
check `startup.log`. Remove it with `scripts\uninstall-startup-task.ps1`.

## Python library

Beyond the CLI, you can drive the interface from your own scripts. There are two
layers: a high-level `Focusrite` session and a `requests` module of request
builders (mirroring the original Node library's `requests` + `clientWrite`).

```python
from focusrite import Focusrite, requests

MONITOR_MUTE = 1107   # your id from `fc.py monitor`

# connect_from_config() reuses the approved client_key in config.json
with Focusrite.connect_from_config() as fc:
    fc.mute(MONITOR_MUTE)                    # high-level helper
    fc.set(MONITOR_MUTE, False)             # generic set (bool -> true/false)
    fc.write(requests.mute(MONITOR_MUTE))   # raw request, like Node's clientWrite

    print(fc.get(MONITOR_MUTE))             # read a value (best-effort)
    print(fc.snapshot())                    # {id: value} for everything seen

    for cid, value in fc.watch(10):         # stream control changes for 10s
        print(cid, "->", value)
```

Define your own named constants (ids differ per model) and use them with either
style — `fc.set(MONITOR_MUTE, True)` or `fc.write(requests.set_item(MONITOR_MUTE, True))`.

| Layer | What |
|-------|------|
| `Focusrite` | `connect()` / `connect_from_config()`, `set`/`get`/`snapshot`/`mute`/`unmute`/`toggle`/`watch`/`write`. |
| `focusrite.requests` | `set_item`, `mute`, `unmute`, `device_subscribe`, `client_details`, `token`. |
| `Connection` / `discover_port` | The raw protocol, if you want full control. |

> Reading and subscribing work with any client; **changing** values requires an
> approved `client_key` (see *Setup → Authorise this client*).

The CLI also exposes a raw setter for one-offs: `py -3 fc.py set <id> <value>`.

## Configuration

`config.json` (created on first run):

| Key | Meaning |
|-----|---------|
| `client_key` | Stable UUID identifying this client (matches the `auth.csv` entry). |
| `hostname` | Name shown for this client in the server allowlist. |
| `mute_item_id` | The control id set by `bind-mute`. |
| `value_muted` / `value_unmuted` | Values written for each state (default `true`/`false`). |
| `devid` | Device id (default `1`). |
| `discovery_timeout` | Seconds to wait for the server (default `3.0`). |

Environment overrides (handy for testing): `FOCUSRITE_CONFIG_DIR` (where
`config.json`/`state.json` live) and `FOCUSRITE_DISCOVERY_PORTS`.

## Command reference

| Command | Description |
|---------|-------------|
| `discover` | Find and print the Control Server port. |
| `monitor` | Watch control changes live (to find the mute id). |
| `dump` | Save the raw device XML to a file. |
| `bind-mute <id>` | Save which control id is the mute (`--muted`/`--unmuted` for custom values). |
| `mute` / `unmute` | Set the speaker mute explicitly. |
| `toggle` / `toggle --wait` | Flip the mute (fast / confirmed). |
| `status` | Print the current mute state. |
| `pair` | Show/inspect this client's authorisation state. |
| `probe <id> [--set V]` | Diagnose a control: raw XML, current value, optional set test. |
| `set <id> <value>` | Raw escape hatch: set any control to any value. |

## How it works

- **Discovery** — UDP broadcast `<client-discovery .../>` to ports 30096–30098;
  the server replies with its TCP port.
- **Connect** — TCP to `127.0.0.1:<port>`; every message is framed as
  `Length=XXXXXX <xml>` (payload length as 6 hex digits + a space).
- **Handshake** — `<client-details client-key="…" hostname="…"/>` then
  `<device-subscribe devid="1" subscribe="true"/>`, with periodic `<keep-alive/>`.
- **Authorisation** — the server tracks approved clients in `auth.csv`; only
  approved clients' writes are honored.
- **Set** — `<set devid="1"><item id="<mute id>" value="true|false"/></set>`.

See [`focusrite/client.py`](focusrite/client.py) for the implementation.

## Troubleshooting

- **`No Focusrite Control Server responded`** — the background server isn't
  running. Open the Focusrite Control app once, then retry.
- **`mute`/`toggle` report success but nothing happens** — the client isn't
  approved. Redo *Setup step 2*; confirm with `py -3 fc.py pair` (look for
  `authorised=true`).
- **Hotkey does nothing** — make sure you built and bound `scripts\toggle.exe`
  (not the `.cmd`/`.vbs`). Rebuild after a Python upgrade with
  `scripts\build-launcher.ps1`.
- **`pyw`/`python3` "not found"** — the Python launcher followed `fc.py`'s unix
  shebang to the MS Store alias; invoke with `py -3` / `pyw -3`, or use
  `toggle.exe`, which calls `pythonw.exe` directly.

## Compatibility

Developed against a 3rd-gen Scarlett (18i8-class). It should work with other
Focusrite interfaces that use Focusrite Control (1st–3rd gen Scarlett, Clarett,
etc.) — the mute control id just differs per model, which the `monitor`/`dump`
step resolves. Focusrite Control **2** (newer USB-C ranges) uses a different
backend and is untested.

## Credits & references

This project reimplements, in pure Python, a local protocol reverse-engineered by
the community. Thanks to:

- **[Mathieu2301/Focusrite-Control-API](https://github.com/Mathieu2301/Focusrite-Control-API)**
  — the Node library that documented the core protocol: the `Length=XXXXXX <xml>`
  framing, the `<client-details>` / `<device-subscribe>` / `<keep-alive>`
  handshake, and the `<set devid="1"><item id=… value=…/></set>` request format.
- **[daveyijzermans — "Discover Focusrite Control Server on the network"](https://gist.github.com/daveyijzermans/f0354858b3eb765e19361ab85a6bc55b)**
  — the UDP discovery mechanism (`<client-discovery …/>` broadcast to ports
  30096–30098 and parsing the announced port).

Beyond those, the following were figured out here and aren't (to our knowledge)
documented elsewhere: the client-approval requirement and the
`…\Server\Authorisation\auth.csv` allowlist, and that the monitor mute appears as
a `<mute id=…/>` node whose state streams as `<item id=… value=…/>` updates.

## Disclaimer

Unofficial and **not affiliated with, endorsed by, or supported by Focusrite**.
It relies on an undocumented local protocol discovered by the community and may
break with Focusrite Control updates. Editing `auth.csv` modifies Focusrite
Control's own configuration (a backup is made). Use at your own risk.

## License

Released under the [MIT License](LICENSE).
