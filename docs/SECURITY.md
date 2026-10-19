# FreeDM — Security Review

Reviewed: 2026-10-19 · scope: the whole application (engine, GUI, loopback
control server, browser extension, queue database, packaging).

This file lists what was checked, what was found, and what was fixed. It is a
working document, not a one-off: new findings go here.

---

## 1. Summary

| # | Severity | Finding | Status |
|---|---|---|---|
| S1 | **High** | The control token was stored in `chrome.storage.sync` | **Fixed** |
| S2 | Medium | The control server sent `Access-Control-Allow-Origin: *` | **Fixed** |
| S3 | Medium | The control server did not validate the `Host` header (DNS rebinding) | **Fixed** |
| S4 | Low–Med | The extension requested the unused `webRequest` permission | **Fixed** |
| S5 | Low | The control server returned internal error text to the client | **Fixed** |
| S6 | Low | `dest_dir` from the extension payload was not validated | **Fixed** |
| S7 | Low | "Open File" ran a downloaded executable/script without asking | **Fixed** |
| S8 | Low–Med | A `Cookie:` header set by hand was dropped on every redirect | **Fixed** |
| S9 | Info | The proxy password and the token are stored in plain text | Documented |

---

## 2. What was checked, and what it showed

### 2.1 The loopback control server (`control_server.py`)

The most security-sensitive component: it listens on `127.0.0.1` and accepts
requests from the browser extension.

| Check | Result |
|---|---|
| Binds to loopback only | **Good** — `127.0.0.1`, never `0.0.0.0` |
| Token strength | **Good** — `secrets.token_urlsafe(32)` (256 bits) |
| Token comparison | **Good** — `hmac.compare_digest` (constant time) |
| Unauthenticated requests | **Good** — rejected before the body is parsed |
| Request body size | **Good** — capped at 1 MiB |
| SQL injection | **Good** — the queue store uses bound parameters only |
| CORS | **S2 — fixed** |
| `Host` header | **S3 — fixed** |
| Error messages | **S5 — fixed** |
| `dest_dir` from the payload | **S6 — fixed** |

**S1 (High) — the token was in `chrome.storage.sync`.**
`chrome.storage.sync` uploads the value to the user's Google account and to
every browser signed in to it, and it is not end-to-end encrypted. The control
token authorises queueing arbitrary downloads in FreeDM, so it should not
leave the device. **Fixed:** the extension now uses `chrome.storage.local`,
which never leaves the machine.

**S2 (Medium) — `Access-Control-Allow-Origin: *` on every response.**
Any web page the user opened could make cross-origin requests to
`http://127.0.0.1:6801` and read the answers: it could tell whether FreeDM was
running (and which port and version it used), and the endpoint behaved like a
public, cross-origin-reachable service on the machine. **Fixed:** the CORS
headers are now only sent for the extension's own origins
(`chrome-extension://`, `moz-extension://`); an ordinary web page gets no CORS
headers at all, so the browser blocks the response. The extension does not
need CORS — an MV3 service worker with `host_permissions` talks to loopback
directly.

**S3 (Medium) — no `Host` header validation (DNS rebinding).**
A web page could point a hostname it controls at `127.0.0.1` and have the
browser send requests to the local control server with an attacker-chosen
`Host` header. The token still protected `/add`, but a localhost service
should not answer requests addressed to another name. **Fixed:** requests whose
`Host` is not `127.0.0.1`, `localhost` or `[::1]` (with any port) are
rejected with `403`.

**S5 (Low) — internal error text was returned to the client.**
A failure inside the handler produced `{"error": "<python exception>"}`, which
can leak paths and internals to any local process. **Fixed:** the client now
gets a generic message; the detail stays in the app.

**S6 (Low) — `dest_dir` from the payload was used unchecked.**
A payload could point a download at any folder. It required the token, so it
was inside the trusted-extension boundary, but there is no reason to accept a
path that is not a folder. **Fixed:** the value is ignored unless it is an
existing directory.

### 2.2 The browser extension (`extension/`)

| Check | Result |
|---|---|
| Token storage | **S1 — fixed** (`storage.local`, not `storage.sync`) |
| Permissions used | `downloads` (cancel/erase), `cookies` (handoff), `storage` (settings) — all needed |
| Permissions unused | **S4 — fixed** (`webRequest` removed) |
| Script injection in the options page | **Good** — the status text is set with `textContent`, never `innerHTML` |
| Intercepts its own downloads | **Good** — `item.byExtensionId` is ignored |
| Incognito downloads | **Good** — left alone on purpose |
| Redirect target of the handoff | **Good** — the browser's copy is only cancelled after FreeDM accepted the job |

**S4 (Low–Medium) — the `webRequest` permission was requested but never used.**
`webRequest` lets an extension observe and modify every request the browser
makes. The code only uses `chrome.downloads` and `chrome.cookies`. An
unnecessary permission is unnecessary risk. **Fixed:** removed.

`host_permissions` stays `<all_urls>` because the `cookies` API can only read
the cookies of a site the extension has host permission for — that is the
point of the handoff.

### 2.3 The download engine (`engine.py`)

| Check | Result |
|---|---|
| Path traversal through the file name | **Good** — `/` and `\` are replaced, `..` cannot escape the destination (regression tests added) |
| Overwriting an existing file | **Good** — renames by default |
| Atomic state writes | **Good** — `tmp` + `os.replace` |
| TLS verification | **Good** — on by default |
| Credentials on redirect | **Good** — `requests` 2.34 strips `Authorization` on a host change and pops `Cookie` on any redirect |
| Redirects to another protocol | **Good** — `requests` will not follow a redirect to `file://` |
| User-set `Cookie:` header | **S8 — fixed** |

**S8 (Low–Medium) — a hand-written `Cookie:` header was dropped on every
redirect.** The **Headers...** dialog lets the user set `Cookie:` (and the
extension hands over cookies for the browser's session). `requests` removes the
`Cookie` header when it follows a redirect and rebuilds it from the cookie
jar — but a header set by hand is not in the jar, so it was silently lost and
the download could fail with a 401. **Fixed:** a hand-written `Cookie:` header
is now put into the session's cookie jar, so it survives redirects *and* is
scoped to the host it belongs to.

### 2.4 The GUI (`gui.py`)

| Check | Result |
|---|---|
| Shell injection | **Good** — `subprocess` is always called with an argument list, never `shell=True` |
| The power command | **Good** — a fixed list, no user input |
| The proxy password | **S9 — documented** (plain text in the queue database) |
| Opening a downloaded file | **S7 — fixed** |

**S7 (Low) — "Open File" ran executables and scripts without asking.**
A download manager by nature handles dangerous files, but launching one should
not be a single click. **Fixed:** opening a file with an executable or script
extension (`.exe`, `.bat`, `.cmd`, `.com`, `.ps1`, `.vbs`, `.js`, `.jar`,
`.scr`, `.msi`, `.lnk`) asks for confirmation first.

### 2.5 The queue database (`store.py`) and the packaging

| Check | Result |
|---|---|
| SQL injection | **Good** — every statement uses bound parameters |
| Database location | **Good** — `%APPDATA%\FreeDM\freedm.db`, per user |
| Token file | **Good** — created atomically, per user; read only by that account |
| Dependency licences | **Good** — all permissive (Apache-2.0 / MIT / BSD-3 / MPL-2.0); PyInstaller is a build tool only |
| The `dist/` build | **Good** — the published SHA-256 is in the release notes |

### 2.6 Not covered

- The threat model assumes a **single-user, non-shared** Windows account. On
  a shared account the plain-text token, proxy password and queue database are
  readable by the other users of that account.
- No audit log: there is no record of who queued which download.
- The app does not verify TLS certificates out of the box — it does, but the
  API allows turning it off, and the GUI does not expose that switch.

---

## 3. Rules for future changes

1. The control server must never send `Access-Control-Allow-Origin: *`, and
   must reject a `Host` header that is not loopback.
2. The control token belongs in `chrome.storage.local`, never in `sync`.
3. Do not add a browser permission that the code does not use.
4. Anything that reaches the file system must go through `sanitize_filename`.
5. Secrets belong in the cookie jar, not in raw headers.
6. Executables are never launched without an explicit confirmation.
