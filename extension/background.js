// Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
// FreeDM Browser Handoff - MV3 service worker.
//
// For every browser download: pause it, ask FreeDM (127.0.0.1) to take it
// over, and only cancel the browser copy once FreeDM has accepted the job.
// If FreeDM is not running the download is simply resumed, so the browser
// behaves normally.

const DEFAULTS = { enabled: true, port: 6801, token: "" };

// The token authorises queuing downloads in FreeDM, so it stays on this
// device: `storage.local` is never synced to the user's Google account or to
// another browser. `storage.sync` would leak it.
const AREA = chrome.storage.local;

async function getConfig() {
  const stored = await AREA.get(DEFAULTS);
  return { ...DEFAULTS, ...stored };
}

function base(cfg) {
  return `http://127.0.0.1:${cfg.port}`;
}

async function ping(cfg) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 1500);
  try {
    const r = await fetch(`${base(cfg)}/ping`, {
      signal: ctrl.signal,
      cache: "no-store",
    });
    return r.ok;
  } catch (e) {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function cookiesFor(url) {
  try {
    const cookies = await chrome.cookies.getAll({ url });
    return cookies.map((c) => ({
      name: c.name,
      value: c.value,
      domain: c.domain,
      path: c.path,
    }));
  } catch (e) {
    return [];
  }
}

async function resume(id) {
  try {
    await chrome.downloads.resume(id);
  } catch (e) {
    /* already finished or not pausable */
  }
}

async function handleCreated(item) {
  if (!item || !/^https?:/i.test(item.url || "")) return;
  if (item.byExtensionId) return;                 // never intercept ourselves
  if (item.incognito) return;                     // keep private downloads private

  const cfg = await getConfig();
  if (!cfg.enabled || !cfg.token) return;

  // Pause first so a fast download cannot complete while we negotiate.
  try {
    await chrome.downloads.pause(item.id);
  } catch (e) {
    /* not pausable yet; continue anyway */
  }

  if (!(await ping(cfg))) {
    await resume(item.id);                        // FreeDM closed -> normal download
    return;
  }

  const cookies = await cookiesFor(item.url);
  let filename;
  try {
    filename = item.filename ? item.filename.split(/[\\/]/).pop() : undefined;
  } catch (e) {
    filename = undefined;
  }

  const body = {
    url: item.url,
    cookies,
    referer: item.referrer || item.initiator || undefined,
    user_agent: navigator.userAgent,
    filename: filename || undefined,
    headers: {},
  };

  let accepted = false;
  try {
    const r = await fetch(`${base(cfg)}/add`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${cfg.token}`,
      },
      body: JSON.stringify(body),
    });
    accepted = r.ok;
  } catch (e) {
    accepted = false;
  }

  if (accepted) {
    try {
      await chrome.downloads.cancel(item.id);
    } catch (e) {
      /* ignore */
    }
    try {
      await chrome.downloads.erase({ id: item.id });
    } catch (e) {
      /* ignore */
    }
  } else {
    await resume(item.id);
  }
}

chrome.downloads.onCreated.addListener((item) => {
  handleCreated(item).catch((e) => console.error("FreeDM handoff:", e));
});

// --- "Download with FreeDM" context menu (N8) ---------------------------
// The link, media or page URL is handed to FreeDM the same way a browser
// download is. Nothing is queued without the token, and the menu only
// appears when the extension is enabled.
const MENU_ID = "freedm-download-with-freedm";

function menuTarget(info) {
  if (!info) return "";
  if (info.linkUrl) return info.linkUrl;
  if (info.mediaSrcUrl) return info.mediaSrcUrl;
  if (info.srcUrl) return info.srcUrl;
  if (info.pageUrl) return info.pageUrl;
  return "";
}

async function handleMenuClick(info) {
  const url = menuTarget(info);
  if (!url || !/^https?:/i.test(url)) return;

  const cfg = await getConfig();
  if (!cfg.enabled || !cfg.token) return;

  // Make sure the app is running: ask the native host to start it, then
  // give it a moment to answer.
  if (!(await ping(cfg))) {
    try {
      await chrome.runtime.sendNativeMessage("org.freedm.app", {
        action: "launch",
      });
    } catch (e) {
      /* no native host installed: the browser keeps the download */
    }
    for (let i = 0; i < 20; i += 1) {
      await new Promise((r) => setTimeout(r, 500));
      if (await ping(cfg)) break;
    }
  }

  const body = {
    url,
    cookies: await cookiesFor(url),
    referer: info.pageUrl || undefined,
    user_agent: navigator.userAgent,
    filename: undefined,
    headers: {},
  };

  try {
    const r = await fetch(`${base(cfg)}/add`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${cfg.token}`,
      },
      body: JSON.stringify(body),
    });
    if (!r.ok) console.error("FreeDM refused the request:", r.status);
  } catch (e) {
    console.error("FreeDM handoff failed:", e);
  }
}

function createMenu() {
  const api = chrome.contextMenus || chrome.menus;
  if (!api) return;
  try {
    api.removeAll(() => {
      api.create({
        id: MENU_ID,
        title: "Download with FreeDM",
        contexts: ["link", "video", "audio", "image", "page"],
      });
    });
  } catch (e) {
    console.error("FreeDM menu:", e);
  }
}

const menuApi = chrome.contextMenus || chrome.menus;
if (menuApi && menuApi.onClicked) {
  menuApi.onClicked.addListener((info) => {
    handleMenuClick(info).catch((e) => console.error("FreeDM menu:", e));
  });
  createMenu();
}
