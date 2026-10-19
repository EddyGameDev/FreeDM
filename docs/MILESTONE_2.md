# FreeDM — Milestone 2: Everyday polish → engine strength

**Status:** started 2026-10-19 · **N1–N5 done** · next: **N6** · Companion to
[`NEXT_GOAL.md`](NEXT_GOAL.md) (Milestone 1 — **complete**) and
[`ROADMAP.md`](ROADMAP.md) (full backlog).

> **Published:** the project is published at
> <https://github.com/outlawproductionstwo-hash/FreeDM> under the
> **PolyForm Noncommercial 1.0.0** license (source-available, not open source).
> See `LICENSE` and `NOTICE` at the repository root.

Milestone 1 (W1–W5) made FreeDM browsable, session-aware, persistent and
polite. Milestone 2 turns it from "works" into "nicer to live with", then
strengthens the engine. This file is the authoritative, sequenced next-goal
list; each goal has plain acceptance criteria so an agent can pick one up
without re-analysing the code.

## Progress log

| Date | Goal | Result |
|---|---|---|
| 2026-10-19 | **N1 — Settings persistence & quick controls** | **DONE.** `settings.py`; last folder, threads, default speed limit and window geometry persist in the existing `settings` table; per-job `speed_limit` column (auto-migrated); live per-download **Limit...**; full-text **Details...** dialog; retry-from-UI confirmed. 13/13 tests. Rebuilt exe (17.5 MB) verified with frozen `--selftest` + `--browser-selftest`. |
| 2026-10-19 | **N2 — Batch input & clipboard** | **DONE.** `batch.py` (`parse_urls`, `find_url`); the URL box now adds every pasted http(s) line as its own job, reports invalid lines and skips duplicates; opt-in **Watch clipboard** toggle (off by default, persisted) offers a copied link with a confirmation and never adds on its own. 27/27 tests (incl. 8 real-GUI tests). Rebuilt exe (17.5 MB) verified with frozen `--selftest` + `--browser-selftest`. |
| 2026-10-19 | **N3 — Integrity & verification** | **DONE.** New `verify.py` (checksum parsing/hashing, size check, orphan scan/cleanup). Engine: `checksum=` option, `VerificationError`, size check before finalize, `verify_now()`/`set_checksum()`, `checksum`/`checksum_result` DB columns (auto-migrated). GUI: **Checksum...** dialog, **Clean Up...** for abandoned `.part` files, checksum shown in **Details...**. Also fixed a real control-server race (403 before reading the request body → WinError 10053) found by a flaky W1 test. 34/34 N3 tests, W1 14/14. |
| 2026-10-19 | **N4 — Dynamic segmentation** | **DONE.** Work-queue engine: workers take the largest pending piece and split it, so a slow connection can only hold back a small piece. Adaptive piece sizing follows the *slowest* recent connection (1 MB – 8 MB). New **Global Limit...** caps the combined throughput of all downloads. Resume now validates that the stored pieces tile the file exactly. `engine.DYNAMIC_SPLITTING` is the master switch. 24/24 tests. Rebuilt exe verified (frozen `--selftest` PASS). |
| 2026-10-19 | **N5 — Organization & history** | **DONE.** New `categories.py` (categories, rules parser, filter, queue export/import). GUI: search box + status filter that hides non-matching rows live, **Sort into category folders** toggle with an editable **Categories...** dialog, **Export...**/**Import...** of the queue, **Show in Folder** (reveal in Explorer) and a friendlier **Open File** fallback. Engine: `dest_resolver` hook so the category folder is chosen from the *real* file name after the probe. 32/32 tests. Rebuilt exe verified (frozen `--selftest` PASS). |
| next | N6 — Automation | Not started |
| next | N7 — Network options | Not started |
| next | N8 — Browser extras | Not started |
| next | N9 — Packaging & quality | Not started |
| later | N10 — Streaming media | Deferred (large, separate subsystem) |

---

## Goal overview

| # | Goal | Roadmap refs | Effort | Status |
|---|---|---|---|---|
| **N1** | **Settings persistence & quick controls** | P0.2, P0.3, P0.4, P0.5 | S | **DONE** |
| N2 | Batch input & clipboard | P1.3, P1.5 | S–M | **DONE** |
| N3 | Integrity & verification | P5.3, P5.10, debt #3 | S | **DONE** |
| N4 | Dynamic segmentation | P5.1, P5.2, debt #4 | M | **DONE** |
| N5 | Organization & history | P1.2, P3.2, P3.3, P3.4 | M | **DONE** |
| N6 | Automation | P2.1, P2.2, P2.3 | M | Not started |
| N7 | Network options | P5.5, P5.8, P5.4 | M | Not started |
| N8 | Browser extras | P4.2, P4.5, P4.3 | M | Not started |
| N9 | Packaging & quality | P0.6, P0.7, P0.8, P7.1, P7.4, P7.5, P7.6, P7.8 | M | Not started |
| N10 | Streaming media | P6.1–P6.4 | L | Deferred |

Recommended order: **N1 → N2 → N3 → N4 → N5 → N6 → N7 → N8 → N9 → (N10)**.
N1–N4 are small and high-impact; N5–N9 are larger but independent.

---

## N1 — Settings persistence & quick controls ✅ DONE

**Why:** the app forgot your folder, thread count and window size every launch,
there was no way to throttle a single download, errors were cut to 40 chars, and
retrying a failed job was unclear.

**What shipped:**
- New `settings.py`: typed accessors over the existing SQLite `settings` table
  (`load`/`save`/`get_str|get_int|get_float|get_bool`), safe when there is no
  store, with a single `DEFAULTS` definition shared by GUI, CLI and tests.
- Persisted: `last_dir`, `threads`, `speed_limit`, `window` (geometry), plus the
  already-persisted `auto_resume`, `max_active`, `control_enabled`.
- A per-job `speed_limit` column in `downloads` (auto-migrated on open via
  `JobStore._migrate`), so a cap set on one download survives a restart and is
  restored by `Download.apply_record`.
- **Limit...** button: sets a live per-download speed cap (KB/s, 0 = off) on the
  selected running/queued jobs via `Download.set_speed_limit`, and remembers the
  value as the default for new downloads (and for browser handoffs).
- **Details...** button: a dialog with the full (untruncated) error, URL,
  destination, size, progress, threads and final path.
- Retry-from-UI: **Resume** restarts `error`/`canceled` jobs (re-probe + resume
  from the `.part`), and the dialog makes the failure reason visible.

**Acceptance criteria:** all met.
- Reopen the app → save folder, threads, default limit and window position
  restored. ✅
- Changing the limit on a running download takes effect live. ✅
- The full error text is viewable from the UI. ✅
- A failed job can be retried from the UI. ✅

**Tests:** `tests/test_n1.py` — 13/13 pass (settings typing/round-trip, bool
parsing, bad-value fallback, DB migration adding `speed_limit`, live
`set_speed_limit`, per-job persistence, `apply_record` restore, rate-limiter
throttling, and a single-thread integration test proving the cap bounds bytes
transferred mid-flight then finishes byte-correct when lifted).

---

## N2 — Batch input & clipboard ✅ DONE

**Why:** adding many links was tedious; many people copy a link and expect the
app to offer it.

**What shipped:**
- New `batch.py` (headless): `parse_urls(text) -> (valid, invalid, duplicates)`
  and `find_url(text, exclude=...)`. Splitting accepts newlines *or* spaces
  (so pasted multi-line text works even if a widget flattens it), unwraps
  `(url)`/`[url]`/`<url>` wrappers, trims sentence punctuation, and keeps
  balanced parentheses inside a URL.
- The URL box (relabelled **URL(s)**) now adds **every** pasted http(s) line as
  its own job in one action. Invalid entries are reported in a dialog and
  summarised in the status bar (never silently dropped); duplicates within one
  paste are counted and skipped.
- **Watch clipboard** toolbar toggle (opt-in; `clipboard_monitor` setting,
  default off). When on, the 500 ms poll looks for a newly copied link and asks
  **"Download this link with FreeDM?"**; it records the clipboard text it has
  seen so a link is offered only once, skips links already in the list, and
  **never adds without confirmation**.
- GUI enqueue path factored into `_new_download`/`_enqueue`/`_add_url`, shared
  by the URL box, the clipboard prompt and browser handoff.
- Drag-and-drop (P1.4) was **not** added: it needs the third-party `tkinterdnd2`
  dependency; batch paste and the clipboard watch cover the common cases. It
  stays on the roadmap (N5).

**Acceptance criteria:** all met.
- Pasting 5 URLs adds 5 queued jobs with one action. ✅
- Clipboard monitor is off by default and never adds without confirmation. ✅
- Malformed lines are reported, not silently ignored. ✅

**Tests:** `tests/test_n2.py` — 27/27 pass (batch splitting, invalid reporting,
duplicate skipping, blank/`None` input, scheme case, punctuation/unwrapping,
clipboard extraction with excludes, the persisted off-by-default setting, the
GUI API surface, and 8 real Tk-window integration tests covering the 5-URL
paste, duplicate skipping, invalid reporting, mixed input, and the clipboard
confirm/decline/only-once flow).

---

## N3 — Integrity & verification ✅ DONE

**Why:** the part file is written at fixed offsets; a bad offset or truncation
should be caught, and users with published checksums want verification.

**What shipped:**
- New `verify.py` (headless): `parse_checksum` (`sha256:…`, `md5:…`, `sha1`,
  `sha512`, or a bare 64-hex digest), `file_digest` (streamed, constant
  memory), `verify_size`, `verify_checksum` (a mismatch message shows **both**
  digests), `find_orphans` and `cleanup_orphans`.
- Engine: `Download(checksum=…)`; `VerificationError`; a **size check before
  finalize** so a short download can never be reported as "done"; size +
  checksum verification after the file is written; public `verify_now()`
  (re-verify a finished file) and `set_checksum()` (set/re-check a digest).
  The file is never deleted on a mismatch — the job is simply marked failed.
- New DB columns `checksum` and `checksum_result` (auto-migrated on open), so
  an expected digest and its result survive a restart.
- GUI: **Checksum...** dialog (algorithm + digest; applies to the selection and
  to new downloads), the digest and its result in **Details...**, and
  **Clean Up...** — scans a folder for abandoned `.part` / `.part.state.json`
  files older than a chosen age (never younger ones, so running downloads are
  safe) and deletes them after confirmation.

**Acceptance criteria:** all met.
- A truncated download is detected and reported, never silently "done". ✅
- A wrong checksum marks the job failed with both digests shown. ✅
- Supplying the correct checksum passes and is recorded in the job details. ✅

**Bonus fix (real bug, not a test artefact):** the W1 suite turned out to be
*flaky* (~1 run in 3 failed). Root cause: the control server answered `403`
**without reading the request body**, so it closed the socket while the client
was still uploading → `ConnectionAbortedError [WinError 10053]` on Windows
instead of the 403. The server now drains the body before any error response.
Regression test added (`test_rejected_posts_always_return_a_clean_response`,
25 rejected posts); W1 now passes 8/8 consecutive runs.

**Tests:** `tests/test_n3.py` — 34/34 pass (checksum parsing incl. errors,
digest/size/checksum helpers, orphan scan + cleanup, engine verify/size
mismatch/checksum match+fail, DB persistence, migration, and 4 real-GUI tests).

---

## N4 — Dynamic segmentation ✅ DONE

**Why:** IDM-style splitting keeps all workers busy when some pieces finish
early, and stops one slow connection from holding back a large part of the
file. This was the main remaining speed win.

**What shipped:**
- The fixed "cursor" over a pre-computed piece list is replaced by a **work
  queue**. A worker that finishes asks for the **largest pending piece**; if
  that piece is bigger than the adaptive target it is **split** and the worker
  takes the small half, leaving the rest for whoever is free. The pending work
  therefore stays evenly divided and no single piece can dominate the tail.
- **Adaptive piece sizing (P5.2):** the target follows the **slowest** of the
  last 8 completed pieces, not the average — one bad pipe is what decides
  when the file is really finished. The target is clamped to 1 MB – 8 MB, and
  starts at the conservative 1 MB so even the very first pieces are safe.
  A fast link raises the target, so big files need fewer requests.
- Hard limits: no piece above `MAX_PIECE_SIZE` (8 MB) and never more than
  `MAX_SEGMENTS` (1024) pieces, so the state file and the queue DB stay
  bounded. `engine.DYNAMIC_SPLITTING = False` restores the old fixed
  behaviour (and is used by the tests as a baseline).
- **Global cross-download speed limit (technical debt #4):** one token bucket
  shared by every download (`set_global_speed_limit()`), so the *combined*
  throughput of all jobs can be capped. New **Global Limit...** button and a
  persisted `global_speed_limit` setting.
- **Resume safety:** the stored pieces are now validated before they are
  trusted — they must tile the file exactly (no gaps, no overlaps, correct
  total). A corrupt or hand-edited state file is refused and the download
  restarts cleanly instead of producing a broken file. Pieces are also sorted
  by offset when they come back from the DB.
- `snapshot()` reports `pieces` and `splits`; **Details...** shows them.

**Acceptance criteria:** all met.
- A slow connection holds back less data, and the download is not slower. ✅
  (measured on a throttled test server: the slow pipe's first piece drops from
  2 MB to 1 MB, and the run time is within noise of the fixed-segment run)
- Byte-for-byte hash is unchanged on segmented downloads. ✅ (SHA-256 verified
  in the suite and in the frozen `--selftest`)
- A global limit caps the sum of all downloads' throughput. ✅ (two parallel
  downloads stay under the shared cap)

**Tests:** `tests/test_n4.py` — 24/24 pass (piece-layout validation, split
accounting, adaptive target, piece cap, work-queue splitting, split switch,
byte-identical download, resume after pause, corrupt-state refusal, global
limit, throttled-server comparison, and 4 real-GUI tests).

---

## N5 — Organization & history ✅ DONE

**Why:** a long queue becomes unusable without categories, a search box and a
way to move a list of links in and out of the app.

**What shipped:**
- New `categories.py` (headless): the shipped categories (Video, Music,
  Documents, Archives, Programs, Other), an editable rule format
  (`Name: .ext, .ext`) with a parser that reports bad lines, `classify()`,
  `destination_for()`, the list filter and the queue export/import helpers.
- **Sort into category folders** toggle: new downloads are saved into
  `<save folder>/<category>/`. The folder is chosen from the **real** file
  name — the engine gained a `dest_resolver` hook that is called after the
  probe, so a `Content-Disposition` name is categorised correctly (not a
  guess made before the request). Files that match no rule go to `Other`.
- **Categories...** dialog: edit the rules in a text box; invalid lines are
  reported and the save is refused, so a typo cannot silently break the
  sorting. The rules are persisted and restored.
- **Search box + Status filter** in a new filter bar: the list is filtered
  live by name, URL or host, and by status (downloading / queued / paused /
  done / error). Non-matching rows are hidden without reloading, and a status
  change can make a row appear or disappear while it runs. The filter is
  remembered between sessions.
- **Export... / Import...**: the queue is written as JSON (URL, file name,
  destination, thread count, expected checksum) and can be imported again
  without loss. A plain list of URLs is accepted on import as well.
- **Show in Folder** opens the containing folder and selects the file
  (Windows), and **Open File** now falls back to the containing folder when
  the file is gone.

**Acceptance criteria:** all met.
- A file lands in its category folder when auto-sort is on. ✅
- Filtering the list by name/status/host works without reloading. ✅
- Export → import round-trips a queue without loss. ✅

**Tests:** `tests/test_n5.py` — 32/32 pass (rules parsing/formatting,
classification, destination, filter matching by name/host/status, export and
import incl. plain-text and broken input, the engine's `dest_resolver`, the
new settings, and 8 real-GUI tests covering filtering, auto-sort, the
export/import round-trip and the new actions).

---

## N6 — Automation

**Build:** scheduled start per item (`P2.1`), allowed download windows
(e.g. 01:00–06:00, `P2.2`), and shut down / sleep when the queue drains
(`P2.3`, confirmation-guarded). Scheduled jobs persist through restarts.

**Acceptance criteria:**
- A job scheduled for the future stays queued until its time, then runs.
- Outside the allowed window jobs wait; inside they resume.
- "Shut down when done" runs only after a confirmation and only when idle.

---

## N7 — Network options

**Build:** proxy configuration with auth (HTTP/SOCKS, `P5.5`), IPv6/Happy
Eyeballs robustness (`P5.8`), and mirror/multi-source downloads (`P5.4`).

**Acceptance criteria:**
- All requests honour the configured proxy.
- A mirror that returns the same bytes can supply pieces for one job.
- Settings persist and are testable with a connection check.

---

## N8 — Browser extras

**Build:** Firefox extension (`P4.2`), right-click "Download with FreeDM"
context menu (`P4.5`), and native-messaging auto-launch of the app (`P4.3`).
Reuse the W1 loopback protocol; only the packaging changes.

**Acceptance criteria:**
- Firefox hands downloads over exactly like Chrome/Edge.
- The context menu enqueues the link/video URL.
- If FreeDM is closed, the native host can start it (or the download is left to
  the browser).

---

## N9 — Packaging & quality

**Build:** console-side build `FreeDM-cli.exe` (`P0.6`), `.gitignore` (`P0.7`),
app icon (`P0.8`), installer (`P7.1`), opt-in update check (`P7.4`), pytest +
CI (`P7.5`, `P7.6`), rotating opt-in log file (`P7.8`).

**Acceptance criteria:**
- `pytest` runs the whole suite in CI.
- The installed and portable builds both run.
- `FreeDM-cli.exe` streams live progress in a console.

---

## N10 — Streaming media (deferred)

HLS (`P6.1`), DASH (`P6.2`), page media sniffing (`P6.3`) and optional FFmpeg
remux (`P6.4`). Large, separate subsystem — explicitly out of scope until the
goals above are done.

---

## Definition of done (Milestone 2)

- Every goal's acceptance criteria pass on a clean Windows machine.
- `--selftest` and `--browser-selftest` still pass; the W1–W5 suites stay green.
- Documentation (`FEATURES.md`, `FILE_MAP.md`, this file, READMEs) is updated as
  each goal lands.
