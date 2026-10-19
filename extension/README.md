# FreeDM Browser Handoff (Chrome / Edge)

An unpacked Manifest V3 extension that sends browser downloads to the FreeDM
desktop app, cancelling the browser's copy so nothing is downloaded twice.

## Install (one time)

1. Open FreeDM, click **Browser...**, then **Export extension**.
   That copies this folder to `%APPDATA%\FreeDM\extension` and opens it.
2. In Chrome/Edge go to `chrome://extensions` (or `edge://extensions`),
   enable **Developer mode**, click **Load unpacked**, and pick that folder.
3. Open the extension's **Options**, paste the token shown in FreeDM's
   **Browser...** dialog, and click **Save**.

## Behaviour

- Enabled + FreeDM running: a new download is paused, handed to FreeDM
  (URL, cookies, referer, user-agent, filename), then cancelled in the browser.
- FreeDM closed: the download is resumed and the browser handles it normally.
- FreeDM running but the token is wrong: the POST is rejected and the browser
  download continues.

## Security notes

- The token is stored in `chrome.storage.local`, **not** in `chrome.storage.sync`:
  it stays on this device and is never uploaded to the Google account or to
  another browser. After re-installing the extension, paste the token again.
- The extension only asks for the permissions it uses: `downloads` (to cancel
  the browser's copy), `cookies` (to hand over the session) and `storage` (for
  the settings). The control server only answers requests whose `Host` is
  loopback, and only an extension origin gets CORS permission - an ordinary
  web page cannot talk to it.
- `host_permissions` includes `<all_urls>` because the `cookies` API can only
  read a site's cookies when the extension has permission for that site.

## Files

| File | Purpose |
|---|---|
| `manifest.json` | MV3 permissions: `downloads`, `cookies`, `storage` |
| `background.js` | the handoff logic (pause → ping → POST `/add` → cancel or resume) |
| `options.html` / `options.js` | port + token settings and a connection test |
