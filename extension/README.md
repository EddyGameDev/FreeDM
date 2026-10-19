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

## Files

| File | Purpose |
|---|---|
| `manifest.json` | MV3 permissions: `downloads`, `cookies`, `storage`, `webRequest` |
| `background.js` | the handoff logic (pause → ping → POST `/add` → cancel or resume) |
| `options.html` / `options.js` | port + token settings and a connection test |
