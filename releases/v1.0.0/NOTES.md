# FreeDM v1.0.0 (archived build)

Published: 2026-10-19

First public build.

- File: `FreeDM-1.0.0.exe`
- SHA-256: `b39709840de48ea16dd307d60ea195e56e5da6541352280cc2ecdcf8a1439fef`
- Verify with: `certutil -hashfile FreeDM-1.0.0.exe SHA256`
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
