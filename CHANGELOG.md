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
