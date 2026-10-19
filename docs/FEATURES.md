# FreeDM — Feature Reference

Status legend: **Implemented** = working and tested. **Partial** = works but
limited. **Planned** = not yet built (see `ROADMAP.md`).

---

## A. Download engine features

| # | Feature | Status | Where |
|---|---|---|---|
| A1 | HTTP and HTTPS downloads | Implemented | `engine.py` → `Download` |
| A2 | Multi-threaded segmented download using `Range` | Implemented | `engine.py` → `_download_segmented`, `_worker`, `_download_segment` |
| A3 | Configurable thread count, 1–32 | Implemented | `Download(num_threads=...)`, `_make_segments` |
| A4 | More pieces than threads (load balancing) | Implemented | `engine.py` → `_make_segments` |
| A5 | Single-stream fallback when no Range support | Implemented | `engine.py` → `_download_single` |
| A6 | Server capability probe (HEAD + ranged GET) | Implemented | `engine.py` → `_probe` |
| A7 | Filename from `Content-Disposition` or URL path | Implemented | `engine.py` → `_filename_from_headers`, `_guess_filename` |
| A8 | Filename sanitising for Windows | Implemented | `engine.py` → `sanitize_filename` |
| A9 | Pause | Implemented | `engine.py` → `pause` |
| A10 | Resume after pause | Implemented | `engine.py` → `resume` |
| A11 | Cancel (deletes partial + state) | Implemented | `engine.py` → `cancel`, `_cleanup_partial` |
| A12 | Resume after crash / reboot | Implemented | `engine.py` → `_save_state`, `_load_state` |
| A13 | Retry per piece with exponential backoff (6 tries) | Implemented | `engine.py` → `_download_segment` |
| A14 | Handle HTTP 416 (piece already complete) | Implemented | `engine.py` → `_download_segment` |
| A15 | Detect a server ignoring `Range` on resume and abort safely | Implemented | `engine.py` → `_download_segment` |
| A16 | Atomic finalize (`.part` → final file) | Implemented | `engine.py` → `_finalize` |
| A17 | Speed limit (token bucket), settable live per download | Implemented (N1 adds live set) | `engine.py` → `RateLimiter`, `Download.set_speed_limit` |
| A18 | Live speed / ETA / progress calculation | Implemented | `engine.py` → `_start_monitor`, `progress`, `eta` |
| A19 | Thread-safe snapshot for UI | Implemented | `engine.py` → `snapshot` |
| A20 | Unknown file size handled (streaming) | Implemented | `engine.py` → `_download_single` |
| A21 | Custom request headers | Implemented (W2; GUI dialog + API) | `Download(headers=...)`, `gui.py` → `_edit_headers` |
| A22 | Per-connection connect/read timeouts | Implemented | constants in `engine.py` |
| A23 | Dynamic mid-download re-segmentation | Implemented (N4) | `engine.py` → `_claim_piece`, `_split_piece` |
| A24 | Checksum verification | Planned | `ROADMAP.md` |
| A25 | Resume integrity via `ETag`/`Last-Modified` + `If-Range` | Implemented (W5) | `engine.py` → `_probe`, `_validator_changed`, `_load_state` |
| A26 | Auto-restart when the remote file changed | Implemented (W5) | `engine.py` → `FileChangedError`, `_reset_for_restart` |
| A27 | Overwrite policy: rename / overwrite / cancel / callback | Implemented (W5) | `engine.py` → `_apply_existing_policy`, `_unique_path` |
| A28 | Disk-space precheck before preallocation | Implemented (W5) | `engine.py` → `_check_disk_space` |
| A29 | Auto-fallback when a server stops honouring `Range` | Implemented (W5) | `engine.py` → `RangeNotSupportedError`, `_run_once` |
| A30 | Worker exceptions propagate to the download status | Implemented (W5) | `engine.py` → `_worker`, `_download_segmented` |
| A31 | Per-download `requests.Session` + connection pooling | Implemented (W2) | `Download.__init__` (HTTPAdapter) |
| A32 | Cookie jar: dict / `"a=1; b=2"` / extension list | Implemented (W2) | `engine.py` → `_apply_cookies` |
| A33 | Custom headers (Referer, Cookie, Authorization...) | Implemented (W2) | `headers=`, `_session_headers` |
| A34 | Redirect-aware `final_url` reused for every request | Implemented (W2) | `_probe`, `_request_url` |
| A35 | `Accept-Encoding: identity` so ranges address raw bytes | Implemented (W2) | `Download.__init__` |
| A36 | Clear 401/403 error, never retried | Implemented (W2) | `AuthRequiredError` |
| A37 | SQLite job queue (`%APPDATA%\FreeDM\freedm.db`) | Implemented (W3) | `store.py` → `JobStore` |
| A38 | Status/size/filename/headers persisted on transitions | Implemented (W3) | `_store_save` |
| A39 | Segment offsets mirrored to the DB during download | Implemented (W3) | `_save_state` → `_store_save` |
| A40 | Resume from DB ranges if the JSON sidecar is missing | Implemented (W3) | `_load_db_segments` |
| A41 | DB failures never abort or corrupt the payload | Implemented (W3) | `JobStore._write`, `_store_save` |
| A42 | `abandon()` keeps partial data on app close | Implemented (W3) | `Download.abandon` |
| A43 | Rate limiter handles caps below one chunk size | Implemented (W3 fix) | `RateLimiter.consume` |
| A44 | Global active-download cap (default 3) | Implemented (W4) | `scheduler.py` → `Scheduler` |
| A45 | Total connection cap (default 64) | Implemented (W4) | `Scheduler.pump` |
| A46 | Per-host connection cap (default 12) | Implemented (W4) | `Scheduler.pump` (netloc budget) |
| A47 | FIFO queue with Start Now / Move Up / Move Down | Implemented (W4) | `Scheduler` queue methods |
| A48 | `429`/`503` honours `Retry-After` or backoff | Implemented (W4) | `Download._parse_retry_after` |
| A49 | Queued status persists across restarts | Implemented (W4) | `QUEUED`, `mark_queued` |
| A50 | Loopback control server (`127.0.0.1:6801`) | Implemented (W1) | `control_server.py` → `ControlServer` |
| A51 | Token authentication for `/add` (403 otherwise) | Implemented (W1) | `ControlServer` handler |
| A52 | `GET /ping` for app detection | Implemented (W1) | `ControlServer` handler |
| A53 | Accepts cookies/referer/UA/filename from the browser | Implemented (W1) | `_normalise`, `_add_from_browser` |
| A54 | Token file auto-created under `%APPDATA%\FreeDM` | Implemented (W1) | `load_or_create_token` |
| A55 | Extension bundled in the exe and exportable | Implemented (W1) | `export_extension` |
| A56 | Live per-download speed limit (`set_speed_limit`, 0 = off) | Implemented (N1) | `engine.py` → `Download.set_speed_limit`, `snapshot()["speed_limit"]` |
| A57 | Per-job `speed_limit` persisted in the DB (auto-migrated) | Implemented (N1) | `store.py` → `_migrate`, `speed_limit` column; `Download.apply_record` |
| A58 | Typed settings module shared by GUI/CLI/tests | Implemented (N1) | `settings.py` → `load`, `save`, `DEFAULTS` |
| A59 | Batch URL parsing (multi-line/space, invalid + duplicates reported) | Implemented (N2) | `batch.py` → `parse_urls` |
| A60 | Clipboard link extraction (bracket/punctuation aware, excludable) | Implemented (N2) | `batch.py` → `find_url` |
| A61 | Size verification before finalize (short download ≠ done) | Implemented (N3) | `engine.py` → `_check_complete`, `VerificationError` |
| A62 | Size + checksum verification of the finished file | Implemented (N3) | `engine.py` → `_verify_result`; `verify.py` → `verify_size`, `verify_checksum` |
| A63 | Checksum parsing (sha256/sha512/sha1/md5, bare or `algo:hex`) | Implemented (N3) | `verify.py` → `parse_checksum` |
| A64 | `Download(checksum=…)`, `set_checksum()`, `verify_now()` | Implemented (N3) | `engine.py` → `set_checksum`, `verify_now` |
| A65 | Expected checksum + result persisted in the DB | Implemented (N3) | `store.py` → `checksum`, `checksum_result` columns |
| A66 | Abandoned `.part`/`.part.state.json` cleanup (age-based, opt-in) | Implemented (N3) | `verify.py` → `find_orphans`, `cleanup_orphans` |
| A67 | Control server drains the body before an error response | Implemented (N3 fix) | `control_server.py` → `_drain` |
| A68 | Work-queue segmentation: workers take the largest pending piece | Implemented (N4) | `engine.py` → `_claim_piece`, `_prepare_pending` |
| A69 | Dynamic splitting: a big pending piece is split and shared | Implemented (N4) | `engine.py` → `_split_piece`, `split_count` |
| A70 | Adaptive piece size (1–8 MB) following the slowest connection | Implemented (N4) | `engine.py` → `_piece_target`, `_note_piece_speed` |
| A71 | Global speed cap shared by all downloads | Implemented (N4) | `engine.py` → `GlobalRateLimiter`, `set_global_speed_limit` |
| A72 | Resume refuses a piece layout that does not tile the file | Implemented (N4) | `engine.py` → `_pieces_are_valid` |
| A73 | Master switch for the old fixed-segment behaviour | Implemented (N4) | `engine.py` → `DYNAMIC_SPLITTING` |
| A74 | Categories with editable extension rules | Implemented (N5) | `categories.py` → `default_rules`, `parse_rules`, `classify` |
| A75 | Auto-sort into category folders (uses the real file name) | Implemented (N5) | `engine.py` → `dest_resolver`; `gui.py` → `_dest_resolver` |
| A76 | Live list filter by name / URL / host / status | Implemented (N5) | `categories.py` → `matches_filter`; `gui.py` → `_apply_filter` |
| A77 | Queue export / import (JSON, or a plain list of URLs) | Implemented (N5) | `categories.py` → `export_queue`, `import_queue` |
| A78 | Reveal the file in Explorer ("Show in Folder") | Implemented (N5) | `gui.py` → `show_in_folder` |
| A79 | Scheduled start per job (persisted, survives a restart) | Implemented (N6) | `engine.py` → `set_start_at`, `SCHEDULED`; `scheduler.py` → `_promote_scheduled` |
| A80 | Daily download window (may wrap past midnight) | Implemented (N6) | `automation.py` → `in_window`; `scheduler.py` → `set_window` |
| A81 | Shut down / sleep when the queue drains (confirmation-guarded) | Implemented (N6) | `gui.py` → `_check_shutdown_when_done`; `automation.py` → `shutdown_command` |
| A82 | Start Now overrides the schedule and the window | Implemented (N6) | `scheduler.py` → `start_now` |
| A83 | Changelog-driven release notes per build | Implemented (N6) | `CHANGELOG.md`; `scripts/release_notes.py` |
| A84 | HTTP/SOCKS proxy with credentials and a bypass list | Implemented (N7) | `network.py` → `ProxyConfig`; engine → `session.proxies` + `_proxies_for` |
| A85 | IPv4/IPv6 address-family preference | Implemented (N7) | `network.py` → `install_address_preference` |
| A86 | Mirror sources: the probe and the download fall back to them | Implemented (N7) | `network.py` → `mirror_path`; engine → `_source_url`, `_advance_source` |
| A87 | Mirrors persisted per job | Implemented (N7) | `store.py` → `mirrors` column; `Download.set_mirrors` |
| A88 | Network dialog with a connection check | Implemented (N7) | `gui.py` → `network_dialog`, `_check_connection` |
| A89 | Control server refuses a non-loopback `Host` header | Implemented (security) | `control_server.py` → `_host_allowed` |
| A90 | CORS is only granted to extension origins | Implemented (security) | `control_server.py` → `_origin_allowed` |
| A91 | The control token stays on the device (`storage.local`) | Implemented (security) | `extension\background.js`, `options.js` |
| A92 | Only the permissions the extension uses are requested | Implemented (security) | `extension\manifest.json` |
| A93 | A hand-written `Cookie:` header is scoped to its host | Implemented (security) | `engine.py` → `_apply_cookie_header` |
| A94 | Executables and scripts ask before they are opened | Implemented (security) | `gui.py` → `EXECUTABLE_EXTENSIONS` |
| A95 | Firefox build of the extension (same source, own manifest) | Implemented (N8) | `extension\manifest.firefox.json`; `export_extension(browser="firefox")` |
| A96 | "Download with FreeDM" context menu (link/media/page) | Implemented (N8) | `extension\background.js` → `handleMenuClick` |
| A97 | Native messaging host that can start the app | Implemented (N8) | `native_host.py`; `main.py --native-host` |
| A98 | Register / remove the native host | Implemented (N8) | `native_host.py` → `install_host`, `uninstall_host` |

### Segment sizing rules (`engine.py`)
- Files ≤ `MIN_SEGMENT_SIZE` (1 MB) are downloaded as a single stream.
- Otherwise piece count = `min(threads*4, max(threads, size // 1MB))`.
- Pieces are contiguous and non-overlapping; the last piece takes the remainder.

### Resume safety (added in W5)
- The probe captures `ETag` (preferred) or `Last-Modified` as the validator.
- The validator is stored in `<file>.part.state.json`.
- On resume, a changed size **or** a changed validator discards the stale state
  and starts from zero instead of corrupting the file.
- While any bytes are already present, requests send `If-Range`. A `200`
  response then triggers a validator re-check: if the file changed, the
  download restarts automatically (once); if only `Range` is unsupported, it
  degrades to a single stream.

### Overwrite policy (added in W5)
- Constructor option `on_existing`:
  - `"rename"` (default) — saves as `name (1).ext`, never destroys data.
  - `"overwrite"` — replaces the existing file.
  - `"cancel"` — aborts the download with status `canceled`.
- Or pass `confirm_overwrite(path) -> action` for a custom decision.

### Resume file layout (created next to the destination file)
```
<destination>\<name>.part                # partial data (preallocated)
<destination>\<name>.part.state.json     # resume state (segments, offsets, ETag/Last-Modified)
<destination>\<name>.part.state.json.tmp # transient, during a state save
```
On success both the `.part` and the `.state.json` are removed.

---

## B. GUI features (`gui.py`)

| # | Feature | Status |
|---|---|---|
| B1 | URL input (Enter key adds download) | Implemented |
| B2 | Destination folder picker | Implemented |
| B3 | Thread count spinner (1–32) | Implemented |
| B4 | Download list with File / Size / Progress / Speed / ETA / Status | Implemented |
| B5 | Live refresh every 500 ms | Implemented |
| B6 | Pause selected | Implemented |
| B7 | Resume selected | Implemented |
| B8 | Cancel selected | Implemented |
| B9 | Remove selected (cancels + drops row) | Implemented |
| B10 | Open completed file (button + double-click) | Implemented |
| B11 | Open containing folder | Implemented |
| B12 | Clear completed | Implemented |
| B13 | Total active speed in status bar | Implemented |
| B14 | Multi-select in the list | Implemented |
| B15 | Per-download speed limit control (**Limit...**) | Implemented (N1) |
| B16 | Settings persistence (folder, threads, limit, window) | Implemented (N1) |
| B17 | System tray / notifications | Planned |
| B18 | Dark theme | Planned |
| B19 | Custom headers dialog (`Headers...`) | Implemented (W2) |
| B20 | Cookie input in the GUI | Planned (API + Cookie header work today) |
| B21 | Queue restore on launch (all jobs listed) | Implemented (W3) |
| B22 | Auto-resume unfinished jobs (checkbox + setting) | Implemented (W3) |
| B23 | Queued status + queued count in the status bar | Implemented (W4) |
| B24 | Start Now / Move Up / Move Down | Implemented (W4) |
| B25 | Max-active setting (persisted) | Implemented (W4) |
| B26 | Browser... dialog (state, token, toggle, export) | Implemented (W1) |
| B27 | Browser downloads appear as normal queued jobs | Implemented (W1) |
| B28 | `--browser-selftest` headless check | Implemented (W1) |
| B29 | **Details...** dialog: full error + job facts | Implemented (N1) |
| B30 | Retry a failed job from the UI (Resume) | Implemented (N1) |
| B31 | Last save folder restored on launch | Implemented (N1) |
| B32 | Window size/position restored on launch | Implemented (N1) |
| B33 | Batch add: pasted multi-URL lines become separate jobs | Implemented (N2) |
| B34 | Watch clipboard: offer a copied link (opt-in, confirm) | Implemented (N2) |
| B35 | **Checksum...** dialog (algorithm + digest, selection + new jobs) | Implemented (N3) |
| B36 | **Clean Up...**: scan/delete abandoned `.part` files by age | Implemented (N3) |
| B37 | Details dialog shows the checksum and its result | Implemented (N3) |
| B38 | **Global Limit...**: cap the combined speed of all downloads | Implemented (N4) |
| B39 | Details dialog shows the piece count and dynamic splits | Implemented (N4) |
| B40 | Search box + status filter that hides non-matching rows | Implemented (N5) |
| B41 | Sort into category folders (toggle) | Implemented (N5) |
| B42 | Categories... editor with validation | Implemented (N5) |
| B43 | Export... / Import... the queue | Implemented (N5) |
| B44 | Show in Folder (reveal in Explorer) | Implemented (N5) |
| B45 | Schedule... (date + time for the selected jobs) | Implemented (N6) |
| B46 | Daily window control (start/end) in the filter bar | Implemented (N6) |
| B47 | Shut down when done (checkbox) | Implemented (N6) |
| B48 | Network... dialog (proxy, bypass, IPv4 preference, test) | Implemented (N7) |
| B49 | Mirrors... dialog for the selected job | Implemented (N7) |
| B50 | Confirmation before opening an executable/script | Implemented (security) |
| B51 | Export for Firefox / install or remove the native host | Implemented (N8) |

Default save folder: `%USERPROFILE%\Downloads`.

---

## C. Command-line features (`main.py`)

| # | Feature | Status |
|---|---|---|
| C1 | `FreeDM.exe URL` | Implemented |
| C2 | `-o / --output DIR` | Implemented |
| C3 | `-t / --threads N` | Implemented |
| C4 | `--limit BYTES_PER_SEC` | Implemented |
| C5 | Live progress line (source build only) | Implemented |
| C6 | `--selftest URL DIR` headless verification | Implemented |
| C7 | Ctrl+C pauses and keeps `.part` for resume | Implemented |
| C8 | Console output from the windowed exe | Not possible (windowed build) |

---

## D. Reliability / correctness

| # | Behaviour | Status |
|---|---|---|
| D1 | State only records bytes confirmed written to disk | Implemented |
| D2 | State file writes are atomic (`tmp` + `os.replace`) | Implemented |
| D3 | State writes serialised by a lock (no torn files) | Implemented |
| D4 | Save state immediately on pause | Implemented |
| D5 | Cleanup of partial files on cancel | Implemented |
| D6 | Cleanup of state file on success | Implemented |
| D7 | No overlap between piece writers | Implemented (by construction) |
| D8 | Segmented assembly byte-identical to source | Verified (SHA-256) |
| D9 | Resume refuses a changed remote file (size/validator) | Implemented (W5) |
| D10 | `If-Range` protects in-session pause/resume | Implemented (W5) |
| D11 | Existing destination never silently destroyed | Implemented (W5) |
| D12 | Insufficient disk space fails before downloading | Implemented (W5) |
| D13 | Worker exceptions surface as a specific error message | Implemented (W5) |
| D14 | A short download is reported as failed, never as done | Implemented (N3) |
| D15 | A checksum mismatch fails the job and shows both digests | Implemented (N3) |
| D16 | The finished file is never deleted by a failed verification | Implemented (N3) |
| D17 | A stored piece layout that does not tile the file is never resumed | Implemented (N4) |
| D18 | The piece count is bounded (≤ `MAX_SEGMENTS`), so the state/DB stay small | Implemented (N4) |

---

## E. Verification performed

All tests used `tests/range_server.py` (a local Range-capable server) so
results do not depend on third-party sites.

| Test | Result |
|---|---|
| Modules compile | Pass |
| **W5 suite: `tests/test_w5.py` (10 tests)** | **Pass** |
| **W2 suite: `tests/test_w2.py` (10 tests)** | **Pass** |
| **W3 suite: `tests/test_w3.py` (9 tests)** | **Pass** |
| **W4 suite: `tests/test_w4.py` (7 tests)** | **Pass** |
| **W1 suite: `tests/test_w1.py` (13 tests)** | **Pass** || **N1 suite: `tests/test_n1.py` (13 tests)** | **Pass** |
| **N2 suite: `tests/test_n2.py` (27 tests)** | **Pass** |
| **N3 suite: `tests/test_n3.py` (34 tests)** | **Pass** |
| **N4 suite: `tests/test_n4.py` (24 tests)** | **Pass** |
| **N5 suite: `tests/test_n5.py` (32 tests)** | **Pass** |
| **N6 suite: `tests/test_n6.py` (36 tests)** | **Pass** |
| **N7 suite: `tests/test_n7.py` (30 tests)** | **Pass** |
| **Security suite: `tests/test_security.py` (29 tests)** | **Pass** |
| **N8 suite: `tests/test_n8.py` (32 tests)** | **Pass** |
| **Changelog suite: `tests/test_changelog.py` (11 tests)** | **Pass** |
| A future start time holds the job in `scheduled` | Pass — released when the time comes |
| A closed window blocks every start; Start Now overrides it | Pass |
| A window of 23:00–06:00 wraps past midnight correctly | Pass |
| Shut-down asks first and never fires while a job is pending | Pass |
| `start_at` survives a restart (DB round-trip + migration) | Pass |
| Release notes are extracted per version from the changelog | Pass |
| Category rules parse, format and round-trip | Pass |
| File lands in the category folder (auto-sort on) | Pass — `Video/` |
| Without auto-sort the file stays in the base folder | Pass |
| Filter by name / host / status hides and shows rows live | Pass |
| Export → import round-trip keeps every field | Pass |
| Import of a plain list of URLs | Pass |
| Broken rules / broken JSON are reported, not ignored | Pass |
| Byte-identical download with dynamic pieces | Pass — SHA-256 matched |
| Pieces never exceed the 8 MB cap and still tile the file | Pass |
| Splitting moves already-downloaded bytes to the right piece | Pass |
| A slow connection gets a smaller piece than with fixed segments | Pass — 2 MB → 1 MB on a throttled server |
| Dynamic splitting does not make the download slower | Pass — within noise of the fixed run |
| Corrupt state file (overlapping pieces) is refused | Pass — download restarts cleanly |
| Two parallel downloads stay under the global cap | Pass |
| Per-download limit still works alongside the global cap | Pass |
| **W1 suite (14 tests, after the N3 socket fix)** | **Pass** — 8/8 consecutive runs (was flaky: ~1 in 3) |
| Correct sha256 → job completes, result "verified" | Pass |
| Wrong sha256 → job fails, message shows both digests | Pass |
| Truncated finished file → `verify_now()` reports a size mismatch | Pass |
| Short download never reported as done | Pass |
| Orphan scan honours the age limit and the file patterns | Pass |
| Cleanup deletes only the listed leftovers | Pass |
| Old DB gains `checksum` / `checksum_result` columns | Pass |
| One paste of 5 URLs parses to 5 jobs | Pass |
| Invalid entries reported (whole line or odd token) | Pass |
| Duplicates skipped and counted | Pass |
| Clipboard extraction with brackets/punctuation + exclude | Pass |
| `clipboard_monitor` defaults off and round-trips | Pass |
| Settings round-trip + typed defaults + bad-value fallback | Pass |
| Old DB without `speed_limit` is migrated on open | Pass |
| Live `set_speed_limit` caps throughput mid-download | Pass — 10 MB, 1 thread, < 400 KB in 1.5 s at 100 KB/s, then byte-correct when lifted |
| Per-job limit survives save/restore (`apply_record`) | Pass |
| Frozen exe `--selftest` (17.5 MB build) | **Pass** — `frozen=True` |
| Frozen exe `--browser-selftest` | **PASS** |
| `/add` rejects missing/wrong token (403) | Pass |
| Payload cookies/referer/UA/filename forwarded | Pass |
| Frozen `--browser-selftest` (server + export) | **PASS** |
| Active-download cap / total cap / per-host cap | Pass |
| `Retry-After` honoured (429) | Pass |
| FIFO order, Start Now, Move Up/Down | Pass |
| Queue survives close/reopen (5 jobs, auto-resume) | Pass |
| Resume without `.part.state.json` (DB fallback) | Pass |
| Dead DB does not break an active download | Pass |
| Referer-gated download | Pass — succeeds with header, 403 without |
| Cookie-gated download (dict / string / extension list) | Pass |
| Headers present on every segment request | Pass (gated multi-segment) |
| Redirect capture (`final_url`) | Pass |
| 20 MB segmented download, 8 threads | Pass — SHA-256 matched source |
| Pause → resume | Pass — byte-identical |
| Crash (process `os._exit`) → fresh process resume | Pass — byte-identical, artifacts cleaned |
| Resume after the remote file changed (same session) | Pass — restarted, matched **new** file |
| Changed ETag blocks stale state on resume | Pass |
| Unchanged state still resumes | Pass |
| Overwrite policy: rename / cancel / overwrite / callback | Pass — original preserved where required |
| Disk-space precheck | Pass — raises before downloading |
| Single-stream fallback (no-Range server) | Pass — SHA-256 matched |
| Speed limit 4 MB/s | Pass — measured 3.99 MB/s |
| GUI constructs and renders | Pass |
| Frozen exe `--selftest` (10 MB) | Pass — `frozen=True`, SHA-256 matched |
| Frozen exe GUI launch | Pass |

---

## F. Known limitations

- Servers that ignore `Range` get no speed-up (single stream).
- Speed gain depends on the server; many servers cap per-connection speed or
  total connections.
- Redirects are followed and the final URL is reused (W2). Authenticated or
  expiring URLs still need the right cookies/headers; the GUI dialog covers
  `Name: Value` headers, but there is no dedicated cookie editor yet.
- A supplied cookie/authorization that expires mid-download is reported
  clearly (`AuthRequiredError`) but not refreshed automatically.
- Queue metadata (including custom headers) is stored in plain text in the
  per-user SQLite DB; cookies supplied via `cookies=` are not persisted across
  restarts. Do not store secrets on a shared Windows account.
- A corrupted/locked queue DB is ignored (downloads still work) but the queue
  will not be restored until the DB is writable again.
- The queue is restored, but the active cap treats each job's thread count as a
  static connection budget; connections are not dynamically rebalanced while a
  job runs.
- Per-host budgets are keyed by `host:port`; mirrors/CDNs on different hostnames
  are treated as separate hosts.
- Speed limits are per download (**Limit...**); **Global Limit...** caps the
  combined speed of all downloads, but there is no time-of-day bandwidth
  schedule yet.
- Segments are split dynamically (N4) instead of being fixed at the start: a
  slow connection can only hold back one small piece, but the *number* of
  requests is higher than a fixed-segment run would use, and the piece count
  is capped at 1024.
- Batch add parses text you paste; there is no drag-and-drop of links yet
  (needs the third-party `tkinterdnd2`, tracked as P1.4). The clipboard watch is
  opt-in and confirmation-gated, and incognito/private-window copies may not be
  readable on some systems.
- Checksum verification only runs when a digest is supplied; there is no
  automatic lookup of a published checksum. The **Clean Up...** scan only
  matches FreeDM's own `.part` / `.part.state.json` names, and only deletes
  files older than the age you set.
- Browser handoff is Chrome/Edge only (Firefox is a later item); the token is
  pasted into the extension options once, and incognito downloads are left to
  the browser. Auto-launching FreeDM from the browser (native messaging) is not
  implemented.
- HLS/DASH streaming video is not a single file and is unsupported.
- A piece that is *already* being downloaded is never split in place; the
  splitter only re-divides the work that is still pending.
- The shut-down action hands over to the operating system's power command
  (`shutdown`/`rundll32 powrprof`); once it starts it cannot be undone.
- The proxy password is stored in plain text in the queue database, like the
  rest of the settings. Do not use it on a shared Windows account.
- A mirror must serve the **identical** file; FreeDM does not compare the
  bytes of two sources.
- The windowed exe has no console, so CLI progress is silent in the packaged
  build.
