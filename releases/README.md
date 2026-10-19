# Archived builds

These are the **older builds** that were published before the security fixes
of **v1.2.1**. They are kept here for the record and for anyone who needs to
reproduce an old behaviour.

> **Do not use them.** They still contain the issues listed in
> [`../docs/SECURITY.md`](../docs/SECURITY.md) - most importantly the browser
> extension kept the control token in `chrome.storage.sync`, and the control
> server answered any web page with `Access-Control-Allow-Origin: *`.
>
> **Always use the latest release:** <https://github.com/EddyGameDev/FreeDM/releases>

| Build | Published | SHA-256 | Superseded by |
|---|---|---|---|
| [`v1.0.0/FreeDM-1.0.0.exe`](v1.0.0) | 2026-10-19 | `b39709840de48ea16dd307d60ea195e56e5da6541352280cc2ecdcf8a1439fef` | v1.2.1 (security) |
| [`v1.1.0/FreeDM-1.1.0.exe`](v1.1.0) | 2026-10-19 | `f0794d81cdd00928f988cbc6d610e13f48accc17ee3f8d2262d7a0c3e2af0d4c` | v1.2.1 (security) |
| [`v1.2.0/FreeDM-1.2.0.exe`](v1.2.0) | 2026-10-19 | `b03f15c8d9c0f2b2092ce56b69506540b9dc7f659a3565e5d9446a2573cb99b5` | v1.2.1 (security) |

Each folder has a `NOTES.md` with what that build added and the security notice.

Verify a build before running it:

```
certutil -hashfile FreeDM-1.0.0.exe SHA256
```

The same binaries are published on the
[release page](https://github.com/EddyGameDev/FreeDM/releases) - this folder
is the local copy.
