# Changelog

All notable changes to FreeDM are recorded here. This file is the **single
source of truth for the release notes**: every release gets its own section
with the build details, so the notes on the GitHub release page always match
the code.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) — each
release lists the **build** that was shipped, then **Added**, **Changed**,
**Fixed** and **Known limitations**.

Generate the notes for a release with:

```
python scripts/release_notes.py v1.1.0
```

That prints the section for that version, ready to paste into the GitHub
release (or to feed to the API - see `docs/PUBLISHING.md`).

---

## [Unreleased]

Nothing yet - the next release notes are written here as the work lands.

## [v1.0.0] - 2026-10-19

First public build.

### Build

- `FreeDM-1.0.0.exe` - Windows x64, single file, no installer (17.5 MB).
- SHA-256: `b39709840de48ea16dd307d60ea195e56e5da6541352280cc2ecdcf8a1439fef`
- Verify with: `certutil -hashfile FreeDM-1.0.0.exe SHA256`
- Source: <https://github.com/EddyGameDev/FreeDM>

### Added

- **Download engine** - multi-threaded segmented downloads over `Range`
  requests, with a dynamic work queue: the piece size (1-8 MB) adapts to the
  slowest active connection, so one slow pipe cannot hold back a large part of
  the file. Single-stream fallback when a server ignores `Range`.
- **Pause / resume / cancel** - crash-safe resume from a `.part.state.json`
  sidecar, validated against the server's `ETag`/`Last-Modified`; a changed
  remote file restarts cleanly instead of corrupting the output.
- **Persistent queue** - a SQLite database keeps jobs, status, headers and
  segment offsets; the queue is restored on launch and unfinished jobs
  auto-resume.
- **Browser handoff** - a Chrome/Edge extension (MV3) hands downloads to the
  app through a loopback-only, token-protected control server; the browser's
  copy is cancelled, or resumed when the app is closed.
- **Integrity checks** - a short download is never reported as done, and an
  expected `sha256`/`sha512`/`sha1`/`md5` digest is verified on completion; a
  mismatch fails the job and shows both digests.
- **Speed limits** - a per-download cap (settable live) and a global cap on
  the combined throughput of all downloads.
- **Organisation** - categories with editable extension rules and an
  auto-sort toggle, a search box and status filter for the list, and queue
  export/import (JSON, or a plain list of URLs).
- **Clean-up** - a dialog that finds and deletes abandoned `.part` /
  `.part.state.json` files older than a chosen age.
- **Session fidelity** - cookies and custom headers (`Referer`,
  `User-Agent`, `Authorization`) are replayed on the probe and every segment;
  redirects are followed and the final URL is reused.
- **Polite concurrency** - caps on active downloads, total connections and
  per-host connections, a FIFO queue with Start Now / reorder, and
  `Retry-After` backoff for `429`/`503`.
- **GUI** - a Tkinter front end with details dialogs, live progress, a
  categories editor and remembered preferences; plus a CLI and headless
  `--selftest` / `--browser-selftest` modes.

### Fixed

- The control server now reads the request body before answering `403`, so a
  rejected download is no longer reported as a connection reset
  (`WinError 10053`).
- The finished file is checked against the advertised size and (optionally)
  against a checksum, so a truncated download is never reported as complete.
- A stored piece layout that does not tile the file exactly is refused
  instead of being resumed.

### Known limitations

- Chrome/Edge only for the browser handoff; no Firefox extension and no
  right-click "Download with FreeDM" menu yet.
- No proxy configuration, no FTP, and no HLS/DASH streaming support.
- Speed limits are constant: there is no time-of-day bandwidth schedule.
- The windowed build has no console, so CLI progress is silent in the
  packaged app.

## [v1.3.1] - 2026-10-19

Repository reorganisation and an archive of the older builds. No behaviour
change.

### Build

- `FreeDM-1.3.1.exe` - Windows x64, single file, no installer (17.6 MB).
- SHA-256: `9e001ada042afc74ddb54f5628ecf4d7ccf3610692484cd2ce9d75db4dc129a6`
- Verify with: `certutil -hashfile FreeDM-1.3.1.exe SHA256`
- Source: <https://github.com/EddyGameDev/FreeDM>

### Changed

- **The application moved into the `freedm/` package.** The thirteen modules
  that used to sit loose in the project root are now `freedm/engine.py`,
  `freedm/store.py`, `freedm/gui.py` and so on, and are imported as
  `freedm.<module>`. The root now holds only the project files: the extension,
  the tests, the documentation, the release tooling and the archived builds.
- The entry point moved with it: `python main.py ...` is now
  `python -m freedm.main ...` (or `python freedm/main.py`, which still works).
  The packaged app is unchanged: `FreeDM.exe URL -o DIR` behaves as before.
- The build script now packages `freedm/main.py`.

### Added

- **`releases/`** keeps the builds that were published before the security
  fixes of v1.2.1 (`v1.0.0`, `v1.1.0`, `v1.2.0`), each with its notes, its
  SHA-256 and a notice explaining why it is superseded. They are archived for
  the record; **use the latest release instead**.

## [v1.3.0] - 2026-10-19

Browser extras: Firefox support, a right-click menu, and native messaging.

### Build

- `FreeDM-1.3.0.exe` - Windows x64, single file, no installer (17.5 MB).
- SHA-256: `584bd0d49f70c16d18a79fb65b3cd9c650aad016a7ca6945a3d3d45a615b3726`
- Verify with: `certutil -hashfile FreeDM-1.3.0.exe SHA256`
- Source: <https://github.com/EddyGameDev/FreeDM>

### Added

- **Firefox extension** - the same handoff code with a Firefox manifest (a
  background page instead of a service worker, an options tab and a gecko
  add-on id). FreeDM's **Browser...** dialog can export the Firefox build;
  load it with `about:debugging` → **Load Temporary Add-on...**.
- **"Download with FreeDM" context menu** - right-click a link, a video, an
  image or a page to hand it to FreeDM. The page's cookies travel with it, so
  a protected link still works.
- **Native messaging host** - `FreeDM.exe --native-host` plus an
  **Install native host** button in the **Browser...** dialog. With it
  registered, the extension can start FreeDM by itself when a download is
  handed over while the app is closed. Without it the download stays in the
  browser, exactly as before.

### Changed

- The extension now asks for the `contextMenus` permission, which the new
  right-click menu uses. It still asks for nothing it does not use.

### Notes

- After installing the native host, restart the browser so it picks up the
  registration.

## [v1.2.1] - 2026-10-19

Security review and fixes. No behaviour changes for normal use.

### Build

- `FreeDM-1.2.1.exe` - Windows x64, single file, no installer (17.5 MB).
- SHA-256: `1b3f89d88885781abe054ba95be7e3eb7c53be02b384b345cc7728be17b002ca`
- Verify with: `certutil -hashfile FreeDM-1.2.1.exe SHA256`
- Source: <https://github.com/EddyGameDev/FreeDM>

### Fixed

- **The control token stays on the device.** The browser extension stored it
  in `chrome.storage.sync`, which uploads it to the Google account and to
  every other browser signed in to it. It now uses `chrome.storage.local`.
  *After updating the extension, paste the token again.*
- **A web page can no longer talk to the control server.** The server sent
  `Access-Control-Allow-Origin: *`, so any site could read its answers and
  tell whether FreeDM was running. The CORS headers are now only sent for a
  browser-extension origin.
- **The control server only answers for loopback.** A request with a `Host`
  header naming another host (a DNS-rebinding attempt) is refused.
- **The extension no longer asks for the `webRequest` permission**, which it
  never used.
- **A `Cookie:` header set by hand is no longer lost on a redirect.** It is
  put into the cookie jar instead, so it survives a redirect *and* is only sent
  to the host it belongs to.
- **Opening a downloaded executable or script asks first**, instead of
  launching it with one click.
- The control server no longer returns internal error messages to the client,
  and a `dest_dir` from the extension is ignored unless it is a real folder.

### Known limitations

- The queue database, the control token and the proxy password are stored in
  plain text under `%APPDATA%\FreeDM`. On a shared Windows account, other
  users of that account can read them.

### Notes

- The full review, including what was checked and found safe, is in
  `docs/SECURITY.md`. The findings are pinned by `tests/test_security.py`.

## [v1.2.0] - 2026-10-19

Network options: proxy support, an IPv4/IPv6 preference and mirror sources.

### Build

- `FreeDM-1.2.0.exe` - Windows x64, single file, no installer (17.5 MB).
- SHA-256: `b03f15c8d9c0f2b2092ce56b69506540b9dc7f659a3565e5d9446a2573cb99b5`
- Verify with: `certutil -hashfile FreeDM-1.2.0.exe SHA256`
- Source: <https://github.com/EddyGameDev/FreeDM>

### Added

- **Proxy support** - an HTTP or SOCKS proxy with an optional user name and
  password, applied to every request (probe, range requests, single-stream
  fallback and the validator check). A **bypass list** sends chosen hosts
  straight to the server while the rest of the queue still uses the proxy.
- **Network... dialog** - configure the proxy, the bypass list and the
  address-family preference, with a **Test connection** button that makes a
  real request through the current settings and reports the result.
- **IPv4/IPv6 preference** - when a host resolves to both, the preferred
  family is used first. A half-working IPv6 route is a common cause of
  downloads that hang before falling back.
- **Mirror sources** - a job can have alternative sources. The probe tries
  them in turn and a segment whose source refuses the connection moves to the
  next mirror, so a slow or dead server no longer fails the download. The
  mirrors are stored with the job and restored on the next launch.

### Changed

- The queue database gained a `mirrors` column (existing databases are
  migrated automatically).

### Known limitations

- The proxy password is stored in plain text in the queue database, like the
  rest of the settings. Do not use it on a shared Windows account.
- A mirror must serve the **identical** file; FreeDM does not compare the
  bytes of two sources.

## [v1.1.0] - 2026-10-19

Automation: scheduled starts, a daily download window and shut-down when the
queue drains.

### Build

- `FreeDM-1.1.0.exe` - Windows x64, single file, no installer (17.5 MB).
- SHA-256: `f0794d81cdd00928f988cbc6d610e13f48accc17ee3f8d2262d7a0c3e2af0d4c`
- Verify with: `certutil -hashfile FreeDM-1.1.0.exe SHA256`
- Source: <https://github.com/EddyGameDev/FreeDM>

### Added

- **Scheduled start** per job (`Schedule...`): a job waits in the `scheduled`
  state until its moment and then joins the queue. The schedule is stored in
  the database, so it survives a restart.
- **Daily download window** - downloads only start inside the configured
  hours (e.g. `01:00` to `06:00`); the window may wrap past midnight. A
  closed window holds the queue without starting anything.
- **Shut down when done** - when the queue really is empty, FreeDM asks for
  confirmation and then powers the machine down (or puts it to sleep).
- `Start Now` overrides both the schedule and the window, because the user
  asked for it explicitly.

### Changed

- The list shows a `scheduled` status with the time the job will start.

### Known limitations

- The shut-down action uses the operating system's power command; it cannot
  be undone once it has started.
