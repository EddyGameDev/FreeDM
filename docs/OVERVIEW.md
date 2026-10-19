# FreeDM — Overview

**FreeDM** is a free, source-available download manager in the style of Internet
Download Manager (IDM). It speeds up downloads by splitting files into many
segments and fetching them in parallel, and it can pause, resume, and survive
crashes without losing progress.

- **Cost:** $0. No licence fees, no paid APIs, no ads, no telemetry.
- **License:** source-available under the
  [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)
  — noncommercial use, modification and redistribution are permitted. It is
  **not** an open-source license.
- **Dependencies:** `requests` only (plus the Python standard library).
- **Platform:** Windows (built exe). The engine is pure Python and is
  cross-platform; only the packaging targets Windows.
- **Language / runtime:** Python 3.10+ (developed and tested on 3.14).

---

## 1. What this project is (scope — IN)

- A standalone desktop download manager with a Tkinter GUI.
- Multi-threaded, segmented HTTP/HTTPS downloads using `Range` requests.
- Pause / resume / cancel, including resume after a crash or reboot.
- Session fidelity: cookies and custom headers (`Referer`, `Cookie`,
  `Authorization`) are replayed on the probe and every segment; redirects are
  followed and the final URL is reused.
- Persistent queue: jobs, status, headers and segment offsets are stored in a
  local SQLite DB and reloaded on launch; unfinished jobs auto-resume.
- Polite concurrency: active-download cap, total and per-host connection caps,
  FIFO queue with Start Now / reorder, and `Retry-After` backoff.
- Browser handoff: a Chrome/Edge extension sends clicks to a loopback-only,
  token-protected control server; the browser's copy is cancelled, or resumed
  if FreeDM is not running.
- Single-stream fallback when a server does not support `Range`.
- Retries with exponential backoff.
- Integrity checks: a short download is never reported as done, and an
  expected SHA-256/SHA-512/SHA-1/MD5 digest is verified on completion.
- Optional cleanup of abandoned `.part`/resume files older than a set age.
- Dynamic segmentation: a work queue re-divides the remaining work, and the
  piece size adapts to the slowest connection (1–8 MB), so one slow pipe
  cannot hold back a large part of the file.
- Optional per-download speed limit (settable live from the GUI, persisted)
  and an optional cap on the combined speed of all downloads.
- Remembered preferences: last folder, thread count, default limit and window
  size/position (stored in the same SQLite DB).
- Batch add: paste many http(s) URLs at once (newline- or space-separated);
  invalid lines are reported and duplicates skipped.
- Optional clipboard watch that offers a copied link with a confirmation
  (off by default).
- Organisation: categories with editable rules and an auto-sort toggle, a
  search box + status filter for the list, and queue export/import.
- A simple CLI and a headless `--selftest` mode.
- A single-file distributable: `dist\FreeDM.exe`.

## 2. What this project is NOT (scope — OUT)

These are deliberately **not** implemented. Do not assume they exist:

- No Firefox extension or right-click "Download with FreeDM" menu (the
  Chrome/Edge handoff and the loopback control server exist).
- No auto-launch of the app from the browser (native messaging).
- No timed/scheduled start or shutdown-when-done. A concurrency queue exists
  (active/connection/host caps, W4), but it does not run on a timer.
- No FTP or SFTP support (HTTP/HTTPS only).
- No streaming-video (HLS/DASH) grabber.
- No proxy authentication UI, and no automatic cookie import from browsers
  (cookies/headers can be supplied manually or via the API).
- No automatic checksum lookup — you paste the published digest yourself
  (N3 added the GUI **Checksum...** dialog and the verification itself).
- No installer; it is a portable single `.exe`.
- No time-of-day bandwidth schedule; the caps are constant.
- No drag-and-drop of links into the window (needs the third-party
  `tkinterdnd2`; use paste/clipboard watch instead).

These out-of-scope items are tracked in `ROADMAP.md`.

## 3. Core design (how it works)

1. **Probe** — `HEAD` the URL (falling back to a tiny `Range: bytes=0-0` GET)
   to learn the file size, the filename, and whether the server advertises
   `Accept-Ranges: bytes`.
2. **Plan segments** — if ranges are supported and the file is big enough, the
   file is divided into many fixed byte ranges (more pieces than threads, so
   fast workers pick up more work — natural load balancing).
3. **Download** — a pool of worker threads fetches each piece with
   `Range: bytes=X-Y` and writes it directly at its offset in one shared
   `.part` file. No separate per-piece files and no merge step.
4. **Track progress** — every piece's downloaded offset is written to a
   `<file>.part.state.json` sidecar and mirrored to the queue DB roughly twice
   a second.
5. **Resume** — on start, an existing matching state file is loaded and only
   the missing bytes are requested. If the sidecar is missing, segment offsets
   are recovered from the queue DB (after size/validator checks).
6. **Finalize** — the `.part` file is atomically renamed to the final name, the
   state file is deleted, and the DB row is marked done.
7. **Restore** — on launch the queue DB reloads every job; unfinished jobs
   resume automatically (configurable) and finished history is still listed.
8. **Schedule** — a FIFO scheduler starts only as many jobs as the active and
   connection budgets allow, capping threads per host; `429`/`503` responses
   are retried after `Retry-After`.
9. **Hand off** — a browser click is posted to a loopback-only, token-protected
   endpoint and becomes a normal job; the browser copy is cancelled (or resumed
   when FreeDM is closed).

See `FILE_MAP.md` for exactly which file implements each step.

## 4. Entry points

| Invocation | Behaviour |
|---|---|
| `FreeDM.exe` (no args) | Launches the Tkinter GUI |
| `FreeDM.exe URL -o DIR -t N` | Command-line download (no visible output in the windowed exe) |
| `FreeDM.exe --selftest URL DIR` | Headless download; writes `DIR\selftest_result.txt` |
| `python main.py ...` (from source) | Same as above, with live CLI progress |

## 5. Design principles

- **Safety first on resume.** The state file records *bytes confirmed written
  to disk*, never more. A stale state file causes a tiny re-download, never
  corruption.
- **One writer per byte range.** Pieces never overlap, so multiple threads can
  write to the same file without locking.
- **Graceful degradation.** Anything the server does not support falls back to
  the simple path rather than failing.
- **No hidden network calls.** The app only contacts the URL you give it.
