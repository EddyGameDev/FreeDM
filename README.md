# FreeDM — Free Download Manager

A 100% free, **source-available** Internet Download Manager (IDM) alternative.
Multi-threaded segmented downloads, pause/resume, crash-safe resume, and a
simple GUI. No license fees, no ads, no paid APIs.

> **License:** FreeDM is **source-available** under the
> [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0).
> You may use, change and redistribute it for noncommercial purposes; commercial
> use is not permitted. It is *not* an open-source license — see
> [LICENSE](LICENSE) for the full terms and [NOTICE](NOTICE) for the copyright
> notice.

## Download / Run

**Windows build (single file, no installer):**
<https://github.com/EddyGameDev/FreeDM/releases/tag/v1.1.0>

```
FreeDM-1.1.0.exe
```

Just double-click it — that launches the GUI. It needs no installation and
makes no registry changes; the queue and your settings live in
`%APPDATA%\FreeDM`.

The built application in a source checkout is:

```
dist\FreeDM.exe
```

### GUI usage
1. Paste a URL into the **URL(s)** field. To add several at once, paste one URL
   per line (or separated by spaces) — each valid line becomes its own job;
   lines that are not http(s) URLs are reported, and duplicates are skipped.
2. Pick a **Save to** folder (defaults to your Downloads folder).
3. Set the number of **Threads** (more = faster on big files).
4. Click **Add Download**.

Tick **Watch clipboard** to have FreeDM offer a link you copy anywhere. It is
off by default, remembers your choice, and always asks before adding.

Use the buttons below the list to **Pause / Resume / Cancel / Remove**,
**Open File**, **Open Folder**, **Show in Folder**, **Limit...**,
**Global Limit...**, **Checksum...**, **Details...**, **Clean Up...**,
**Export...**, **Import...**, or **Clear Completed**.

The **Search** box and the **Status** filter above the list hide the rows that
do not match (by name, URL, host or status) while the app keeps running. The
filter is remembered for the next launch.

**Sort into category folders** saves new downloads into a subfolder named after
their type (Video, Music, Documents, Archives, Programs, Other). Click
**Categories...** to edit the rules. **Export...** writes the queue to a file
and **Import...** reads it back (a plain list of URLs also works).

**Schedule...** picks a date and time for the selected jobs: they wait until
then and the schedule survives a restart. The **Window:** control in the filter
bar limits downloads to certain hours of the day (e.g. `01:00` – `06:00`; it
may run past midnight). **Shut down when done** powers the machine off once
every job has finished — it always asks first.

**Network...** configures a proxy (HTTP or SOCKS) with an optional user name
and password, plus a bypass list for hosts that must be reached directly, and
a **Test connection** button that checks the settings with a real request.
**Mirrors...** sets alternative sources for a file: a mirror is a base URL and
the original path is appended to it, so a slow server can be replaced by a
fast one.

**Limit...** sets a live speed cap (in KB/s; `0` or empty = unlimited) on the
selected downloads and remembers it as the default for new downloads.
**Global Limit...** caps the *combined* speed of every download — useful on a
metered or shared connection. **Details...** shows the full job information,
including the complete error text when something fails. A failed or cancelled
job can be retried with **Resume** (it re-probes and continues from the `.part`
file).

**Checksum...** takes the digest published by the site (`sha256:1a2b3c…`, or
just the 64-character hex digest) and verifies the file when the download
finishes. A mismatch marks the job as failed and shows both digests. The
digest is remembered for new downloads.

**Clean Up...** finds abandoned `.part` and `.part.state.json` files left over
from downloads you gave up on and deletes them. Only files older than the age
you set are listed, so running downloads are never touched.

The app remembers your last save folder, thread count, default speed limit and
window size/position. If the queue ever looks wrong, delete
`%APPDATA%\FreeDM\freedm.db` to reset the queue *and* preferences.

The queue is saved automatically. Close the app mid-download and reopen it:
unfinished jobs are listed and resume (toggle **Auto-resume** in the toolbar).
The database lives at `%APPDATA%\FreeDM\freedm.db`.

Only a few downloads run at once (default 3; set **Active:** in the toolbar).
The rest show **queued**. Select a row and use **Start Now**, **Move Up**, or
**Move Down** to control the order.

For sites that need a login or block hotlinking, click **Headers...** and add
lines such as `Referer: https://example.com/` or `Cookie: session=...`. Those
headers apply to downloads added afterwards.

### Browser handoff (Chrome / Edge)

1. Click **Browser...**, then **Export extension**. This writes the extension to
   `%APPDATA%\FreeDM\extension` and opens the folder.
2. In Chrome/Edge open `chrome://extensions` (or `edge://extensions`), turn on
   **Developer mode**, click **Load unpacked**, and choose that folder.
3. Open the extension's **Options**, paste the token from the **Browser...**
   dialog, and click **Save**.

Now a download started in the browser is handed to FreeDM (URL, cookies,
referer and user-agent) and the browser's own copy is cancelled. If FreeDM is
closed, the browser download continues as usual. The control server listens only
on `127.0.0.1:6801` and requires the token; uncheck **Accept downloads from the
browser** to turn it off.

**Firefox:** click **Export for Firefox...** and load the folder with
`about:debugging#/runtime/this-firefox` → **Load Temporary Add-on...**. The
handoff works exactly like Chrome/Edge.

**Right-click → Download with FreeDM** hands a link, a video or a page to
FreeDM, with that page's cookies, so protected links work too.

**Install native host** lets the browser start FreeDM by itself when a
download is handed over while the app is closed. Without it the download
simply stays in the browser.

## Command line

The same program also works from a terminal:

```
FreeDM-cli.exe "https://example.com/big.iso" -o C:\Downloads -t 16
FreeDM-cli.exe "https://example.com/big.iso" --limit 2000000   # 2 MB/s cap
```

`FreeDM-cli.exe` is the **console build**: it prints live progress. The
normal `FreeDM.exe` is a windowed app and cannot print anything (it has no
console attached).

## Installing

The portable build needs nothing: download `FreeDM-1.4.0.exe` and run it.
Your queue and settings live in `%APPDATA%\FreeDM` — nothing is written to
the registry, so the program can be deleted by simply removing the file.

If you prefer an installer, `installer/FreeDM.iss` is a ready-made
[Inno Setup](https://jrsoftware.org/isdl.php) script (Inno Setup is free).
It installs both executables, the licence and the browser extension, adds
Start-menu and optional desktop shortcuts, and adds an uninstaller. The
uninstaller never deletes your queue.

To build it yourself:

```
iscc installer\FreeDM.iss      # -> dist\FreeDM-Setup-1.4.0.exe
```

## About, updates and the log file

**About FreeDM...** shows the version and has two optional extras:

- **Check for updates** - reads one small public `VERSION.json` and tells you
  whether a newer build exists. It only ever runs when you press the button,
  and it sends nothing about you.
- **Write a log file** - a rotating log (2 MB, three old files kept) in
  `%APPDATA%\FreeDM\freedm.log`, for bug reports. It is off unless you turn
  it on, and it records the app's own events, never your URLs, file names,
  cookies or tokens.

## Building from source

```
python -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File build.ps1
```

`build.ps1` builds `dist\FreeDM.exe` (windowed) and `dist\FreeDM-cli.exe`
(console), and generates `icon.ico` if it is missing.

Run the tests with either:

```
python -m pytest            # the whole suite in one command
python tests\test_w1.py     # or one suite at a time
```

## Streaming media (HLS / DASH)

Paste a playlist address (`.m3u8` or `.mpd`) and FreeDM downloads the
segments and joins them into one file:

```
FreeDM.exe "https://example.com/live/stream.m3u8" -o C:\Videos
```

- **HLS**: master playlists (the best quality is chosen) and media playlists,
  including AES-128 encrypted segments, byte ranges and the initialisation
  segment.
- **DASH**: manifests with `SegmentTemplate` and `SegmentList`.
- An interrupted stream **continues** instead of starting over.
- A playlist URL is also found when you paste the address of a page that
  links to one.

The file is written as it comes (MPEG-TS, or fragmented MP4). Turning it into
a single MP4 would need FFmpeg, which is not bundled.

## How it works

- **Probe** the URL (HEAD, then a tiny ranged GET) for size, filename and
  whether the server supports `Accept-Ranges: bytes`.
- **Session fidelity**: one `requests.Session` per download carries cookies,
  `Referer`, `User-Agent`, and `Authorization` on the probe and every segment.
  Cookies can be passed as a dict, a cookie string, or an extension-style list.
  Redirects are followed once and the final URL is reused.
- **Segmented download**: the file is split into many pieces; a pool of worker
  threads fetches each piece with `Range: bytes=X-Y` and writes it to its own
  offset in a single `.part` file. The remaining work is kept in a queue, so
  a worker that finishes early takes over the largest piece still pending and
  splits it if needed. The piece size (1–8 MB) follows the *slowest* active
  connection, so one slow pipe cannot hold back a large part of the file.
- **Fallback**: servers without Range support get a normal single-stream
  download.
- **Resume**: progress per piece is saved to `<file>.part.state.json` every
  half second. Pause, close, crash, or reboot — restarting reuses the `.part`
  file and only downloads what is missing.
- **Resume integrity**: the state records the server's `ETag`/`Last-Modified`.
  If the remote file changed, the stale partial is discarded and the download
  restarts instead of producing a corrupt file.
- **Integrity checks**: a short download is never reported as done, and an
  expected `sha256`/`sha512`/`sha1`/`md5` digest is verified when the file
  finishes (a mismatch fails the job and shows both digests).
- **Persistent queue**: every job, status and segment offset is mirrored to a
  local SQLite DB. On launch the queue is restored; unfinished jobs resume
  automatically. If the `.part.state.json` sidecar is lost, the DB supplies the
  segment offsets. A broken DB never aborts an active download.
- **Polite concurrency**: only `max_active` jobs run (3 by default); total and
  per-host connection budgets cap thread counts. `429`/`503` responses honour
  `Retry-After` instead of hammering the server.
- **Streaming media**: HLS and DASH playlists are downloaded segment by
  segment into one file, with AES-128 decryption and resume.
- **Browser handoff**: a Chrome/Edge extension pauses a browser download, asks
  the app to take over through a loopback-only, token-protected endpoint, then
  cancels the browser copy (or resumes it if the app is closed).
- **Retries**: each piece retries up to 6 times with exponential backoff.
- **Rate limiting**: a per-download token-bucket cap, settable live from the GUI
  (**Limit...**) and persisted; `0` means unlimited. **Global Limit...** caps
  the combined throughput of all downloads.
- **No silent overwrite**: if the destination already exists, the default is to
  save as `name (1).ext`. `on_existing` also accepts `overwrite` or `cancel`.
- **Disk-space check**: the download fails early with a clear message when the
  destination drive is too full.

## Project layout

```
FreeDM/
├── freedm/                 # THE APPLICATION (import as `freedm.*`)
│   ├── main.py             # entry point: GUI / CLI / self-tests / native host
│   ├── engine.py           # download engine (segments, resume, retry, limits)
│   ├── store.py            # SQLite queue (jobs, segments, settings)
│   ├── scheduler.py        # active/connection/host caps + FIFO queue
│   ├── settings.py         # typed settings (folder, threads, limit, window)
│   ├── batch.py            # batch URL parsing + clipboard link detection
│   ├── verify.py           # size/checksum verification + orphan cleanup
│   ├── categories.py       # categories, list filter, queue export/import
│   ├── automation.py       # scheduled starts, daily window, shut-down
│   ├── network.py          # proxy, IPv4/IPv6 preference, mirror sources
│   ├── stream.py           # HLS/DASH playlists
│   ├── aes.py              # a small pure-Python AES-128
│   ├── native_host.py      # native messaging host (starts the app)
│   ├── control_server.py   # loopback browser-handoff endpoint (token auth)
│   └── gui.py              # Tkinter GUI
├── extension/              # MV3 browser extension (Chrome/Edge/Firefox)
├── tests/                  # the regression suites
├── scripts/                # release tooling
├── docs/                   # documentation
├── releases/               # ARCHIVED older builds (see releases/README.md)
├── installer/              # the Inno Setup installer script
├── .github/workflows/      # CI: the suite on 3 systems + the Windows build
├── icon.ico                # the application icon (generated)
├── VERSION.json            # the file the update check reads
├── pytest.ini / conftest.py # `python -m pytest` runs everything
├── dist/FreeDM.exe         # the built application
├── LICENSE                 # PolyForm Noncommercial 1.0.0 (full text)
├── NOTICE                  # copyright notice / Required Notice line
├── CHANGELOG.md            # per-build patch notes (source of truth)
├── build.ps1               # rebuild FreeDM.exe AND FreeDM-cli.exe
└── requirements.txt
```

## Security

FreeDM was reviewed for security on 2026-10-19; the findings and the fixes
are in [`docs/SECURITY.md`](docs/SECURITY.md). The short version:

- The control server listens on `127.0.0.1` only, requires a 256-bit token
  for every state-changing request, rejects a `Host` header that is not
  loopback, and gives **no CORS permission to ordinary web pages** — only to
  the browser extension.
- The extension keeps the token in `chrome.storage.local`, so it never leaves
  the device, and asks only for the permissions it uses.
- A hand-written `Cookie:` header is kept in the cookie jar, so it is scoped
  to the host it belongs to and survives a redirect.
- Opening a downloaded executable or script always asks first.
- The queue database, the control token and the proxy password are stored in
  plain text under `%APPDATA%\FreeDM`. On a shared Windows account, other
  users of that account can read them.

## Changelog and release notes

[`CHANGELOG.md`](CHANGELOG.md) is the single source of truth for the patch
notes of every build. Each release has its own section listing the **build**
(file name, size, SHA-256) followed by what was added, changed and fixed.

To get the notes for a release:

```
python scripts\release_notes.py --list
python scripts\release_notes.py v1.1.0
python scripts\release_notes.py v1.1.0 --file notes.md
python scripts\release_notes.py --hash dist\FreeDM.exe
```

The same text is used for the GitHub release page, so the notes there always
match the shipped binary.

## Testing

Regression suites (each starts its own server on an ephemeral port):

```
python tests\test_w1.py
python tests\test_w2.py
python tests\test_w3.py
python tests\test_w4.py
python tests\test_w5.py
python tests\test_n1.py
python tests\test_n2.py
python tests\test_n3.py
python tests\test_n4.py
python tests\test_n5.py
python tests\test_n6.py
python tests\test_n7.py
python tests\test_n8.py
python tests\test_security.py
python tests\test_changelog.py
```

For a manual download, start the Range-capable test server and run:

```
python tests\range_server.py 8765 20
python -m freedm.main "http://127.0.0.1:8765/test.bin" -o %TEMP%\freedm_test -t 8
```

`--selftest` runs a headless download and writes the result to a log file
(useful to verify a frozen build):

```
dist\FreeDM.exe --selftest "http://127.0.0.1:8765/test.bin" "%TEMP%\freedm_frozen"
dist\FreeDM.exe --browser-selftest "%TEMP%\freedm_browser"
```

## License

FreeDM is **source-available** under the
[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0).

- You may use, modify and redistribute FreeDM for **noncommercial** purposes.
- Commercial use is **not** permitted. Permitted purposes include personal,
  research, hobby and noncommercial-organisation use.
- The complete, unmodified license text is in [LICENSE](LICENSE); the copyright
  notice is in [NOTICE](NOTICE).

This is a *source-available* license, not an open-source license: it does not
grant the freedoms the Open Source Definition requires.

### Third-party components

| Component | License | Notes |
|---|---|---|
| [requests](https://github.com/psf/requests) | Apache-2.0 | Bundled in the exe |
| [urllib3](https://github.com/urllib3/urllib3) | MIT | Bundled (via requests) |
| [certifi](https://github.com/certifi/python-certifi) | MPL-2.0 | Bundled (via requests) |
| [idna](https://github.com/kennethreitz/idna) | BSD-3-Clause | Bundled (via requests) |
| [charset-normalizer](https://github.com/jawah/charset_normalizer) | MIT | Bundled (via requests) |
| Python 3 | PSF-2.0 | Runtime |
| [PyInstaller](https://pyinstaller.org/) | GPL-2.0 + bootloader exception | **Build tool only** — not distributed in the exe |

The shipped `FreeDM.exe` therefore contains only permissive-licensed
components, which are compatible with the PolyForm Noncommercial terms.
Review this table before publishing a new build.

## Limitations

- Servers that block Range requests fall back to single-thread (no speedup).
- Streaming video (HLS/DASH) is not a single file and is not supported yet.
- Speed depends on the server; more connections help only on servers that
  allow them.
- The default filename comes from `Content-Disposition` or the URL path.
- Queue metadata is stored in plain text in `%APPDATA%\FreeDM\freedm.db`;
  cookies passed via the API are not persisted across restarts.
- Connection budgets are assigned when a job starts (static thread count), not
  rebalanced while it runs.
- Speed limits are per download; **Global Limit...** caps the combined speed
  of all downloads, but there is no time-of-day bandwidth schedule.
- Browser handoff is Chrome/Edge only; the token is pasted once into the
  extension options, incognito downloads stay in the browser, and the app is not
  auto-launched from the browser.

## Roadmap (not yet implemented)

Firefox extension, native-messaging auto-launch, right-click "Download with
FreeDM", FTP, proxy auth, video grabber.

For the full, maintained backlog see [`docs/MILESTONE_2.md`](docs/MILESTONE_2.md)
and [`docs/ROADMAP.md`](docs/ROADMAP.md).
