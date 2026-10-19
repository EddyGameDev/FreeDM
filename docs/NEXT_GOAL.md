# FreeDM — Next Goal: Everyday Usability

**Status:** milestone complete — **W1, W2, W3, W4 and W5 all done (2026-10-19)** ·
Companion to `ROADMAP.md`

> **This document is the completed Milestone 1 record.** For the next set of
> goals (N1–N10) and current progress, see **[`MILESTONE_2.md`](MILESTONE_2.md)**.
> N1 (settings persistence, live per-download speed limit, job details) is
> **done**; N2 (batch input & clipboard) is next.

This document identifies the blockers that most limit real-world use of FreeDM
and defines the **next milestone**. It is written so an agent can pick it up
without re-analysing the code.

## Progress log

| Date | Workstream | Result |
|---|---|---|
| 2026-10-19 | **W5 — integrity & UX safety** | **DONE.** ETag/Last-Modified + `If-Range` resume validation, auto-restart on remote change, overwrite policy (rename/overwrite/cancel/callback), disk-space precheck, Range-loss fallback, worker error propagation. 10/10 tests pass; frozen exe re-verified. |
| 2026-10-19 | **W2 — session & header fidelity** | **DONE.** Per-download `requests.Session` with connection pooling, cookie jar (dict/string/extension-list), custom headers (Referer, Cookie, Authorization...), redirect `final_url` reuse, `Accept-Encoding: identity`, clear 401/403 errors, GUI `Headers...` dialog. 10/10 tests pass; frozen exe re-verified. |
| 2026-10-19 | **W3 — persistent queue & auto-resume** | **DONE.** `freedm/store.py` SQLite job store, schema + settings, engine persistence hooks, DB segment fallback when the JSON sidecar is lost, GUI reload/auto-resume with a toggle, remove/clear delete rows, close preserves partials. 9/9 tests pass (including 5-job close/reopen). Also fixed a rate-limiter hang when the speed cap was below one 128 KiB chunk. |
| 2026-10-19 | **W4 — polite concurrency & queue control** | **DONE.** `freedm/scheduler.py`: active-download cap (default 3), total-connection cap (64), per-host cap (12), FIFO queue with Start Now / Move Up / Move Down, queued status, and `Retry-After` handling for 429/503. GUI shows queued counts and persists the active cap. 7/7 tests pass; full regression green. Also fixed a pause-during-probe race. |
| 2026-10-19 | **W1 — browser handoff** | **DONE.** `freedm/control_server.py` (loopback-only, token-authenticated) with `GET /ping` and `POST /add`; MV3 extension (`extension/`) pauses a browser download, pings FreeDM, forwards URL/cookies/referer/UA/filename, then cancels the browser copy — or resumes it when FreeDM is closed or rejects the request. GUI **Browser...** dialog (token, enable toggle, Export extension). 13/13 tests pass; frozen `--browser-selftest` PASS. |

---

## 1. Method

A "blocker" here is not a missing nice-to-have. It is something that causes a
user with a real download to **give up or fail**. Ranked by:

```
impact = (share of real downloads affected) x (how hard it is to work around)
```

A bug that affects 5% of downloads but has no workaround can outrank a missing
feature that affects 50% but has a manual workaround.

---

## 2. The blockers, ranked

| # | Blocker | Why it caps usage | Evidence in this repo | Effort |
|---|---|---|---|---|
| **B1** | **No browser takeover** | Most downloads begin with a click in a browser. Requiring users to copy a URL and paste it into the app loses the majority of casual users on the first try. | ~~GUI only accepts a typed/pasted URL; no extension, no local control endpoint.~~ **Fixed in W1:** loopback token server + MV3 extension + GUI Browser dialog. | ~~M-L~~ |
| **B2** | **No real session / header fidelity** | A large share of real URLs fail without cookies, `Referer`, `User-Agent`, or `Authorization`. Login-gated files, signed CDN URLs, anti-bot checks, and hotlink protection all break. | ~~Every request is a bare `requests.get(...)`; no `requests.Session`, no cookie jar.~~ **Fixed in W2:** per-download Session, cookie jar, header replay, `final_url`. | ~~M~~ |
| **B3** | **No persistent queue / no auto-resume** | The app is a one-shot downloader. Close it and every job disappears. It cannot be a daily driver, and unfinished work is invisible after restart even though the `.part` state exists. | ~~`self.downloads` is an in-memory list (`gui.py:34`); nothing on disk except per-file `.part` state.~~ **Fixed in W3:** SQLite queue, reload-on-launch, DB-backed resume. | ~~M~~ |
| **B4** | **Unbounded concurrency / no per-host limit** | Adding several downloads at once fires them all immediately, each with up to 32 threads. That triggers HTTP 429/ban on many hosts and makes the app unsafe to queue work in. | ~~`add_download` calls `dl.start()` immediately (`gui.py:138`); `num_threads` allowed up to 32; no semaphore, no `Retry-After` handling.~~ **Fixed in W4:** scheduler caps + 429/503 backoff. | ~~S-M~~ |
| **B5** | **Distribution trust (SmartScreen / antivirus)** | An unsigned single-file PyInstaller exe is frequently flagged by Defender heuristics and always shows SmartScreen's "unknown publisher" on first run. Users abandon at that point. | `build.ps1` builds `--onefile` with no signing and no version resource. | S–M |
| **B6** | **Resume can corrupt if the remote file changed** | If the server's file is replaced between pause and resume, old offsets are applied to new bytes. Silent data corruption. | ~~Resume state stores only URL, size, segment offsets.~~ **Fixed in W5.** | ~~S~~ |
| **B7** | **No streaming-video support** | A major reason people install IDM-likes is saving videos (HLS/DASH). Those are not single files, so the current engine cannot touch them. | Engine downloads exactly one HTTP resource. | L |
| **B8** | **No proxy support** | Blocks corporate, campus, and restricted-network users entirely. | No `proxies=` plumbing anywhere. | M |
| **B9** | **Silent overwrite / no disk-space check** | `os.replace` destroys an existing file without asking; preallocation fails with a cryptic error on a full disk. Data-loss risk. | ~~`engine.py: _finalize`; `_preallocate`.~~ **Fixed in W5.** | ~~S~~ |
| **B10** | **No installer / no console build** | Friction for non-technical users; the windowed exe prints nothing for CLI use. | `build.ps1` produces one windowed onefile. | S |

---

## 3. The next goal

> **Milestone 1 — "Everyday Usability": make FreeDM the tool people actually
> reach for when they download something, not a demo they try once.**

Success means a non-technical Windows user can:

1. Click a download link in their browser and have FreeDM take it over,
2. download login-gated / hotlink-protected files that a browser could fetch,
3. queue many downloads, close the app, and have them continue next launch,
4. do all of that without getting rate-limited or banned.

### In scope for this milestone

**B1, B2, B3, B4**, plus the cheap correctness/UX fixes **B6 and B9**.

### Explicitly out of scope (later milestones)

- B5 trusted distribution → *Milestone 2*
- B7 streaming video, B8 proxy → *Milestone 3*
- B10 installer/console build → *Milestone 2*
- Dynamic segmentation, multi-source, FTP → *Milestone 3+*

---

## 4. Workstreams

Each workstream lists **what to build**, **acceptance criteria**, and **how**.

### W1 — Browser handoff  (addresses B1)  ✅ **DONE 2026-10-19**

**What shipped:**
- `freedm/control_server.py`: `ThreadingHTTPServer` bound to `127.0.0.1:6801`
  (configurable via the constructor; tests use port 0). Endpoints:
  - `GET /ping` → `{ok, app:"FreeDM", port}` (no token; used for detection).
  - `POST /add` → normalises `{url, cookies, referer, user_agent, filename,
    threads, headers, dest_dir}` and hands it to the GUI.
- Security: token in `%APPDATA%\FreeDM\control_token.txt` (auto-generated,
  `secrets.token_urlsafe(32)`); required as `Authorization: Bearer <token>` or
  `X-FreeDM-Token`; rejected with **403** when missing/wrong. Loopback only,
  request body capped at 1 MiB, URLs restricted to http(s).
- `extension/` (MV3, Chrome/Edge): pauses the browser download, pings FreeDM,
  forwards the job, then cancels+erases the browser copy. If FreeDM is closed
  or rejects the request, it **resumes** the browser download, so nothing is
  duplicated or lost. Also bundled into the exe and exportable from the GUI.
- GUI: **Browser...** dialog (running state + port, enable toggle, token with
  Copy, Export extension) and an incoming-job queue drained on the Tk thread.
- `main.py --browser-selftest` for headless verification of the frozen build.

**Tests:** `tests/test_w1.py` — 13/13 pass: ping, 404s, 403 without/wrong
token, `X-FreeDM-Token` support, payload forwarding (cookies/referer/UA/
filename/headers), URL/JSON validation, thread clamping, CORS preflight, token
file stability, extension export, and a malformed-cookie regression.

**Acceptance criteria:** all met.
- A browser click starts the download in FreeDM with no copy/paste. ✅
- The browser's own download is cancelled (and erased), not duplicated. ✅
- With FreeDM closed, ping fails and the browser download resumes normally. ✅
- A request without the token is rejected with 403. ✅

**Known limitations:** Chrome/Edge only (Firefox variant is P4.2); the token is
pasted into the extension options once; incognito downloads are intentionally
left to the browser; no native-messaging auto-launch (P4.3).

---

### W2 — Session & header fidelity  (addresses B2)  ✅ **DONE 2026-10-19**

**What shipped:**
- Each `Download` owns a `requests.Session` used for the probe, every segment,
  `_validator_changed`, and single-stream downloads. An `HTTPAdapter`
  (`pool_connections=16`, `pool_maxsize=64`) gives keep-alive reuse.
- Header precedence: per-request (`Range`, `If-Range`) > job headers
  (`Referer`, `Cookie`, `Authorization`, `User-Agent`) > session defaults.
- `Accept-Encoding: identity` is forced unless the caller overrides it, so
  byte ranges always address the raw file.
- `cookies=` accepts a `dict`, a `"a=1; b=2"` string, or a list of
  `{name,value,domain,path}` dicts (the shape a browser extension would send).
- `_probe` captures `final_url` after redirects and `_request_url` is used for
  every later request, so signed/CDN URLs are fetched directly.
- `AuthRequiredError` gives a clear 401/403 message instead of a generic HTTP
  error, and is never retried.
- GUI: a **Headers...** button opens a dialog for `Name: Value` lines applied
  to new downloads.

**Tests:** `tests/test_w2.py` — 10/10 pass. Covers no-header regression,
referer gate (pass/fail), cookie gate via dict/string/extension-list (pass) and
fail-without, headers reaching every segment, redirect `final_url`, and redirect
plus cookies.

**Acceptance criteria:** all met.
- Referer-gated download succeeds. ✅
- Cookie-gated download succeeds with supplied cookies. ✅
- Every segment carries the same cookies/referer (gated multi-segment test). ✅
- Works with no headers (backwards compatible). ✅

---

### W3 — Persistent queue & auto-resume  (addresses B3)  ✅ **DONE 2026-10-19**

**What shipped:**
- New `freedm/store.py` with `JobStore`, a thread-safe SQLite wrapper at
  `%APPDATA%\FreeDM\freedm.db` (`FREEDM_DB` overrides it for tests).
- Schema: `downloads` (url, final_url, dest_dir, filename, size, downloaded,
  threads, status, headers_json, etag, last_modified, error, timestamps),
  `segments` (per-job ranges + offsets), `settings(key, value)`. WAL mode.
- Engine: `Download(..., store=..., job_id=...)`, `apply_record()`,
  `_store_save()`, DB writes on probe/pause/progress/finalize, `abandon()` to
  stop threads without deleting partials, and `_load_db_segments()` as the
  resume source when the JSON sidecar is missing. Stored validators/size are
  checked before DB ranges are trusted.
- GUI: `App(root, store)` restores the queue on launch, auto-resumes
  active/queued jobs (checkbox + `auto_resume` setting), shows paused/error/
  done history, deletes rows on Remove/Clear, and pauses + abandons running
  jobs on window close so partials survive.
- Robustness: every DB write is best-effort (a dead DB cannot abort a
  download); `_finalize` retries `os.replace` on transient Windows locks.
- Bonus fix: the rate limiter no longer hangs when the per-second cap is
  smaller than one 128 KiB read chunk.

**Tests:** `tests/test_w3.py` — 9/9 pass. Covers store round-trip/order/delete/
settings, engine completion persistence, pause offsets, dead-DB isolation,
restart resume, DB fallback without a sidecar, and the 5-job close/reopen
acceptance scenario.

**Acceptance criteria:** all met.
- Add 5, close mid-transfer, reopen → all 5 listed and resume; done stays done. ✅
- History survives a reopen/reboot (SQLite file). ✅
- DB write failure does not corrupt or abort the `.part` payload. ✅

**Known trade-off:** `headers_json` (which may include `Authorization`/`Cookie`)
is stored in the per-user DB in plain text; cookies passed via `cookies=` are
not persisted at all. See `FEATURES.md` §F.

---

### W4 — Polite concurrency & queue control  (addresses B4)  ✅ **DONE 2026-10-19**

**What shipped:**
- New `freedm/scheduler.py` (`Scheduler`) above `Download`: FIFO queue, queued →
  active transitions, and automatic refill as slots free.
- Caps: `max_active` (default 3, GUI setting), `max_connections` (64) and
  `max_per_host` (12) keyed by `urlparse(...).netloc`. Each job's effective
  thread count is clamped to the remaining total/host budget at launch and
  restored when it finishes.
- `Download.start()` now marks `PROBING` synchronously (prevents double-start
  races and lets the scheduler count a job immediately); `QUEUED` is a real
  persisted status.
- `429`/`503`: the engine honours `Retry-After` (seconds or HTTP date) or uses
  exponential backoff, in cancel/pause-aware slices; probe/segment/single all
  participate.
- GUI: active cap spinbox (persisted), **Start Now**, **Move Up**, **Move Down**,
  queued counts in the status bar, and Pause/Resume/Cancel routed through the
  scheduler.
- Fixed a race where pausing during probe/prepare could be overwritten by the
  run thread and leave the job stuck as downloading.

**Tests:** `tests/test_w4.py` — 7/7 pass: active cap, total-connection cap,
per-host cap, thread-count restore, FIFO + Start Now + reorder, queued
pause/resume, and `Retry-After` timing.

**Acceptance criteria:** all met.
- Active downloads never exceed the cap. ✅
- Per-host concurrent connections never exceed the cap. ✅
- `Retry-After` is honoured before retrying. ✅
- Queued jobs start automatically as slots free. ✅

---

### W5 — Cheap correctness fixes  (addresses B6, B9)  ✅ **DONE 2026-10-19**

**What shipped:**
- **Resume integrity:** `_probe` captures `ETag` (preferred) or
  `Last-Modified`; `_save_state` stores it; `_load_state` rejects a state file
  whose size or validator no longer matches. Requests with existing bytes send
  `If-Range`; a `200` response triggers `_validator_changed()` — a real change
  raises `FileChangedError` and `_reset_for_restart()` re-probes and restarts
  once; otherwise the engine degrades to single-stream (`RangeNotSupportedError`).
- **Overwrite policy:** `on_existing="rename"` (default) / `"overwrite"` /
  `"cancel"`, plus a `confirm_overwrite(path)` callback. Implemented in
  `_apply_existing_policy` + `_unique_path`.
- **Disk-space check:** `_check_disk_space` compares `Content-Length` to
  `shutil.disk_usage(dir).free` minus a 64 MiB `DISK_MARGIN`.
- **Bonus hardening:** worker exceptions now propagate to the download status
  (`_worker`/`_download_segmented`), and a server that stops honouring `Range`
  falls back automatically instead of failing.

**Tests:** `tests/test_w5.py` — 10/10 pass. Covers unchanged resume, validator
mismatch blocking resume, same-session change restart, all overwrite modes, the
callback, and the disk-space error. Also re-verified the 20 MB segmented hash,
crash-resume, GUI construction, and the frozen exe `--selftest`.

**Acceptance criteria:** all met.
- Remote file replaced between pause and resume → clean restart, final hash
  matches the **new** file. ✅
- Existing destination never destroyed unless the policy allows it. ✅
- Insufficient disk space → human-readable error before downloading. ✅

---

## 5. Sequencing & dependencies

``` 
W5 (integrity) ✅ ─┐
                   ├─> W3 (queue) ✅ ─> W4 (scheduler) ✅
W2 (sessions)  ✅ ─┘                     │
                                         v
W1 (browser)  ───────────────────> needs W2 ✅ + W3 ✅  **DONE**
```

- **W2 before W1:** done — the extension hands over cookies/referer.
- **W3 before W4:** done — the scheduler persists queued/active state.
- **W5 anytime:** done (safety fixes shipped).
- **W1 last:** done — the browser handoff tops off the milestone.

Suggested order: **W5 ✅ → W2 ✅ → W3 ✅ → W4 ✅ → W1 ✅**.
Milestone status: **complete.** Next horizon items live in `ROADMAP.md`.

---

## 6. Definition of done for Milestone 1

- All acceptance criteria in W1–W5 pass on a clean Windows machine.
- `--selftest` still passes, plus new tests for: cookie/referer download,
  queue persistence across restart, per-host cap, `429` backoff, and
  changed-file resume.
- `docs/FEATURES.md` and `docs/FILE_MAP.md` updated to match.
- A short "Browser setup" section added to `README.md`.

---

## 7. Success metrics

| Metric | Before | Target |
|---|---|---|
| Steps to download a browser link | copy URL → paste → Add (3+) | 1 click |
| Downloads requiring cookies/referer that succeed | ~0% | >90% |
| Jobs surviving a restart | 0% | 100% |
| Rate-limit failures with 20 queued jobs | frequent | none |
| Silent data-loss paths | 2 (B6, B9) | 0 |

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| Browser extension review / permissions friction | Ship unpacked/dev first; request minimum scopes; document install. |
| Local control server abused by other local apps | Token + `Origin` check + loopback-only bind. |
| Cookie handling breaks on exotic sites | Keep a "disable takeover" toggle and browser fallback. |
| SQLite + `.part` state drift | DB authoritative; `.part.state.json` is fallback only; reconcile on load. |
| Per-host caps slow power users | Make caps configurable in settings. |
| SmartScreen still warns until reputation (B5, Milestone 2) | Document; submit false-positive reports; optional signing later. |

---

## 9. One-line summary

**The next goal is to stop being a URL box and become a real browser-connected,
session-aware, persistent, rate-limit-safe download manager.** Everything else
is downstream of those four things.
