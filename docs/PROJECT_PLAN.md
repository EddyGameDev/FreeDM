# Free Download Manager (IDM-style) — Project Plan

**Goal:** Build a 100% free, open-source download manager with Internet Download Manager (IDM) core features: multi-threaded segmented downloads, resume after interruption, browser integration, scheduler, speed limiting, and queue management — with $0 cost (no licensing, no paid APIs).

---

## 1. Why this is feasible for $0

IDM's speed comes from well-understood, unpatented techniques, not proprietary magic:

- **HTTP Range requests** (`Range: bytes=X-Y`) let N threads download different byte ranges of the same file concurrently, then stitch them together.
- **Connection reuse / keep-alive** avoids repeated TLS/TCP handshakes.
- **Resume support** is just tracking per-segment byte offsets and re-requesting from where each left off (servers return `206 Partial Content`).
- **Browser integration** is a small browser extension that intercepts download links and POSTs them to a local manager over HTTP/WebSocket.

All of these are implementable with free, standard libraries.

## 2. Target feature set (MVP → v1 → v2)

| Feature | MVP | v1 | v2 |
|---|---:|---:|---:|
| Single-file HTTP/HTTPS download | ✅ | ✅ | ✅ |
| Multi-threaded segmented download (HTTP Range) | ✅ | ✅ | ✅ |
| Pause / resume / cancel | ✅ | ✅ | ✅ |
| Resume after app restart / crash | ❌ | ✅ | ✅ |
| Fallback to single-stream when Range unsupported | ✅ | ✅ | ✅ |
| CLI + GUI (Tkinter or web UI) | CLI | GUI | GUI |
| Per-download & global bandwidth limit | ❌ | ✅ | ✅ |
| Persistent download history & queue (SQLite) | ❌ | ✅ | ✅ |
| Scheduler (start at time, shutdown when done) | ❌ | ✅ | ✅ |
| Browser extension (Chrome/Edge/Firefox) to "take over" downloads | ❌ | ✅ | ✅ |
| Proxy support (HTTP/SOCKS, optional auth) | ❌ | ❌ | ✅ |
| FTP support | ❌ | ❌ | ✅ |
| Video/streaming link detector (grabber) | ❌ | ❌ | ✅ |
| Dynamic segmentation (rebalance segments mid-download like IDM) | ❌ | ❌ | ✅ |
| Checksum verification (SHA-1/SHA-256) | ❌ | ❌ | ✅ |

## 3. Recommended tech stack

| Layer | Choice | Reason |
|---|---|---|
| Language | **Python 3.10+** | Fast to build, great HTTP libs, cross-platform, Tkinter built-in for GUI |
| HTTP client | `requests` / `httpx` | Range headers, streaming, keep-alive, proxies |
| Concurrency | `concurrent.futures.ThreadPoolExecutor` | One worker per segment; GIL is not an issue for I/O-bound downloads |
| Persistence | **SQLite** | Zero-install, serverless, stores queue/history/segment state |
| GUI | **Tkinter** (built-in) or **pywebview** + HTML/JS | Tkinter needs no install; pywebview gives a modern browser UI |
| Browser extension | Vanilla JS + manifest v3 | Chrome/Edge/Firefox compatible; talks to local Python host |
| Packaging | PyInstaller / Nuitka | Single `.exe` for Windows users |
| Testing | `pytest` + local threaded HTTP test server | Test resume, retries, range fallback without internet |

## 4. Core architecture

```
+----------------+      +-------------------+      +------------------+
|   Browser Ext  |<---> | Local Host (Py)   |<---> | Download Engine  |
+----------------+      | (Native Messaging)|      |                  |
                        +-------------------+      +------------------+
                                              |   Queue (SQLite)   |
                                              |   Segment State    |
                                              |   Speed/ETA calc   |
                                              +------------------+
```

### Download Engine (the heart)
1. **Probe** the URL with `HEAD` (or `Range: bytes=0-0` GET) to get `Content-Length` and whether `Accept-Ranges: bytes` is supported.
2. **If ranges supported:** split file into N segments; launch one thread per segment; each thread issues `Range: bytes=start-end` and writes to its offset in a shared temp file (`.part`).
3. **If not supported:** single-thread `iter_content` stream to temp file.
4. **Track progress** per segment (bytes done, speed, ETA); save state to SQLite every few seconds so a crash/restart can resume.
5. **On completion:** rename `.part` → final filename; optionally verify checksum.
6. **On pause/cancel:** stop threads, keep `.part`, mark state paused in DB.
7. **On resume:** read `.part` offsets, request remaining ranges only.

### Retry policy
- Exponential backoff (1s, 2s, 4s, 8s…), max 5 retries per segment.
- If one segment keeps failing, fall back to single-stream for that segment rather than failing the whole download.

### Dynamic segmentation (v2, IDM-style)
- Start with fewer segments; as connections finish, split the largest remaining segment in half and assign it to a free connection. Keeps all connections busy on uneven servers.

## 5. File layout (suggested)

```
downloader/
├── engine/            # download core (segment worker, range probe, resume)
├── storage/           # SQLite schema + DAOs (queue, history, segment state)
├── cli/               # command-line interface (argparse/click)
├── gui/               # Tkinter or webview window (queue, history, settings)
├── ext/               # browser extension (manifest, content script, background)
├── host/              # native messaging host bridging ext ↔ Python engine
├── tests/             # pytest suite + local test HTTP server
├── requirements.txt
├── main.py            # entry point
└── README.md
```

## 6. Development roadmap (suggested order)

**Phase 1 — Engine core (2–3 days)**
- Range-probe + single-stream download
- Multi-threaded segmented download with `.part` temp file
- Pause/resume/cancel, progress callback

**Phase 2 — Persistence & CLI (2 days)**
- SQLite schema (downloads, segments, history)
- Save/load resume state across restarts
- CLI: `dlm add <url>`, `dlm list`, `dlm pause <id>`, `dlm resume <id>`

**Phase 3 — GUI (2–3 days)**
- Tkinter window: active queue, history, pause/resume buttons, speed/ETA display
- Global speed limit slider

**Phase 4 — Browser integration (2–3 days)**
- Chrome/Edge/Firefox extension that captures download URLs
- Native messaging host to forward URLs to the Python manager
- "Download with FreeDM" context menu

**Phase 5 — Scheduler & polish (2–3 days)**
- Schedule downloads by time
- Shutdown computer when queue completes
- Checksum verify, categories, bandwidth limiter

**Phase 6 — Package & release (1 day)**
- PyInstaller one-file `.exe`
- GitHub release + install instructions

## 7. Known limitations to document up front (so users aren't surprised)

- **Some sites block Range requests** → falls back to single-thread (no speed boost).
- **Cloudflare/anti-bot protection** may require cookies/User-Agent; the extension can forward browser cookies.
- **Streaming video (HLS/DASH)** isn't a single file — needs a separate stream grabber (v2).
- **Speed gain depends on server:** a single slow server won't get faster just because you open more connections.

## 8. Existing open-source references you can study (free, no copying required)

- `lianzz-downloader` / `fastdownloader` (PyPI) — Python segmented downloader with Tkinter GUI, resume, rate limiting.
- `simple-download-manager` (GitHub) — Python IDM/XDM-style manager with SQLite history, browser UI, Tkinter option.
- `hyperfetch` / `pget` (Rust) — CLI segmented downloaders with resume and state persistence.
- `ranget` (Go) — multi-threaded downloader with proxy support and MCP mode.

These show the same approach works and are good reference implementations, not code to copy unless their licenses allow it.

---

**Bottom line:** You can build a fully free IDM alternative with Python + SQLite + a browser extension, costing $0 in software licenses. The hard part isn't the money — it's the resume state machine and the browser extension native-host plumbing. Start with Phase 1 (the engine) and prove segmented resume works before adding GUI/extension.
