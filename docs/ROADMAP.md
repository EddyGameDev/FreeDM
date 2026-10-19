# FreeDM — Future Improvement Plan

> **Start with `MILESTONE_2.md`** for the sequenced *next* goals (N1–N10) and
> current progress. **`NEXT_GOAL.md`** is the completed Milestone 1 record
> (browser handoff, sessions/cookies, persistent queue, polite concurrency).
> This file is the longer-term backlog behind both.
>
> **Progress:** Milestone 1 is **done** — W5 (resume integrity, overwrite
> policy, disk-space precheck, Range-loss fallback), W2 (session/cookie/header
> fidelity, redirect `final_url`), W3 (SQLite queue, auto-resume, DB-backed
> segment recovery), W4 (active/connection/per-host caps, FIFO, Retry-After)
> and W1 (loopback control server + MV3 browser handoff).
>
> Milestone 2 has started — **N1–N7 done**: N1 (P0.2–P0.5: settings
> persistence, live per-download speed limit, retry-from-UI, full error
> details), N2 (P1.3/P1.5: batch multi-URL add, opt-in clipboard watch),
> N3 (P5.3/P5.10 + debt #3: size and checksum verification, abandoned
> `.part` cleanup), N4 (P5.1/P5.2 + debt #4: dynamic segmentation,
> adaptive piece sizing, global speed cap), N5 (P1.2/P3.2–P3.4:
> categories with auto-sort, list filtering, queue export/import), N6
> (P2.1–P2.3: scheduled starts, a daily download window, shut-down when
> the queue drains) and N7 (P5.4/P5.5/P5.8: proxy with a bypass list,
> IPv4/IPv6 preference, mirror sources). See `MILESTONE_2.md` §Progress log.

This roadmap is ordered by **user value ÷ effort**. Items are independent
unless a dependency is noted. Nothing here is implemented yet unless marked.

Effort is rough developer time: **S** ≈ ≤1 day, **M** ≈ 2–4 days,
**L** ≈ 1–2 weeks.

---

## Priority 0 — Quick wins / polish (do first)

| # | Item | Effort | Notes |
|---|---|---|---|
| ~~P0.1~~ | ~~**Overwrite / rename confirmation**~~ | ~~S~~ | **DONE (W5).** `on_existing="rename"` is the default; `overwrite`/`cancel`/callback also supported. |
| ~~P0.2~~ | ~~**Persist settings** (last folder, threads, speed limit, window size)~~ | ~~S~~ | **DONE (N1).** `freedm/settings.py` + the `settings` table — no separate JSON file needed. Persists `last_dir`, `threads`, `speed_limit`, `window`, plus the earlier toggles. |
| ~~P0.3~~ | ~~**Per-download speed limit in the GUI**~~ | ~~S~~ | **DONE (N1).** **Limit...** sets a live cap on the selection (`Download.set_speed_limit`) and the default for new downloads; persisted per job. |
| ~~P0.4~~ | ~~**Retry failed downloads from the UI**~~ | ~~S~~ | **DONE (N1).** **Resume** restarts `error`/`canceled` jobs (re-probe + resume from `.part`); **Details...** explains the failure. |
| ~~P0.5~~ | ~~**Show error details on hover / dialog**~~ | ~~S~~ | **DONE (N1).** **Details...** shows the full untruncated error, URL, destination, size, progress and limit. |
| P0.6 | **Separate console build** (`FreeDM-cli.exe`) | S | Build a second exe with `--console` so CLI users get live progress. Reuse `freedm/main.py`. |
| P0.7 | **Fix stale `build\` churn** | S | Add `build\`, `__pycache__\`, `dist\` to a `.gitignore` if version-controlled. |
| P0.8 | **App icon** | S | Add `icon.ico`; pass `--icon` in `build.ps1`. |

---

## Priority 1 — Core UX

| # | Item | Effort | Notes |
|---|---|---|---|
| ~~P1.1~~ | ~~**Download queue with concurrency limit**~~ | ~~M~~ | **DONE (W4).** `freedm/scheduler.py`: active/connection/per-host caps, FIFO, Start Now/reorder, 429/503 backoff. |
| ~~P1.2~~ | ~~**Categories** (Video / Music / Documents / Archives / Programs)~~ | ~~M~~ | **DONE (N5).** `freedm/categories.py`; editable rules, **Sort into category folders** toggle, `Other` fallback. |
| ~~P1.3~~ | ~~**Batch add** (paste many URLs)~~ | ~~M~~ | **DONE (N2).** `batch.parse_urls`; the URL box adds every pasted http(s) line, reports invalid entries, skips duplicates. |
| P1.4 | **Drag-and-drop URLs** | M | Tkinter needs `tkinterdnd2` (free) or a native hook. |
| ~~P1.5~~ | ~~**Clipboard monitor** ("grab URL from clipboard")~~ | ~~S~~ | **DONE (N2).** Opt-in **Watch clipboard** toggle (`clipboard_monitor`, off by default); offers a copied link with confirmation via `batch.find_url`. |
| P1.6 | **Dark theme / theme switch** | S | `ttk` theme + custom styles. |
| P1.7 | **System tray + notifications** | M | `pystray` + `plyer` (both free). |
| P1.8 | **Progress bar column** (real bar, not text %) | S | Custom `ttk` cell or `Canvas` overlay. |

---

## Priority 2 — Scheduler & automation

| # | Item | Effort | Notes |
|---|---|---|---|
| ~~P2.1~~ | ~~**Scheduled start** ("start at 02:00")~~ | ~~M~~ | **DONE (N6).** **Schedule...** dialog; a job waits in the `scheduled` state, persisted in the DB. |
| ~~P2.2~~ | ~~**Start/stop batch windows**~~ | ~~M~~ | **DONE (N6).** A daily window (may wrap past midnight) in the filter bar; nothing starts outside it. |
| ~~P2.3~~ | ~~**Shutdown / sleep when queue done**~~ | ~~S~~ | **DONE (N6).** **Shut down when done** — confirmation-guarded, only when the queue is really empty. |
| ~~P2.4~~ | ~~**Auto-resume on app start**~~ | ~~M~~ | **DONE (W3).** Unfinished jobs reload from SQLite and resume; toggle in the GUI (`auto_resume`). |

---

## Priority 3 — Persistence & history

| # | Item | Effort | Notes |
|---|---|---|---|
| ~~P3.1~~ | ~~**SQLite history + queue**~~ | ~~M~~ | **DONE (W3).** `freedm/store.py`: `downloads`, `segments`, `settings`; survives restarts. Search/filter (P3.2) still open. |
| ~~P3.2~~ | ~~**Search / filter history**~~ | ~~S~~ | **DONE (N5).** Search box + status filter; rows are hidden live without reloading. |
| ~~P3.3~~ | ~~**Export / import URL list**~~ | ~~S~~ | **DONE (N5).** **Export...**/**Import...**; JSON keeps every field, plain URL lists also import. |
| ~~P3.4~~ | ~~**Open-file-location history actions**~~ | ~~S~~ | **DONE (N5).** **Show in Folder** reveals the file in Explorer; **Open File** falls back to the folder. |

---

## Priority 4 — Browser integration (biggest UX win, most plumbing)

| # | Item | Effort | Notes |
|---|---|---|---|
| ~~P4.1~~ | ~~**Chrome/Edge extension** (Manifest V3)~~ | ~~M~~ | **DONE (W1).** `extension/`: intercepts new downloads, forwards URL/cookies/referer/UA, cancels the browser copy, resumes it when FreeDM is closed. |
| ~~P4.2~~ | ~~**Firefox extension**~~ | ~~M~~ | **DONE (N8).** The same source with a Firefox manifest (background page, gecko id); **Export for Firefox...** in the Browser dialog. |
| ~~P4.3~~ | ~~**Native messaging host**~~ | ~~M~~ | **DONE (N8).** `FreeDM.exe --native-host`; register it from the Browser dialog so the extension can start the app. |
| ~~P4.4~~ | ~~**Local control server**~~ | ~~S~~ | **DONE (W1).** `freedm/control_server.py`: loopback-only `GET /ping` + token-protected `POST /add`. |
| ~~P4.5~~ | ~~**"Download with FreeDM" context menu**~~ | ~~S~~ | **DONE (N8).** Right-click a link, a video or a page to hand it to FreeDM. |
| ~~P4.6~~ | ~~**Forward cookies / referer / user-agent**~~ | ~~M~~ | **DONE (W2 engine + W1 wiring).** The extension now supplies cookies/referer/UA on every handoff. |

---

## Priority 5 — Engine upgrades

| # | Item | Effort | Notes |
|---|---|---|---|
| ~~P5.1~~ | ~~**Dynamic segmentation** (IDM-style)~~ | ~~M~~ | **DONE (N4).** Work queue: workers take the largest pending piece and split it, so a slow pipe holds back less. |
| ~~P5.2~~ | ~~**Adaptive piece sizing**~~ | ~~S~~ | **DONE (N4).** Piece target (1–8 MB) follows the *slowest* recent connection. |
| ~~P5.3~~ | ~~**Checksum verification** (SHA-256/MD5)~~ | ~~S~~ | **DONE (N3).** `freedm/verify.py`; `Download(checksum=…)`, GUI **Checksum...**, mismatch fails the job and shows both digests. |
| ~~P5.4~~ | ~~**Mirror / multi-source downloads**~~ | ~~M~~ | **DONE (N7).** Mirrors are tried in turn by the probe and the download; the file comes from whichever source answers. |
| ~~P5.5~~ | ~~**Proxy support** (HTTP/SOCKS, auth)~~ | ~~M~~ | **DONE (N7).** Shared proxy configuration with credentials, a bypass list and a connection check in the GUI. |
| P5.6 | **Cookie jar / login support** | M | Import from browser or manual. |
| P5.7 | **FTP support** | L | Different protocol; `ftplib`, no Range semantics. |
| ~~P5.8~~ | ~~**IPv6 / Happy Eyeballs tuning**~~ | ~~S~~ | **DONE (N7).** The resolver can prefer IPv4 or IPv6 when a host has both. |
| P5.9 | **Bandwidth scheduler** (different limits by time) | M | Depends on `RateLimiter`. |
| ~~P5.10~~ | ~~**Verify size after assembly**~~ | ~~S~~ | **DONE (N3).** `_check_complete` + `verify_size`; a short download is never reported as done. |

---

## Priority 6 — Streaming / media (large, separate subsystem)

| # | Item | Effort | Notes |
|---|---|---|---|
| P6.1 | **HLS (m3u8) downloader** | L | Parse playlist, fetch segments, concatenate/remux. |
| P6.2 | **DASH (mpd) downloader** | L | More complex; needs manifest parsing. |
| P6.3 | **Media sniffing from page URL** | L | Requires a mini browser or extension. |
| P6.4 | **FFmpeg integration** (optional) | M | Remux/convert; FFmpeg is free but adds a large dependency — make it optional. |

---

## Priority 7 — Packaging, distribution, quality

| # | Item | Effort | Notes |
|---|---|---|---|
| P7.1 | **Installer** (Inno Setup / NSIS — both free) | M | Start-menu shortcut, uninstaller. |
| P7.2 | **Portable vs installed modes** | S | Keep the single-exe portable build too. |
| P7.3 | **Code signing** | S | Requires a certificate (costs money) — optional, not required for function. |
| P7.4 | **Auto-update check** | M | Check a version JSON; must stay opt-in. |
| P7.5 | **Automated test suite** (`pytest`) | M | Encode the existing manual checks: segmented hash, pause/resume, crash resume, fallback, rate limit. |
| P7.6 | **CI build** (GitHub Actions, free for public repos) | S | Build + run tests on push. |
| P7.7 | **Cross-platform packaging** | L | PyInstaller per-OS; engine already cross-platform. |
| P7.8 | **Logging to file** (opt-in) | S | Rotating log for bug reports. |

---

## Technical debt / known rough edges

1. **Windowed exe loses CLI output.** `sys.stdout` is `None`; `_emit` guards it,
   but users get no progress. Fix via P0.6 (separate console build) or by
   attaching to the parent console with `ctypes`.
2. ~~**No collision policy** on final rename (P0.1).~~ **Fixed in W5**
   (rename/overwrite/cancel/callback).
3. ~~**State files persist on failure** by design (for resume) but are never
   garbage-collected if the user gives up.~~ **Fixed in N3** — the GUI
   **Clean Up...** dialog deletes abandoned `.part`/`.part.state.json` files
   older than a chosen age.
4. ~~**No global cross-download speed limit.** `RateLimiter` is per-download
   (now settable live, N1); a shared limiter object would be a small change.~~
   **Fixed in N4** — one token bucket shared by every download
   (`set_global_speed_limit`), with a **Global Limit...** button.
5. ~~**Segments are fixed at start** (P5.1 addresses this).~~ **Fixed in N4**
   — the work queue re-divides the pending pieces as workers finish.
6. ~~**In-memory only:** closing the app loses the queue.~~ **Fixed in W3**
   (SQLite queue + auto-resume); manual ordering/caps remain (W4).
7. **No `.gitignore`** in the copied project.
8. ~~**GUI error text is truncated** to 40 characters in the status column.~~
   **Fixed in N1** — the **Details...** dialog shows the full text; the column
   keeps a short preview by design.

---

## Suggested next milestone

**Current: see `MILESTONE_2.md`.** Goals N1–N10 are already sequenced there;
N1 is done and N2 (batch input & clipboard) is next. The old short list was:

1. ~~P0.1 overwrite/rename policy~~ (done, W5)
2. ~~P0.2 settings persistence~~ (done, N1)
3. ~~P0.3 per-download speed limit in the GUI~~ (done, N1)
4. P0.6 separate console build
5. ~~P1.1 queue with concurrency limit~~ (done, W4)
6. ~~P3.1 SQLite history + queue~~ (done, W3)
7. ~~P4.4 local control server, then P4.1 browser extension~~ (done, W1)
8. P5.1 dynamic segmentation
9. P7.5 pytest suite

---

## Explicit non-goals (keep the tool simple and free)

- No account system, no cloud service, no telemetry.
- No paid APIs or paid code-signing requirement for core use.
- No bundled adware or "download accelerator" upsells.
- No browser hijacking: integration must always be opt-in and reversible.
