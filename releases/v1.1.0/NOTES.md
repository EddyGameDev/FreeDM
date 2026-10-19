# FreeDM v1.1.0 (archived build)

Published: 2026-10-19

Scheduled starts, a daily window, shut-down when done.

- File: `FreeDM-1.1.0.exe`
- SHA-256: `f0794d81cdd00928f988cbc6d610e13f48accc17ee3f8d2262d7a0c3e2af0d4c`
- Verify with: `certutil -hashfile FreeDM-1.1.0.exe SHA256`
- Source: <https://github.com/EddyGameDev/FreeDM>

## Security notice

> **This build is superseded - do not use it.**
>
> It was published before the security fixes of **v1.2.1** and still has
> them. See `docs/SECURITY.md` for the findings:
>
> - the browser extension kept the control token in `chrome.storage.sync`, so it
>   was uploaded to the Google account and to other signed-in browsers;
> - the control server answered with `Access-Control-Allow-Origin: *`, so
>   any web page could read it;
> - the control server did not check the `Host` header (DNS rebinding);
> - a `Cookie:` header set by hand was dropped on every redirect;
> - opening a downloaded executable ran it without asking.
>
> **Use the latest release instead.**
