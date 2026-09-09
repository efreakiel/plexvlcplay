# plexvlc

Open the current Plex movie or episode in **VLC** (or any local player) from Plex Web.

![Open in VLC on a Plex movie details page](screenshot.PNG)

Plex’s browser player remuxes or transcodes a lot of files and cannot hand a library item to the player you already have installed. plexvlc sits *next to* Plex: a Chrome/Edge extension injects **Open in VLC**, and a small Python helper on `127.0.0.1` launches the file (or a Plex stream URL) in VLC.

This does **not** patch Plex Media Server. Plex plugins are gone; this is a sidecar.

## What you get

- An **Open in VLC** button on movie/episode pages in Plex Web (`app.plex.tv` and the local `/web` UI)
- The same action in a library poster’s **⋯ More Actions** menu, so you don’t have to open each item
- Toolbar popup, right-click menu, and `Alt+Shift+V`
- Prefers the **file on disk** when this PC can read `Part.file`
- Otherwise streams via a LAN HTTP Plex URL (token on VLC’s command line — the toast tells you)
- Configurable player executable and argument templates (`mpv`, MPC-HC, …)

## Requirements

- Windows 10/11
- Python 3.11+ on PATH (`python`, and `pythonw` for the installed helper)
- [VLC](https://www.videolan.org/vlc/) (or another player you set in config)
- Plex Media Server (local or on your LAN)
- Chrome or Edge (Manifest V3)

## Install

### 1. Helper

From this repo, in PowerShell:

```powershell
git clone https://github.com/efreakiel/plexvlcplay.git
cd plexvlcplay
.\helper\scripts\install.ps1
```

That creates `%APPDATA%\plexvlc\config.json` (current-user ACL only), a **logon scheduled task** that waits for Plex Media Server then starts the helper, plus Start Menu / Startup shortcuts as backup.

No pairing code. The unpacked extension’s frozen ID is enough.

To start the helper right now (without rebooting):

```powershell
.\helper\scripts\start.ps1
```

### 2. Extension

1. Open `chrome://extensions` (or `edge://extensions`)
2. Enable **Developer mode**
3. **Load unpacked** → select this repo’s `extension\` folder
4. Confirm the ID is `hpdhegbljejbmohafhhgdkmbhonodpal` (frozen by the manifest `key`)

### 3. Use it

Any of these open the current movie or episode in VLC:

| Where | What to click |
| --- | --- |
| Details / preplay page | **Open in VLC** next to Plex’s Play button |
| Library grid or hub | Poster **⋯** (bottom-right) → **Open in VLC** in the More Actions menu |
| Any Plex tab | Toolbar icon, right-click the page, or `Alt+Shift+V` |

You do not have to open the details page first. The ⋯ menu is the fast path from a poster wall.

Shows, seasons, photos, and Plex Discover titles are not launched (the helper only accepts movies, episodes, and clips).

Toasts:

- `Opened {title} from disk` — VLC got a filesystem path
- `Streaming {title} from Plex (token on VLC command line)` — VLC is playing a Plex HTTP URL

If you browse Plex at `http://192.168.x.x:32400/web`, the popup offers **Allow this origin**. Grant it, **reload the tab once**, then the button and ⋯ action appear.

## Config

`%APPDATA%\plexvlc\config.json` (see `config.example.json`):

| Key | Meaning |
| --- | --- |
| `listen_port` | Default `18765`. Bind is **always** `127.0.0.1`. If the port is taken, the helper exits 2 — it does not pick another port. |
| `helper_secret` | Optional. Required only for CLI tools with no `Origin` header. The Chrome/Edge extension does not need it. |
| `player.executable` | Empty = auto-discover VLC. Otherwise a full path. **This is arbitrary code execution as your user.** |
| `player.args_file` / `args_url` | Templates. Placeholders: `{paths}`, `{urls}`, `{start_seconds}`, `{sub_file}`, `{title}`. |
| `allowed_extension_ids` | Chrome IDs matching `^[a-p]{32}$`. Empty list = no extension may pair. |

Example mpv:

```json
"player": {
  "name": "mpv",
  "executable": "C:\\Program Files\\mpv\\mpv.exe",
  "args_file": ["--start={start_seconds}", "{paths}"],
  "args_url": ["--start={start_seconds}", "{urls}"],
  "args_extra": []
}
```

## Architecture

```
Plex Web  →  MV3 extension (button / popup)
                 │  POST http://127.0.0.1:18765/v1/launch
                 ▼
           Python helper
                 │  GET /library/metadata/{id}?checkFiles=1
                 ▼
           Plex Media Server
                 │
           vlc.exe  ← local file if it exists, else stream URL
```

The helper binds **only** `127.0.0.1`. The frozen unpacked extension is allowed by Origin; other extensions get 403. After reboot, a logon task waits for **Plex Media Server** (up to two minutes) and starts the helper.

Full design: [DESIGN.md](DESIGN.md).

## Tests

```powershell
cd plexvlcplay
$env:PYTHONPATH = "$pwd\helper"
python -m unittest discover -s tests -v
```

## Uninstall

```powershell
.\helper\scripts\uninstall.ps1
```

Then remove the unpacked extension in `chrome://extensions`.

## Security notes

- The helper is a process launcher. `player.executable` runs as you.
- Loopback is machine-wide (Fast User Switching). Don’t leave the helper running if an untrusted user is logged on to the same PC.
- Stream mode puts `X-Plex-Token` on VLC’s command line. Prefer file mode when the media is local.
- Do not disable TLS verification; plexvlc will rewrite plex.direct HTTPS to LAN HTTP when identity matches.

## Out of scope (v1)

- Appearing as a Plex “Play on…” / Cast target
- Writing watch progress back to Plex
- Plex Discover titles (non-numeric keys)
- Chrome Web Store publish

## License

MIT
