# FreeDM — Security Review

Reviewed: **2026-10-19** (round one, the code up to N6) and **2026-10-20**
(round two, the modules added since - see §7). The findings and the fixes are
below. This is a working document, not a one-off: new findings go here.

Every finding is pinned by a test, so it cannot come back unnoticed.

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
| **S10** | **High** | **A playlist could send the user's `Authorization` header to any host, and could point FreeDM at the local network** | **Fixed (round two)** |
| **S11** | Medium | **The native host accepted a call from *any* installed extension** | **Fixed (round two)** |
| **S12** | Medium | **A category name was used as a folder name without sanitising** | **Fixed (round two)** |
| **S13** | Low | **A proxy URL that already had credentials in it was mangled** | **Fixed (round two)** |
| **S14** | Low | The update check could be pointed at any URL | **Fixed (round two)** |

---

## 2. Round one — what was checked, and what it showed

### 2.1 The loopback control server (`freedm/control_server.py`)

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

### 2.3 The download engine (`freedm/engine.py`)

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

### 2.4 The GUI (`freedm/gui.py`)

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

### 2.5 The queue database (`freedm/store.py`) and the packaging

| Check | Result |
|---|---|
| SQL injection | **Good** — every statement uses bound parameters |
| Database location | **Good** — `%APPDATA%\FreeDM\freedm.db`, per user |
| Token file | **Good** — created atomically, per user; read only by that account |
| Dependency licences | **Good** — all permissive (Apache-2.0 / MIT / BSD-3 / MPL-2.0); PyInstaller is a build tool only |
| The `dist/` build | **Good** — the published SHA-256 is in the release notes |

### 2.6 Not covered in round one

- The threat model assumes a **single-user, non-shared** Windows account. On
  a shared account the plain-text token, proxy password and queue database are
  readable by the other users of that account.
- No audit log: there is no record of who queued which download.
- The app does not verify TLS certificates out of the box — it does, but the
  API allows turning it off, and the GUI does not expose that switch.

**Round one did not cover the modules added afterwards** (the network
options, the native host, the update check, the log file, streaming, the AES
code and the category rules). They are reviewed in §3.

## 3. Round two — the modules added after N6 (2026-10-20)

The first review covered the code up to N6. Seven modules were added after it
and had never been looked at: `network.py`, `native_host.py`, `update.py`,
`logsetup.py`, `stream.py`, `aes.py` and `categories.py`. They are reviewed
here.

### 3.1 The streaming path (`freedm/stream.py`, the engine's stream branch)

A playlist is **data from a third party**: the user chooses the playlist's
address, but the playlist decides where the *segments* come from. That is a
trust boundary, and two things could go wrong.

**S10 (High) — the user's own headers followed the playlist to any host.**
The engine sent `self._session_headers()` — which includes any `Authorization`
or `Referer` the user set — to *every* segment URL. A hostile playlist could
therefore point one segment at a host the user never chose, and FreeDM would
hand that host the user's `Authorization` header. It could also point
FreeDM at an address on the user's own network (a router, a NAS, the app's own
control server) and make it fetch it.

**Fixed** in two parts:
- **The user's headers only go to the playlist's own host.** A segment on any
  other host is fetched without them (`_stream_headers`). The session's own
  default headers (the user agent) still go everywhere, which is harmless.
- **A URL policy for the playlist** (`check_segment_url`): only `http` and
  `https` are allowed (a `file://` or `ftp://` URL is refused with a clear
  message), and a segment on a **private address** (loopback, link-local,
  `10/8`, `172.16/12`, `192.168/16`, or a name that resolves to one) is
  refused unless the user has ticked *"Allow segments from private
  addresses"*. The playlist's own host is always fine — the user chose it.
  A name is resolved once and the answer cached, so a host that points at the
  local network is caught too.

### 3.2 The native messaging host (`freedm/native_host.py`)

The host is started by the browser and can do exactly one thing: start
FreeDM.

| Check | Result |
|---|---|
| What it can do | Only `ping` and `launch` — it never touches the queue |
| The message format | The browser's own (a length-prefixed JSON) |
| **Who may call it** | **S11 — fixed** |

**S11 (Medium) — any installed extension could call the host.** The manifest
listed `chrome-extension://*` and `moz-extension://*`, so *every* extension on
the machine could start FreeDM. The wildcard is the only option for an
unpacked extension (its id is different on every install), but it should be a
choice, not an accident.

**Fixed:** the extension now sends `chrome.runtime.id` with every handoff,
FreeDM remembers it, and the manifest is then written with **that extension
only**. The wildcard remains as the fallback, and the manifest carries a
`_note` saying so - so anyone reading the file can see that the host is
open until the extension has talked to FreeDM once.

### 3.3 The update check (`freedm/update.py`)

| Check | Result |
|---|---|
| When it runs | **Only** when the user presses the button |
| What it fetches | The project's own `VERSION.json` |
| What it sends | Nothing about the user - one plain GET |

**S14 (Low) — the URL was a parameter.** `check_for_update(current, url=...)`
accepted any URL, so a mistake (or a bad call) could have pointed it anywhere.
**Fixed:** the URL is fixed to the project's own file; the function no longer
takes one.

### 3.4 The log file (`freedm/logsetup.py`)

| Check | Result |
|---|---|
| Is it on by default | **No** — the user ticks the box in the **About** dialog |
| Where does it go | `%APPDATA%\FreeDM\freedm.log` (per user) |
| How big does it get | 2 MB, then it rotates; three old files are kept |
| What does it hold | The app's own events - **never** URLs, file names, cookies or tokens (a test checks the source) |

### 3.5 The proxy (`freedm/network.py`)

| Check | Result |
|---|---|
| Where the password lives | The settings database, in plain text (S9) - documented |
| Is the password ever shown | **No** - `summary()` leaves it out, and a test checks it |
| Is the proxy URL ever logged | **No** |
| **Does the URL survive a password in it** | **S13 — fixed** |

**S13 (Low) — a proxy URL that already had credentials in it was mangled.**
`http://user:pass@proxy:8080` had its `user:pass` thrown away when a user
name was also configured, and the path was rebuilt by hand. **Fixed:** the URL
is parsed properly, any existing userinfo is replaced rather than appended
to, and the path is kept.

### 3.6 The category rules (`freedm/categories.py`)

**S12 (Medium) — a category name was used as a folder name, unsanitised.**
The rules are the user's own, but the name becomes a *folder*, so a rule
called `..\..\Windows\System32` would have placed a download outside the
chosen folder, and a name with `:` or `*` would have broken the download with
a confusing error.

**Fixed:** `safe_folder_name()` replaces the characters that are illegal on
Windows, removes `..` and falls back to `Other`. A test checks that the
destination always stays inside the base folder.

### 3.7 The AES code (`freedm/aes.py`)

| Check | Result |
|---|---|
| Is it correct | **Yes** - it matches the FIPS-197 test vector and a reference implementation (both are in the tests) |
| Does it touch the disk or the network | **No** - it is pure arithmetic |
| Is a wrong answer dangerous | **No** - a wrong decryption produces a file that fails the size/checksum verification, it does not produce a *valid* wrong file by accident |

---

1. The control server must never send `Access-Control-Allow-Origin: *`, and
   must reject a `Host` header that is not loopback.
2. The control token belongs in `chrome.storage.local`, never in `sync`.
3. Do not add a browser permission that the code does not use.
4. Anything that reaches the file system must go through `sanitize_filename`
   (or `categories.safe_folder_name` for a folder name).
5. Secrets belong in the cookie jar, not in raw headers.
6. Executables are never launched without an explicit confirmation.
7. **Data that comes from a server (a playlist, a manifest) must not decide
   where FreeDM connects, and must never carry the user's own headers to a
   host the user did not choose.**
8. A name that becomes a path must be sanitised, and a URL that comes from
   elsewhere must be checked before it is fetched.
9. The native host must name the extension that may call it, or say plainly
   that it does not know yet.
10. A secret (a proxy password, a token) is never written to a log, and
    never shown in full in the interface.
