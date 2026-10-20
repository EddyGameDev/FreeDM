# FreeDM — Milestone 3: Harden, then polish

**Status:** planned 2026-10-20 · Milestone 2 (N1–N10) is **complete** ·
Companion to [`MILESTONE_2.md`](MILESTONE_2.md) (the N1–N10 record),
[`REVIEW.md`](REVIEW.md) (the review this plan comes from) and
[`ROADMAP.md`](ROADMAP.md) (the long-term backlog).

Milestone 2 made FreeDM capable. Milestone 3 makes it **safe to keep
changing**: a second security pass over the code that was written after the
first review, release metadata that matches the product, and the two very
large files broken into pieces that can be worked on.

Each goal below is small enough to finish in one sitting and has a plain
acceptance test.

## Progress log

| Date | Goal | Result |
|---|---|---|
| 2026-10-20 | **G1 — Security round two** | **DONE.** The seven modules added after N6 are reviewed and documented (S10–S14 in `docs/SECURITY.md`). A playlist can no longer carry the user's `Authorization` header to another host, may only name `http(s)` URLs, and may not reach a private address unless the user allows it. The native host now names the extension that may call it. Category folder names are sanitised. 40 new tests. |
| next | G2 — Release polish | Not started |
| next | G3 — Split the two large modules | Not started |
| next | G4 — Streams in the interface | Not started |
| next | G5 — Everyday interface polish | Not started |
| next | G6 — Schedule and accounts | Not started |
| later | G7 — Distribution polish | Not started |
| later | FTP (P5.7) | Deferred — a different protocol, its own project |

---

## G1 — Security round two ✅ DONE

**Why:** [`REVIEW.md`](REVIEW.md) finding **R1**. The first review covered
N1–N6. Seven modules have been added since — `network.py`,
`native_host.py`, `update.py`, `logsetup.py`, `stream.py`, `aes.py` and
`categories.py` — and they are unreviewed. `stream.py` is the sharpest edge:
a playlist is data from a server, and FreeDM fetches whatever it names.

**What to build:**
- Review the seven new modules and add the missing sections to
  `docs/SECURITY.md` (proxy credentials, the native host, the update check,
  the log file, streaming, the AES code, the category rules).
- **Decide and document the streaming boundary.** A playlist may only point
  at `http(s)`; anything else (a `file://` URL, a local address) is refused
  or clearly reported, and the rule is enforced in one place and tested.
- **Tighten the native host** (finding **R2**): write the manifest with the
  extension's *actual* ID when it is known, keep the wildcard only as the
  fallback for an unpacked extension, and say so in the manifest itself.
- Check the remaining new surfaces: the update check only ever reads the
  project's own `VERSION.json`; the log file never holds URLs, file names,
  cookies or tokens; the proxy password is the only secret on disk.
- Add the new findings to `tests/test_security.py` so they cannot come back.

**What was found and fixed** (the numbers are the findings in
`docs/SECURITY.md`):
- **S10 (High)** — a playlist could send the user's `Authorization` header to
  any host it named, and could point FreeDM at the local network. Now the
  user's headers only go to the playlist's own host, only `http(s)` URLs are
  allowed, and a private address is refused unless the user ticks
  *"Allow segments from private addresses"*.
- **S11 (Medium)** — the native host accepted a call from any installed
  extension. The extension now reports its id and the manifest names it.
- **S12 (Medium)** — a category name was used as a folder name
  unsanitised, so a rule could have pointed a download outside the chosen
  folder. It is sanitised now.
- **S13 (Low)** — a proxy URL that already had credentials in it was
  mangled.
- **S14 (Low)** — the update check could be pointed at any URL; it is fixed
  to the project's own file now.

**Acceptance criteria:** all met.
- Every module in `freedm/` is covered by a section of `docs/SECURITY.md`. ✅
- A playlist that names a `file://` or a non-http(s) URL is refused, and the
  test says so. ✅
- The native host manifest names the extension it belongs to, or explains
  why it cannot. ✅
- `docs/SECURITY.md` is dated after the last code change it reviewed. ✅

**Tests:** `tests/test_security2.py` — 40/40 pass.

---

## G2 — Release polish

**Why:** findings **R3**, **R5** and **R6**. A published application should
answer `--version`, and the repository should describe what it actually is.

**What to build:**
- `FreeDM.exe --version` (and `--help` without a URL) prints the version, the
  licence and where the settings live. The CLI should not demand a URL
  before it can say anything.
- The **update check** compares against that same version, so there is one
  source of truth.
- Update the repository description, add **topics** (`download-manager`,
  `hls`, `dash`, `python`, `tkinter`, `windows`, …) and put a **CI badge**
  in the README.
- Keep the **extension's version** in step with the app, and add a test like
  the one that already guards the app, `VERSION.json` and the installer.
- Remove the dead `check_updates` setting.
- Fix the stale bits found in the review: the ROADMAP's *"Suggested next
  milestone"* section, technical-debt item 7, and the `security.md` heading
  in `FILE_MAP.md`.

**Acceptance criteria:**
- `FreeDM.exe --version` prints the version without complaining.
- The repository description and topics mention streaming and the console
  build; the README shows the CI status.
- The extension version cannot drift from the app version unnoticed.
- No setting in `settings.py` is written but never read.

---

## G3 — Split the two large modules

**Why:** finding **R4**. `gui.py` is 1502 lines in one class and `engine.py`
is 1618. Every feature since N1 has made them bigger, and a change to
either touches a file nobody wants to open.

**What to build:**
- `gui.py` → a `freedm/gui/` package: the window and toolbar, the job list,
  and one module per dialog group (headers/network, categories/schedule,
  cleanup/about).
- `engine.py` → a `freedm/engine/` package: the download engine, the piece
  work queue, the streaming path, and the verification.
- Keep every public name importable from the same place, so nothing outside
  has to change.

**Acceptance criteria:**
- No file in the project is longer than about 700 lines.
- The public API (`Download`, `Snapshot`, the settings) is unchanged:
  the existing tests import it unchanged and keep passing.
- The 384 tests still pass, with no test edited to make the split work.

---

## G4 — Streams in the interface

**Why:** finding **R7**. A stream is not a file, and the interface does not
say so. Downloading 37 segments looks like a very slow download of one file.

**What to build:**
- The list and the **Details...** dialog show that a job is a stream: how
  many segments it has, whether it is encrypted, and how long it is.
- The output file name is the real one (`show.ts`), not the playlist's.
- A **"Re-fetch the playlist"** action for a live stream that keeps
  growing.

**Acceptance criteria:**
- A stream job is visibly marked as a stream, with its segment count.
- Its name and size are right in the list.

---

## G5 — Everyday interface polish

**Why:** the roadmap items people actually notice (P1.4, P1.6, P1.7, P1.8).

**What to build:**
- A **real progress bar** in the list (a `Canvas` cell), not just a
  percentage (P1.8).
- **Drag and drop** of links onto the window (P1.4) — `tkinterdnd2` is free
  and optional: without it the feature is simply not offered.
- A **dark theme** switch (P1.6), following the system setting by default.
- A **system tray** icon with a notification when a download finishes
  (P1.7) — `pystray` is free and optional.

**Acceptance criteria:**
- The progress bar matches the percentage.
- Dropping a link adds it.
- The dark theme can be switched on and off, and the choice is remembered.
- A finished download can raise a notification, and the tray icon can be
  turned off.

---

## G6 — Schedule and accounts

**Why:** the roadmap's P5.9 and P5.6.

**What to build:**
- A **time-of-day bandwidth schedule**: a different speed limit (or no
  limit) per hour, so a download can use the whole line at night and a
  little in the day (P5.9). It reuses the window machinery from N6.
- A **cookie and login interface** (P5.6): a small cookie editor for a job
  (the API can already take cookies; today only the browser extension
  supplies them), and a place to paste a login URL that is replayed.

**Acceptance criteria:**
- A schedule can be set and it overrides the plain speed limit in the hours
  it covers.
- Cookies can be edited for a job and are used on the next attempt.

---

## G7 — Distribution polish

**Why:** the roadmap's P7.2, P7.3 and P7.7.

**What to build:**
- **Portable versus installed mode** (P7.2): the installed build can put
  itself on the Start menu and register the native host; the portable one
  never writes outside `%APPDATA%\FreeDM`.
- **Code signing** (P7.3): the steps and the cost, and what a *signed*
  release looks like. Signing needs a certificate, which costs money, so
  this goal is documentation plus a script — not a purchase.
- **Cross-platform packaging** (P7.7): what it would take to ship a Linux
  and a macOS build. The engine is already cross-platform; the GUI uses
  `os.startfile` and Windows paths in places, which is the work.

**Acceptance criteria:**
- The installed build can register the native host and the portable one
  cannot.
- The signing and cross-platform notes are written down, with the known
  blockers.

---

## Deferred

- **FTP** (P5.7) — a different protocol with no `Range` semantics. It is a
  project of its own, not a line item here.
- **FFmpeg remuxing** (P6.4) — needs an external tool. The stream is
  written as it comes, which plays fine; a single MP4 would need FFmpeg
  installed. Worth doing only if real users ask for it.

---

## Definition of done (Milestone 3)

- Every goal's acceptance criteria pass, and `docs/SECURITY.md` covers every
  module in `freedm/`.
- `python -m pytest` is green, and the CI is green on all three systems.
- `docs/REVIEW.md`'s findings R1–R7 are closed or deliberately accepted
  (with the reason written down).
- The documentation is updated as each goal lands, and
  `CHANGELOG.md` gets a section for the next release.
