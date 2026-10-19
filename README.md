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
<https://github.com/EddyGameDev/FreeDM/releases/tag/v1.0.0>

```
FreeDM-1.0.0.exe
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

## Command line

The same exe also works from a terminal:

```
FreeDM.exe "https://example.com/big.iso" -o C:\Downloads -t 16
FreeDM.exe "https://example.com/big.iso" --limit 2000000   # 2 MB/s cap
```

(Note: the windowed build prints nothing to a console; use the source build
below if you want live CLI progress.)

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
├── LICENSE                 # PolyForm Noncommercial 1.0.0 (full text)
├── NOTICE                  # copyright notice / Required Notice line
├── .gitignore              # build artefacts, caches, partial downloads
├── engine.py              # download engine (segments, resume, retry, limits)
├── store.py               # SQLite queue (jobs, segments, settings)
├── settings.py            # typed settings (folder, threads, limit, window)
├── batch.py               # batch URL parsing + clipboard link detection
├── verify.py              # size/checksum verification + orphan cleanup
├── categories.py          # categories, list filter, queue export/import
├── scheduler.py           # active/connection/host caps + FIFO queue
├── control_server.py      # loopback browser-handoff endpoint (token auth)
├── extension/             # MV3 browser extension (Chrome/Edge)
├── gui.py                 # Tkinter GUI
├── main.py                # entry point (GUI / CLI / --selftest / --browser-selftest)
├── build.ps1              # rebuild dist\FreeDM.exe
├── requirements.txt
├── tests/
│   ├── range_server.py    # local HTTP server with Range + ETag + gated paths
│   ├── crash_session1.py  # simulates a crash mid-download
│   ├── test_w1.py         # W1 control-server/handoff tests
│   ├── test_w2.py         # W2 session/cookie/header/redirect tests
│   ├── test_w3.py         # W3 queue persistence/DB resume tests
│   ├── test_w4.py         # W4 caps/FIFO/Retry-After tests
│   ├── test_w5.py         # W5 integrity/overwrite/disk tests
│   ├── test_n1.py         # N1 settings/migration/live-limit tests
│   ├── test_n2.py         # N2 batch parsing/clipboard tests
│   ├── test_n3.py         # N3 verification/cleanup tests
│   ├── test_n4.py         # N4 dynamic segmentation/global limit tests
│   ├── test_n5.py         # N5 categories/filter/export-import tests
│   └── gui_testcase.py    # shared GUI test base (temp folder, no downloads)
├── dist/FreeDM.exe        # the built application
└── build/                 # PyInstaller intermediate files
```

## Rebuilding the exe

```
powershell -ExecutionPolicy Bypass -File build.ps1
```

Requires Python 3.10+ and PyInstaller. Output lands in `dist\FreeDM.exe`.

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
```

For a manual download, start the Range-capable test server and run:

```
python tests\range_server.py 8765 20
python main.py "http://127.0.0.1:8765/test.bin" -o %TEMP%\freedm_test -t 8
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
  rebalanced while it runs. There is no timed/scheduled start yet.
- Speed limits are per download; there is no shared cap across all active
  downloads and no time-of-day bandwidth schedule.
- Browser handoff is Chrome/Edge only; the token is pasted once into the
  extension options, incognito downloads stay in the browser, and the app is not
  auto-launched from the browser.

## Roadmap (not yet implemented)

Firefox extension, native-messaging auto-launch, right-click "Download with
FreeDM", FTP, proxy auth, video grabber.

For the full, maintained backlog see [`docs/MILESTONE_2.md`](docs/MILESTONE_2.md)
and [`docs/ROADMAP.md`](docs/ROADMAP.md).
