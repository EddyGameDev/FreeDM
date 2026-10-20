# FreeDM — Project Review

Reviewed: 2026-10-20, after Milestone 2 (N1–N10). This is a **review of the
whole project**: what works, what is missing, and what should be done next.
The plan that follows from it is in [`MILESTONE_3.md`](MILESTONE_3.md).

---

## 1. The state of the project

| | |
|---|---|
| Version | 1.5.0 (app, `VERSION.json` and the installer are kept in step by a test) |
| Tests | **384** pass locally (`python -m pytest`) |
| CI | Green: Windows, Ubuntu and macOS test jobs + a Windows build job that compiles the installer, installs it and runs the *installed* app |
| Releases | 8 published (v1.0.0 → v1.5.0); every asset was downloaded back and hash-checked |
| Licence | PolyForm Noncommercial 1.0.0; `LICENSE` is byte-identical to the official text |
| Docs | 0 broken internal links; `CHANGELOG.md` is the source of the release notes |
| Dependencies | `requests` only at runtime (the AES-128 is our own) |

### What is genuinely finished

- **The engine**: segmented downloads with a dynamic work queue, crash-safe
  resume, validators, retries, overwrite policy, disk-space check, size and
  checksum verification, mirrors, proxies, IPv4/IPv6 preference.
- **The app**: persistent queue, categories, filtering, scheduling, a daily
  window, shut-down-when-done, a log file, an update check, streaming media.
- **The browser side**: Chrome/Edge and Firefox extensions, a right-click
  menu, a native messaging host, a token-protected loopback server.
- **The packaging**: a windowed and a console build, an icon, an installer
  script, CI, a changelog-driven release process.

---

## 2. Findings

Ordered by how much they matter.

### R1 — The security review is one milestone behind (high)

`docs/SECURITY.md` was written for N1–N6. **Seven modules have been added
since and were never reviewed**: `network.py` (proxy credentials),
`native_host.py` (registry writes, process spawning, a native-messaging
manifest), `update.py` (a network fetch), `logsetup.py` (a file write),
`stream.py` (fetches URLs that come from a playlist), `aes.py` and
`categories.py`.

`stream.py` is the interesting one: a playlist is data from the server, and
FreeDM fetches whatever it names. A malicious playlist can therefore point
FreeDM at any `http(s)` address — including one on the local network. That
is inherent to "download what the playlist says", but it deserves an
explicit decision, a documented limit and a test, not silence.

### R2 — The native host accepts any extension (medium)

`native_host.build_manifest()` writes
`"allowed_origins": ["chrome-extension://*", "moz-extension://*"]`, so **any
browser extension on the machine can call the host** — and the host can
launch FreeDM. The wildcard is the only practical option for an unpacked
extension (its ID changes per install), but it should be a deliberate,
documented choice, and the manifest should be written per installation with
the *actual* extension ID when it is known.

### R3 — No `--version` (medium)

`FreeDM.exe --version` fails with *"the following arguments are required:
url"*. For a published application that is an obvious gap, and it is exactly
what the update check compares against.

### R4 — `gui.py` and `engine.py` are very large (medium)

`gui.py` is **1502 lines** in one class and `engine.py` is **1618**. Every
new feature has made them bigger. The 384 tests make a split verifiable, but
until then, every change touches two files that nobody wants to open.

### R5 — The release metadata is thin (low)

- The repository description does not mention streaming or the console build.
- There are **no topics**, so the project is hard to find.
- There is **no CI badge** in the README.
- The extension's manifest version is still `1.0.0` while the app is `1.5.0`,
  and nothing keeps the two in step (unlike the app, the installer and
  `VERSION.json`, which do have such a test).

### R6 — Dead and stale bits (low)

- `check_updates` is declared and persisted but **never read** — the update
  check is (correctly) always user-triggered, so the setting is pointless.
- The ROADMAP's *"Suggested next milestone"* section still says *"N2 is next"*
  and lists P0.6, P5.1 and P7.5 as open, all of which are done.
- The ROADMAP's technical-debt item 7 still says *"No `.gitignore` in the
  copied project"*. There is one.
- `docs/FILE_MAP.md` has a heading `` ### `security.md` `` — the file is
  `SECURITY.md` (case).

### R7 — Streaming has no presence in the interface (low)

A stream downloads like any other file. The list and the **Details...**
dialog say nothing about *"this is a stream of 37 segments"*, and the
extension's own files are not part of the detail view.

### R8 — The remaining roadmap items (informational)

Still open: drag-and-drop (P1.4), dark theme (P1.6), system tray and
notifications (P1.7), a real progress bar (P1.8), a cookie/login interface
(P5.6), a time-of-day bandwidth schedule (P5.9), FFmpeg remuxing (P6.4),
portable-vs-installed modes (P7.2), code signing (P7.3) and cross-platform
packaging (P7.7). FTP (P5.7) is a different protocol and stays a project of
its own.

---

## 3. What is *not* wrong

Checked and found sound, so they do not need to be revisited:

- The token is 256-bit and compared in constant time; the control server is
  loopback-only, checks the `Host` header and grants CORS only to extension
  origins.
- The token stays in `chrome.storage.local`; the extension asks for no
  permission it does not use.
- The file name from a server cannot escape the destination folder.
- A hand-written `Cookie:` header lives in the jar, so it is host-scoped and
  survives a redirect.
- The SQL is fully parameterised; the queue database and the token live in
  the per-user `%APPDATA%`.
- The AES-128 implementation matches the FIPS-197 vector and a reference
  implementation.
- `requests` already strips `Authorization` and pops `Cookie` on a redirect.
- The build is reproducible from the committed sources, and every published
  artefact is hash-checked.

---

## 4. The recommendation

The project has stopped needing features and started needing **maintenance**:
a second security pass over the new code, a smaller `gui.py`/`engine.py`, and
release metadata that matches what the app actually does.

That is what [`MILESTONE_3.md`](MILESTONE_3.md) is for: G1 (security round
two) and G2 (release polish) first, then G3 (split the two large modules),
and only then the remaining interface work.

The features that are still open (drag-and-drop, dark theme, tray, progress
bars) are nice, but none of them fixes a problem a user has today. The
security gap and the two enormous files are the ones that will cost
something later.
