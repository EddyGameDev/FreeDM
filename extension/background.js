// Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
// FreeDM Browser Handoff - MV3 service worker.
//
// For every browser download: pause it, ask FreeDM (127.0.0.1) to take it
// over, and only cancel the browser copy once FreeDM has accepted the job.
// If FreeDM is not running the download is simply resumed, so the browser
// behaves normally.

const DEFAULTS = { enabled: true, port: 6801, token: "" };

async function getConfig() {
  const stored = await chrome.storage.sync.get(DEFAULTS);
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
