# FreeDM — Free Download Manager

[![CI](https://github.com/EddyGameDev/FreeDM/actions/workflows/ci.yml/badge.svg)](https://github.com/EddyGameDev/FreeDM/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/EddyGameDev/FreeDM)](https://github.com/EddyGameDev/FreeDM/releases/latest)
[![License](https://img.shields.io/badge/license-PolyForm--Noncommercial%201.0.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)

A free, **source-available** download manager for Windows, in the style of
Internet Download Manager. It splits a file into many pieces, fetches them in
parallel, and puts them back together — with pause, resume, a persistent queue
and browser handoff. No licence fees, no ads, no paid APIs, no account.

> **Licence:** FreeDM is **source-available** under the
> [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0).
> You may use, change and redistribute it for noncommercial purposes; commercial
> use is not permitted. It is *not* an open-source licence — see
> [LICENSE](LICENSE) for the full terms and [NOTICE](NOTICE) for the copyright
> notice.

---

## What it does

**Downloading**

- **Segmented downloads** — the file is split into pieces fetched in parallel
  over `Range` requests, and written straight into one `.part` file.
- **Dynamic splitting** — the remaining work is kept in a queue and re-divided
  as workers finish, and the piece size (1–8 MB) follows the *slowest* active
  connection, so one bad pipe cannot hold back the whole file.
- **Pause, resume and crash-safe resume** — progress is written to a sidecar
  next to the file; restarting continues where it stopped.
- **Safe resume** — the server's `ETag`/`Last-Modified` are checked, so a
  changed file restarts cleanly instead of producing a corrupt one.
- **Integrity** — the finished size is checked against the advertised size, and
  an expected `sha256`/`sha512`/`sha1`/`md5` digest is verified.
- **Streams** — an HLS (`.m3u8`) or DASH (`.mpd`) playlist is downloaded
  segment by segment and joined into one file, with AES-128 decryption.
- **Mirrors** — alternative sources for the same file, tried in turn.
- **Proxies** — HTTP or SOCKS, with credentials and a bypass list.
- **Speed limits** — per download, and one cap for everything at once.

**The queue**

- Jobs, status and segment offsets are kept in a local SQLite database, so
  closing the app (or the machine) loses nothing.
- **Categories** with editable rules, and an auto-sort toggle that files
  downloads into `Video/`, `Music/`, `Documents/` and so on.
- A **search box** and status filter that hide the rows that do not match.
- **Scheduled starts** and a **daily window** in which downloads may run.
- **Export and import** the queue as a file (a plain list of URLs works too).
- **Shut down when done**, if you want the machine to power off when the queue
  is empty.

**The browser**

- A Chrome/Edge **and** Firefox extension that hands browser downloads to
  FreeDM, with the page's cookies.
- A right-click **"Download with FreeDM"** menu for links, videos and pages.
- A **native messaging host**, so the browser can start FreeDM by itself.

**Also**

- A **console build** with live progress, for the terminal.
- An **installer** (Inno Setup script) and a fully portable build.
- An **opt-in log file** and an **opt-in update check** — neither phones home
  unless you ask it to.

---

## Download

Grab the latest release (the page always shows the current build):

**<https://github.com/EddyGameDev/FreeDM/releases/latest>**

It contains three files:

| File | What it is |
|---|---|
| `FreeDM-<version>.exe` | the app — double-click it, nothing to install |
| `FreeDM-cli-<version>.exe` | the same program with a console attached, so it prints live progress |
| `FreeDM-Setup-<version>.exe` | an installer with shortcuts and an uninstaller |

The portable build needs no installation and makes no registry changes: the
queue and your settings live in `%APPDATA%\FreeDM`, so you can delete the
executable and nothing is left behind. The uninstaller never deletes your
queue either.

---

## Using it

### The window

1. Paste a URL into the **URL(s)** field. To add several at once, paste one
   URL per line — each valid line becomes its own job; lines that are not
   http(s) URLs are reported, and duplicates are skipped.
2. Pick a **Save to** folder (defaults to your Downloads folder).
3. Set the number of **Threads** (more is faster on big files).
4. Click **Add Download**.

The buttons under the list are **Pause / Resume / Cancel / Remove**,
**Open File**, **Open Folder**, **Show in Folder**, **Limit...**,
**Global Limit...**, **Checksum...**, **Details...**, **Clean Up...**,
**Export...**, **Import...** and **Clear Completed**. The **Schedule...** button
picks a date and time for the selected jobs.

The **Search** box and the **Status** filter hide the rows that do not match
(by name, URL, host or status) while the app keeps running. The filter is
remembered for the next launch.

A few of the rest, in one place:

- **Limit...** — a live speed cap for the selection (KB/s, `0` = unlimited).
- **Global Limit...** — a cap on the *combined* speed of every download.
- **Checksum...** — the digest the site publishes; a mismatch fails the job and
  shows both digests.
- **Details...** — everything about a job, including the full error text.
- **Network...** — the proxy, the bypass list, the IPv4/IPv6 preference, and
  a **Test connection** button.
- **Categories...** — the rules that decide which folder a file lands in.
- **Mirrors...** — alternative sources for a file.
- **Clean Up...** — deletes abandoned `.part` files older than the age you
  set; running downloads are never touched.
- **About FreeDM...** — the version, an update check and the log switch.

Only a few downloads run at once (default 3; set **Active:** in the toolbar).
The rest show **queued**; select a row and use **Start Now**, **Move Up** or
**Move Down** to change the order.

### The command line

```
FreeDM-cli.exe "https://example.com/big.iso" -o C:\Downloads -t 16
FreeDM-cli.exe "https://example.com/big.iso" --limit 2000000   # 2 MB/s cap
FreeDM-cli.exe --version      # the version, the licence and where things live
FreeDM-cli.exe --help
```

The console build prints live progress. The windowed build cannot print
anything (it has no console attached), so `FreeDM.exe --version` shows a small
dialog instead.

### Browser handoff

1. Click **Browser...** → **Export extension**. That copies the extension to
   `%APPDATA%\FreeDM\extension` and opens the folder.
2. In Chrome/Edge open `chrome://extensions` (or `edge://extensions`), turn on
   **Developer mode**, click **Load unpacked**, and pick that folder.
   *Firefox:* **Export for Firefox...**, then `about:debugging#/runtime/this-firefox`
   → **Load Temporary Add-on...**.
3. Open the extension's **Options**, paste the token from the **Browser...**
   dialog, and **Save**.

A download started in the browser is then handed to FreeDM — URL, cookies,
referer and user-agent — and the browser's own copy is cancelled. If FreeDM is
closed, the browser download simply continues. The control server listens only
on `127.0.0.1:6801` and needs the token; uncheck **Accept downloads from the
browser** to turn it off.

**Install native host** lets the browser start FreeDM by itself when a download
is handed over while the app is closed. Without it the download stays in the
browser.

---

## Building from source

```
python -m pip install -r requirements.txt -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File build.ps1
```

`build.ps1` produces `dist\FreeDM.exe` (windowed) and `dist\FreeDM-cli.exe`
(console), and generates the icon if it is missing. To build the installer too
(needs [Inno Setup](https://jrsoftware.org/isdl.php), which is free):

```
iscc installer\FreeDM.iss      # -> dist\FreeDM-Setup-<version>.exe
```

## Testing

```
python -m pytest            # the whole suite
python tests\test_w1.py     # or one suite at a time
```

The suite runs on Windows, Ubuntu and macOS in CI
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)), which also builds
the app, compiles the installer, installs it and runs the *installed* program.

## Changing the version

The version appears in a few files, so set them all at once:

```
python scripts\set_version.py 1.8.0
```

A test checks that they agree, so they cannot drift apart.

---

## Security

FreeDM was reviewed for security twice; the findings and the fixes are in
[`docs/SECURITY.md`](docs/SECURITY.md), and the whole project was reviewed in
[`docs/REVIEW.md`](docs/REVIEW.md). In short:

- The control server listens on `127.0.0.1` only, needs a 256-bit token for
  every state-changing request, refuses a `Host` header that is not loopback,
  and gives no CORS permission to ordinary web pages — only to the extension.
- The extension keeps the token in `chrome.storage.local`, so it never leaves
  the device, and asks for no permission it does not use.
- A playlist can only name `http(s)` URLs, cannot reach your local network
  unless you allow it, and never carries your own headers to another host.
- The queue database, the token and the proxy password are stored in plain
  text under `%APPDATA%\FreeDM`. On a shared Windows account, other users of
  that account can read them.

## Where things stand

[`docs/MILESTONE_3.md`](docs/MILESTONE_3.md) holds the plan for what comes
next, [`docs/MILESTONE_2.md`](docs/MILESTONE_2.md) records the finished work
and [`docs/REVIEW.md`](docs/REVIEW.md) is the review behind the plan.
[`docs/FEATURES.md`](docs/FEATURES.md) lists every feature and where it
lives; [`docs/FILE_MAP.md`](docs/FILE_MAP.md) is the map of the source tree.

## Project layout

```
FreeDM/
├── freedm/                 # the application
│   ├── engine/             # the download engine
│   ├── gui/                # the window
│   ├── version.py          # the version, in one place
│   └── ...                 # the rest of the modules
├── extension/              # the browser extension (Chrome/Edge/Firefox)
├── tests/  scripts/  docs/  releases/  dist/
├── LICENSE  NOTICE  CHANGELOG.md  README.md
```

## Licence

PolyForm Noncommercial 1.0.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
