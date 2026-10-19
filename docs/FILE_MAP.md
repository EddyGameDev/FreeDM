# FreeDM — File Map & Project Structure

This file tells a new agent **where everything lives** and **what each file
does**, so nobody wastes time re-discovering the project.

All paths are relative to the project root:

```
F:\OMNI Config\Plan\FreeDM\
```

(The original working copy also exists at `F:\OMNI Config\FreeDM\`; the copy
under `Plan\` is the consolidated deliverable. Treat `Plan\FreeDM\` as
canonical.)

---

## 1. Directory tree

```
F:\OMNI Config\Plan\FreeDM\
├── dist\
│   └── FreeDM.exe              # BUILT APPLICATION (double-click to run)
├── docs\
│   ├── OVERVIEW.md             # what it is, scope, how it works
│   ├── FEATURES.md             # every feature + status + location
│   ├── FILE_MAP.md             # this file
│   ├── ROADMAP.md              # future improvements (long-term backlog)
│   ├── MILESTONE_2.md          # sequenced next goals N1-N10 + progress
│   ├── NEXT_GOAL.md            # Milestone 1 record (W1-W5, complete)
│   └── PROJECT_PLAN.md         # original research/plan document
├── tests\
│   ├── range_server.py         # local HTTP server WITH Range + ETag support
│   ├── crash_session1.py       # starts a download, pauses, os._exit (crash sim)
│   ├── test_w2.py              # W2 suite: sessions, cookies, headers, redirects
│   ├── test_w3.py              # W3 suite: queue persistence, DB resume, isolation
│   ├── test_w4.py              # W4 suite: caps, FIFO, Retry-After
│   ├── test_w5.py              # W5 suite: validators, overwrite, disk space
│   ├── test_n1.py              # N1 suite: settings, migration, live speed limit
│   ├── test_n2.py              # N2 suite: batch parsing, clipboard detection
│   ├── test_n3.py              # N3 suite: size/checksum verification, cleanup
│   ├── test_n4.py              # N4 suite: dynamic pieces, global limit
│   ├── test_n5.py              # N5 suite: categories, filter, export/import
│   └── test_w1.py              # W1 suite: control server, token, payload
├── engine.py                   # download engine (the core)
├── store.py                    # SQLite persistent queue (W3)
├── scheduler.py                # active/connection/host caps + FIFO queue (W4)
├── settings.py                 # typed settings over the DB `settings` table (N1)
├── batch.py                    # batch URL parsing + clipboard link detection (N2)
├── verify.py                   # size/checksum verification + orphan cleanup (N3)
├── categories.py               # categories, filtering, queue export/import (N5)
├── control_server.py           # loopback browser-handoff endpoint (W1)
├── extension\                  # MV3 browser extension (W1)
│   ├── manifest.json
│   ├── background.js
│   ├── options.html / options.js
│   └── README.md
├── gui.py                      # Tkinter GUI
├── main.py                     # entry point: GUI / CLI / selftests
├── build.ps1                   # one-command rebuild of the exe
├── FreeDM.spec                 # PyInstaller spec (generated)
├── requirements.txt            # requests, pyinstaller
└── README.md                   # short user-facing readme
```

Not copied into `Plan\`: the `build\` folder (PyInstaller intermediates) and
`__pycache__\` (bytecode). Both are regenerable.

---

## 2. Source files in detail

### `engine.py` — download engine
The heart of the app. No UI dependencies; usable on its own.

| Symbol | Kind | Purpose |
|---|---|---|
| `CHUNK` | const | 128 KiB read/write chunk |
| `MIN_SEGMENT_SIZE` | const | 1 MiB; files smaller than this are single-stream |
| `MAX_RETRIES` | const | 6 retries per piece |
| `CONNECT_TIMEOUT` / `READ_TIMEOUT` | const | 15 s / 60 s |
| `DISK_MARGIN` | const | 64 MiB free space kept as headroom |
| `MAX_PIECE_SIZE` / `MIN_PIECE_SIZE` | const | N4 piece bounds (8 MB / 1 MB) |
| `MIN_SPLIT_SIZE` | const | both halves of a split must reach this size |
| `MAX_SEGMENTS` | const | hard cap on the number of pieces (1024) |
| `SPLIT_TARGET_SECONDS` | const | a piece should take ~this long (5 s) |
| `DYNAMIC_SPLITTING` | const | master switch for the N4 work queue (False = fixed pieces) |
| `USER_AGENT` | const | default browser-like UA |
| `IDLE, PROBING, DOWNLOADING, PAUSED, DONE, ERROR, CANCELED` | const | status strings |
| `DownloadCanceled` | exception | destination exists and overwrite declined |
| `FileChangedError` | exception | remote file changed; restart from zero |
| `RangeNotSupportedError` | exception | server stopped honouring Range |
| `AuthRequiredError` | exception | 401/403 — cookies/headers required; never retried |
| `human_size`, `human_speed`, `human_time` | func | display formatting |
| `sanitize_filename` | func | strip characters illegal on Windows |
| `RateLimiter` | class | token-bucket speed limit (`consume`, `set_rate`) |
| `Segment` | class | one byte range + progress (`size`, `remaining`, `done`, `to_dict`, `from_dict`) |
| `Download` | class | one download job — the public API |

**`Download` public API:** `start()`, `pause()`, `resume()`, `cancel()`,
`set_speed_limit(bps)`, `progress`, `eta`, `name`, `snapshot()`.
Constructor: `Download(url, dest_dir=None, filename=None, num_threads=8,
headers=None, speed_limit=0.0, verify_ssl=True, on_existing="rename",
confirm_overwrite=None, cookies=None, store=None, job_id=None, checksum="",
dest_resolver=None)`.
`cookies` accepts a `dict`, a `"a=1; b=2"` string, or a list of
`{name,value,domain,path}` dicts (browser-extension shape).
`snapshot()` includes `speed_limit`, `checksum`, `checksum_result` and
`job_id` (N1/N3).

**`Download` internals (call order):**
`start` → `_run` → `_probe` → `_prepare_files` → `_apply_existing_policy` →
(`_load_state` or `_preallocate`/`_check_disk_space`) → `_start_monitor` →
`_run_once` → `_download_segmented` (or `_download_single`) → `_finalize`.
A `FileChangedError` from `_run_once` triggers `_reset_for_restart` once.

**W5-specific internals:**
| Method | Purpose |
|---|---|
| `_validator_changed` | HEAD the URL and compare ETag/Last-Modified |
| `_apply_existing_policy` | rename / overwrite / cancel when destination exists |
| `_unique_path` | generate `name (1).ext` |
| `_check_disk_space` | fail early if free space < size + `DISK_MARGIN` |
| `_run_once` | one download pass; degrades on `RangeNotSupportedError` |
| `_reset_for_restart` | delete stale state after a file change and re-probe |

**W2-specific internals:**
| Attribute / method | Purpose |
|---|---|
| `session` | per-download `requests.Session`; cookie jar + pooled adapters (`pool_maxsize=64`) |
| `final_url` | URL after redirects; captured by `_probe`, persisted in state |
| `_request_url` | property returning `final_url or url`; used by every later request |
| `_apply_cookies` | seed the jar from dict / `"a=1; b=2"` / extension list |
| `_session_headers` | job headers applied to each request (Range/If-Range added per call) |

`Accept-Encoding: identity` is set unless the caller overrides it, so Range
offsets always address the raw file. `AuthRequiredError` (401/403) is raised
by `_probe`, `_download_segment`, and `_download_single` and is not retried.

**W3-specific internals:**
| Attribute / method | Purpose |
|---|---|
| `store`, `job_id` | optional queue DB and this job's row id |
| `apply_record` | seed a restored job from a DB row; schedules a re-probe |
| `_store_save` | best-effort row + segment sync (never raises) |
| `_load_db_segments` | resume from DB ranges when the JSON sidecar is gone |
| `abandon` | stop threads while keeping `.part` data (app close) |
| `_needs_prepare` | force probe/prepare on restart or retry |

**N1-specific internals / attributes:**
| Attribute / method | Purpose |
|---|---|
| `speed_limit` | current cap in bytes/s (0 = unlimited); shown by `snapshot()` |
| `set_speed_limit(bps)` | change the live cap (`rate.set_rate`), clamp negatives to 0, persist the job |
| `apply_record` (limit) | restores `speed_limit` from the DB row on startup |

**N3-specific internals / attributes:**
| Attribute / method | Purpose |
|---|---|
| `checksum` | expected digest, e.g. `"sha256:ab12…"` |
| `checksum_result` | last verification message ("sha256 checksum verified", "size mismatch: …") |
| `_check_complete` | refuse to finish a short download (`downloaded != total_size`) |
| `_verify_result` | size + checksum check of the finished file; raises `VerificationError` |
| `verify_now()` | re-verify a finished file → `(ok, message)`; marks the job `error` on failure |
| `set_checksum(spec)` | set/re-check a digest → `(ok, message)`; rejects malformed values |
| `VerificationError` | exception raised when the finished file fails verification |

**N4-specific internals / attributes:**
| Attribute / method | Purpose |
|---|---|
| `_pending` | pending pieces by index — the dynamic work queue |
| `_piece_speeds` | the last 8 completed piece speeds (drives the target) |
| `split_count` / `initial_piece_count` | how often the pieces were re-divided |
| `_prepare_pending` | build the work queue from the current pieces |
| `_piece_target` | adaptive piece size (1–8 MB) from the *slowest* recent piece |
| `_note_piece_speed` | record a finished piece's throughput |
| `_split_piece` | split a piece into a head + remainder, moving the downloaded bytes |
| `_claim_piece` | take the largest pending piece, splitting it when it is too big |
| `_pieces_are_valid` | the pieces must tile the file exactly (used when resuming) |
| `GlobalRateLimiter` / `GLOBAL_LIMITER` | one token bucket shared by every download |
| `set_global_speed_limit` / `global_speed_limit` | read/set the shared cap (0 = off) |
| `dest_resolver` | optional callable(filename) → folder, called after the probe (N5 categories) |

### `store.py` — persistent queue (W3)
Thread-safe SQLite wrapper; the DB is a queue index, not the payload.

| Symbol | Purpose |
|---|---|
| `default_db_path` | `%APPDATA%\FreeDM\freedm.db` (or `FREEDM_DB`) |
| `JobStore.add` | insert a job and return its id |
| `JobStore.save` | update size/offset/status/headers/validators |
| `JobStore.save_segments` | replace all ranges for a job in one transaction |
| `JobStore.load_segments` | ordered ranges for resume |
| `JobStore.list_all` / `get` / `delete` | queue history operations |
| `JobStore.get_setting` / `set_setting` | e.g. `auto_resume`, `last_dir`, `threads`, `speed_limit`, `window` |
| `JobStore._migrate` | adds later columns (e.g. `speed_limit`) to an existing DB |

Tables: `downloads` (includes `speed_limit` since N1), `segments`, `settings`.
WAL mode; write errors are captured in `last_error` and never propagate to the
download.

### `settings.py` — typed settings (N1)
Headless (no Tkinter) accessor layer over the `settings` table, shared by the
GUI, the CLI and the tests so defaults are defined once.

| Symbol | Purpose |
|---|---|
| `DEFAULTS` | canonical default for every known key |
| `load(store)` | all settings converted to their natural type (dict) |
| `save(store, **values)` | best-effort write; bools stored as `"1"`/`"0"` |
| `get_str` / `get_int` / `get_float` / `get_bool` | typed single-key reads |

Every accessor tolerates `store is None` and falls back to `DEFAULTS`, so the
GUI still starts when the database is unavailable.

### `batch.py` — batch input & clipboard (N2)
Headless helpers (no Tkinter) for turning pasted/clipboard text into URLs.

| Symbol | Purpose |
|---|---|
| `parse_urls(text)` | split pasted text on newlines **or** spaces into `(valid, invalid, duplicates)`; unwraps `(url)`/`[url]`/`<url>`, trims punctuation, de-dupes |
| `find_url(text, exclude=...)` | first http(s) URL in free text, punctuation/bracket-aware, skipping `exclude` |
| `_is_url` / `_normalise` / `_trim` | scheme check, token cleanup, balanced-bracket trimming |

### `verify.py` — integrity & orphan cleanup (N3)
Headless helpers for proving a finished file is intact and for tidying up
abandoned partial downloads.

| Symbol | Purpose |
|---|---|
| `ALGORITHMS` / `HEX_LENGTHS` | supported digests (sha256/sha512/sha1/md5) and their hex lengths |
| `parse_checksum(spec)` | `"sha256:ab12…"` or a bare 64-hex digest → `(algo, digest)`; raises `ValueError` with a clear message |
| `file_digest(path, algo)` | streamed hex digest (constant memory) |
| `verify_size(path, expected)` | `(ok, message)`; empty message when the size matches |
| `verify_checksum(path, spec)` | `(ok, message, status)`; status = `none`/`verified`/`mismatch`/`invalid`; a mismatch shows both digests |
| `is_orphan_name(name)` | True for `.part` / `.part.state.json` / `.part.state.json.tmp` |
| `find_orphans(folder, min_age_days)` | abandoned partials older than the given age (`<= 0` disables the scan) |
| `cleanup_orphans(paths)` | delete them → `(deleted, failed)` |

### `categories.py` — categories, filtering, export/import (N5)
Headless helpers for organising the queue. All the rules are plain text so
they can be edited by the user and stored in the settings table.

| Symbol | Purpose |
|---|---|
| `DEFAULT_CATEGORIES` | the shipped categories (Video, Music, Documents, Archives, Programs, Other) |
| `default_rules()` / `format_rules()` / `parse_rules()` | the editable rule text; `parse_rules` returns `(rules, errors)` |
| `load_rules(text)` | the user's rules, falling back to the defaults when unusable |
| `classify(filename, rules)` | the category of a file name |
| `destination_for(filename, base, rules)` | the folder a file should go to |
| `matches_filter(name, url, status, needle, status_filter)` | the list filter (name / URL / host / status) |
| `export_queue(jobs)` / `import_queue(text)` | the queue JSON format; the import also accepts a plain list of URLs |
| `STATUS_FILTERS` | the status values offered in the GUI filter |

### `scheduler.py` — polite concurrency (W4)
| Symbol | Purpose |
|---|---|
| `Scheduler` | FIFO queue + caps above `Download` |
| `submit` / `resume` | queue a job (status `queued`) and start when a slot is free |
| `pause` / `cancel` / `remove` | queue-aware job control |
| `start_now` / `move_up` / `move_down` | reorder the queue |
| `pump` | launch while `max_active`, `max_connections`, `max_per_host` allow |
| `set_max_active` | GUI/persisted active cap (default 3) |

Effective thread counts are assigned at launch (clamped by the remaining total
and host budgets) and restored when the job finishes. `Counter` per
`urlparse(...).netloc` enforces the per-host budget.

### `control_server.py` — browser handoff (W1)
| Symbol | Purpose |
|---|---|
| `ControlServer` | loopback `ThreadingHTTPServer`; `start()` / `stop()` / `running` / `port` |
| `_normalise` | validates/normalises an extension payload (http(s), size caps) |
| `load_or_create_token` | per-user token at `%APPDATA%\FreeDM\control_token.txt` |
| `extension_source_dir` | bundled extension path (temp dir when frozen) |
| `export_extension` | copies the extension to a stable folder |
| `ControlServer.start` handler | `GET /ping`; `POST /add` requires the token (403 without) |

Only `127.0.0.1` is bound; the request body is capped at 1 MiB; the token is
compared with `hmac.compare_digest`. The handler never downloads — it passes a
normalised job to `on_add`, and the GUI creates a regular `Download`.

### `extension/` — browser companion (W1)
| File | Purpose |
|---|---|
| `manifest.json` | MV3; permissions `downloads`, `cookies`, `storage`, `webRequest` |
| `background.js` | on a new download: pause → `GET /ping` → `POST /add` → cancel+erase, else resume |
| `options.html` / `options.js` | port + token settings, connection test |
| `README.md` | install steps (Load unpacked + paste token) |

### `gui.py` — Tkinter front-end
| Symbol | Purpose |
|---|---|
| `App` | main window; owns `downloads` list and `rows` (tree-id → Download) |
| `App._build_toolbar` | URL(s), save folder, threads, Add, **Headers...**, Auto-resume, **Watch clipboard** |
| `App._build_filterbar` | search box, status filter, **Sort into category folders**, **Categories...** (N5) |
| `App._apply_filter` / `_refresh_visible` | hide/show the rows that match the filter (N5) |
| `App.categories_dialog` | edit the category rules (N5) |
| `App.export_queue_dialog` / `import_queue_dialog` | write / read the queue file (N5) |
| `App._dest_resolver` / `_target_dir` | the category folder for a new download (N5) |
| `App.show_in_folder` | reveal the file in Explorer (N5) |
| `App._edit_headers` | dialog for `Name: Value` lines applied to new downloads |
| `App._restore_jobs` | reload the DB queue and auto-resume unfinished work |
| `App._restore_window` | re-apply the saved window geometry (N1) |
| `App._toggle_auto_resume` | persist the `auto_resume` setting |
| `App._change_max_active` | apply/persist the scheduler's active cap |
| `App._change_threads` | persist the thread spinner value (N1) |
| `App._toggle_clipboard` | persist + arm/disarm the clipboard watch (N2) |
| `App._check_clipboard` | poll the clipboard, confirm, then add a copied link (N2) |
| `App._new_download` / `_add_url` / `_enqueue` | shared job-creation path (N2) |
| `App.limit_selected` | set a live per-download cap + default (**Limit...**, N1) |
| `App.checksum_dialog` | set the expected digest for the selection + new jobs (**Checksum...**, N3) |
| `App.cleanup_dialog` | scan/delete abandoned `.part` files by age (**Clean Up...**, N3) |
| `App.show_details` | full untruncated job/error dialog (**Details...**, N1) |
| `App.start_now_selected` / `move_up_selected` / `move_down_selected` | queue controls |
| `App._browser_dialog` | token/enable/export UI for browser handoff (W1) |
| `App._add_from_browser` | turn an extension payload into a queued `Download` |
| `App._build_tree` | results table (File/Size/Progress/Speed/ETA/Status) |
| `App._build_buttons` | Pause/Resume/Cancel/Limit/Global/Checksum/Export/Import/Remove/Open/Clear |
| `App._poll` | 500 ms refresh loop via `root.after` |
| `App._on_close` | persist last dir/limit/window, pause workers, close store |
| `run_gui()` | creates `tk.Tk()`, applies "vista" theme, runs mainloop |
| `APP_NAME` | window title |

Preferences are read once at startup by `settings.load(store)` and written back
on change (`_change_threads`, `_change_max_active`, `_toggle_auto_resume`,
`_toggle_control`, `add_download`) and on close.

All UI updates happen on the Tk main thread; workers only mutate
thread-safe fields on `Download`.

### `main.py` — entry point
| Symbol | Purpose |
|---|---|
| `cli_download` | runs one download and prints progress |
| `_selftest` | headless download; writes `selftest_result.txt` (used to verify frozen builds) |
| `_emit` | safe stdout writer (windowed exe has `stdout=None`) |
| `main` | dispatches: `--selftest` → selftest; no args → GUI; else CLI |

### `tests/range_server.py`
Threaded HTTP server that **honours `Range`**, **emits `ETag` /
`Last-Modified`**, and serves a generated `test.bin`.
Usage: `python tests/range_server.py [port] [size_mb]` (default 8765 / 20 MB).
Prints the served URL. Also exposes:
- `GET /hash` — SHA-256 of the current file
- `GET /mutate` — rewrite the file (simulate a changed remote file)
- `GET /size` — current size
- `/protected/test.bin` — requires `Referer` containing `freedm-test`, else 403
- `/cookie/test.bin` — requires `Cookie: auth=secret`, else 403
- `/redirect/test.bin` — 302 to `/test.bin`
- `/retry/test.bin` — `reset_retry(n)` makes it answer `429 Retry-After: 1` n times
- `/throttle/test.bin` — the first client connection is slowed to
  `set_throttle(bps)`; `throttled_stats()` reports the bytes it served and the
  size of the first piece it was given (N4)
`start_server(port, size_mb)` starts it on a daemon thread for tests.

### `tests/test_w1.py`
The W1 suite (13 tests): ping/404s, 403 without/wrong token, `X-FreeDM-Token`
support, payload forwarding, URL/JSON validation, thread clamping, CORS
preflight, token-file stability, extension export, and a malformed-cookie
regression. Run with `python tests/test_w1.py` or `python -m pytest tests/test_w1.py`.

### `tests/test_w4.py`
The W4 suite (7 tests): active cap, total-connection cap, per-host cap,
thread-count restore, FIFO/Start Now/reorder, queued pause/resume, and
`Retry-After` timing. Run with `python tests/test_w4.py` or
`python -m pytest tests/test_w4.py`.

### `tests/test_w2.py`
The W2 suite (10 tests): no-header regression, referer gate pass/fail, cookie
gate via dict/string/extension list, failure without cookies, headers on every
segment, redirect `final_url` capture, redirect + cookies. Run with
`python tests/test_w2.py` or `python -m pytest tests/test_w2.py`.

### `tests/test_w3.py`
The W3 suite (9 tests): store round-trip/order/delete/settings, engine
completion persistence, pause offsets, dead-DB isolation, restart resume,
DB fallback without a JSON sidecar, and the 5-job close/reopen acceptance
scenario. Run with `python tests/test_w3.py` or
`python -m pytest tests/test_w3.py`.

### `tests/test_w5.py`
The W5 regression suite (10 tests): normal download, pause/resume, validator
mismatch/match, same-session file change, overwrite rename/cancel/overwrite,
confirm callback, disk-space precheck. Run with
`python tests/test_w5.py` or `python -m pytest tests/test_w5.py`.

### `tests/test_n1.py`
The N1 suite (13 tests): settings defaults/typing/round-trip/bad-value
fallback, bool parsing, the `speed_limit` DB migration, live `set_speed_limit`
(clamp + rate), snapshot field, per-job persistence, `apply_record` restore,
`RateLimiter` throttling, and a single-thread integration test that the cap
bounds mid-flight throughput and then finishes byte-correct when lifted. Run
with `python tests/test_n1.py` or `python -m pytest tests/test_n1.py`.

### `tests/test_n2.py`
The N2 suite (27 tests): batch splitting (newline/space), whole-line vs odd-
token invalid reporting, duplicate skipping, blank/`None` input, scheme case,
punctuation/unwrapping, clipboard extraction with `exclude` and balanced
brackets, the off-by-default persisted setting, the GUI API surface, and 8
**real Tk-window** integration tests (5 URLs → 5 rows, duplicates skipped,
invalid reported, mixed add, clipboard off by default, confirmed add, declined
add, offered only once). Run with `python tests/test_n2.py` or
`python -m pytest tests/test_n2.py`.

### `tests/test_n3.py`The N3 suite (34 tests): checksum parsing (all algorithms, bare/explicit
forms, unknown algorithm, wrong length, non-hex), `file_digest` vs hashlib,
size verify (ok/short/unknown), checksum verify (match/mismatch showing both
digests/none/invalid), orphan detection by age + pattern, orphan cleanup,
engine-level correct/wrong checksum, truncated-file `verify_now()`, checksum
persistence and `apply_record` restore, the DB migration, and 4 real-GUI tests.
Run with `python tests/test_n3.py` or `python -m pytest tests/test_n3.py`.

### `tests/test_n4.py`
The N4 suite (24 tests): piece-layout validation, split byte accounting, the
adaptive piece target, the piece-size cap, work-queue splitting, the
`DYNAMIC_SPLITTING` switch, a byte-identical download, resume after a pause,
refusal of a corrupt state file, the global speed cap (and that the
per-download cap still works next to it), a throttled-server comparison, and 4
real-GUI tests. Run with `python tests/test_n4.py` or
`python -m pytest tests/test_n4.py`.

### `tests/test_n5.py`
The N5 suite (32 tests): rule parsing/formatting/round-trip, bad-line
reporting, classification, destination, filter matching by name/host/status,
queue export and import (JSON, plain URL list, broken input), the engine's
`dest_resolver` (and that the base folder is used without one), the new
settings, and 8 real-GUI tests (filter by name/status/host, the filter being
remembered, auto-sort on/off, export→import round-trip, plain-URL import).
Run with `python tests/test_n5.py` or `python -m pytest tests/test_n5.py`.

### `tests/crash_session1.py`
Starts a download at a speed limit, pauses after 1.5 s, then calls
`os._exit(0)` to simulate a hard crash (OS releases file handles).
Usage: `python tests/crash_session1.py <out_dir> <url>`.

### `build.ps1`
Runs PyInstaller with the exact flags used for the shipped exe:
`--onefile --windowed --name FreeDM --hidden-import requests
--collect-submodules requests main.py`.

Output: `dist\FreeDM.exe`.

### `FreeDM.spec`
Auto-generated by PyInstaller. Not hand-edited. Rebuild with `build.ps1`.

### `requirements.txt`
`requests>=2.28`, `pyinstaller>=6.0`.

---

## 3. Runtime files (created while downloading)

These are written **next to the final destination file**, not in the project:

| Path | When | Meaning |
|---|---|---|
| `<dest>\<name>.part` | during download | the in-progress file (preallocated to full size) |
| `<dest>\<name>.part.state.json` | during download | resume state: URL, size, `supports_range`, `ETag`/`Last-Modified`, per-segment offsets |
| `<dest>\<name>.part.state.json.tmp` | briefly, during saves | atomic-save scratch file |
| `<dest>\<name>` | on success | final file; `.part` is renamed onto it |
| `%APPDATA%\FreeDM\freedm.db` | always (GUI) | SQLite queue: `downloads` (incl. `speed_limit`), `segments`, `settings`; `FREEDM_DB` overrides |
| `%APPDATA%\FreeDM\freedm.db-wal`, `-shm` | while open | SQLite WAL sidecars (normal; do not delete while running) |
| `%APPDATA%\FreeDM\control_token.txt` | first GUI run | browser-handoff token (`FREEDM_HOME` overrides the folder) |
| `%APPDATA%\FreeDM\extension\` | Export extension | exported MV3 extension loaded into Chrome/Edge |
| `<dest>\selftest_result.txt` | only `--selftest` | self-test log |
| `<dest>\browser_selftest_result.txt` | only `--browser-selftest` | control-server self-test log |

Default destination when none is given: `%USERPROFILE%\Downloads`
(GUI) or the current directory (engine default).

The app has **no registry use and no separate config file**. Preferences live in
the `settings` table of the same DB (`last_dir`, `threads`, `speed_limit`,
`window`, `auto_resume`, `max_active`, `max_connections`, `max_per_host`,
`control_enabled`, `clipboard_monitor`). The only persistent state is the queue DB under
`%APPDATA%\FreeDM\` plus per-download files in the destination folder. Delete
the DB to reset the queue and preferences (partial files remain).

---

## 4. Build artifacts

| Path | Meaning |
|---|---|
| `dist\FreeDM.exe` | the shipped single-file app (≈17.5 MB, extension bundled) |
| `build\` | PyInstaller intermediates (regenerable, not copied to Plan) |
| `FreeDM.spec` | generated build recipe |

---

## 5. Where to change what

| I want to change… | Edit |
|---|---|
| Download logic, retries, segmentation | `engine.py` |
| Speed limiting (live per-download cap) | `engine.py` → `RateLimiter`, `Download.set_speed_limit` |
| The shared (all-downloads) speed cap | `engine.py` → `set_global_speed_limit` |
| Segmentation / piece splitting | `engine.py` → `_claim_piece`, `_split_piece`, `_piece_target` |
| Preferences / stored defaults | `settings.py` (+ `store.py` `settings` table) |
| Batch URL parsing / clipboard detection | `batch.py` |
| Categories, list filter, queue export/import | `categories.py` |
| Size/checksum verification, orphan cleanup | `verify.py` |
| Resume state format | `engine.py` → `_save_state` / `_load_state` |
| Cookies / request headers | `engine.py` → `_apply_cookies`, `_session_headers` |
| Redirect handling | `engine.py` → `_probe`, `_request_url`, `final_url` |
| Queue persistence / DB schema | `store.py` → `JobStore` |
| Restore/auto-resume behaviour | `gui.py` → `_restore_jobs` |
| Concurrency caps / queue order | `scheduler.py` → `Scheduler` |
| Browser handoff endpoint / token | `control_server.py` |
| Browser extension behaviour | `extension\background.js` (manifest in `extension\manifest.json`) |
| GUI layout or buttons | `gui.py` |
| Adding a new CLI flag | `main.py` → `main`/`cli_download` |
| How the exe is packaged | `build.ps1` |
| Test server behaviour | `tests/range_server.py` |
| Documentation | `docs\*.md` |

After any source change, rebuild with:

```
powershell -ExecutionPolicy Bypass -File build.ps1
```

Run all regression suites (each starts its own server):

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

Then re-run the frozen check:

```
dist\FreeDM.exe --selftest "http://127.0.0.1:8765/test.bin" "%TEMP%\freedm_frozen"
dist\FreeDM.exe --browser-selftest "%TEMP%\freedm_browser"
```

(Start `python tests\range_server.py 8765 20` first for the first command;
`--browser-selftest` needs no server.)
