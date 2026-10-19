// Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
const DEFAULTS = { enabled: true, port: 6801, token: "" };

const $ = (id) => document.getElementById(id);

async function load() {
  const cfg = await chrome.storage.sync.get(DEFAULTS);
  $("enabled").checked = cfg.enabled !== false;
  $("port").value = cfg.port || 6801;
  $("token").value = cfg.token || "";
}

async function save() {
  const cfg = {
    enabled: $("enabled").checked,
    port: parseInt($("port").value, 10) || 6801,
    token: $("token").value.trim(),
  };
  await chrome.storage.sync.set(cfg);
  $("status").textContent = "Saved.";
  $("status").style.color = "#0a7a2f";
}

async function test() {
  const port = parseInt($("port").value, 10) || 6801;
  const token = $("token").value.trim();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 2000);
  try {
    const r = await fetch(`http://127.0.0.1:${port}/ping`, {
      signal: ctrl.signal,
      cache: "no-store",
    });
    const body = await r.json();
    if (body && body.app === "FreeDM") {
      $("status").textContent = `Connected to FreeDM on port ${port}` +
        (token ? "." : " - now paste the token and Save.");
      $("status").style.color = "#0a7a2f";
    } else {
      $("status").textContent = "Reached a server, but it is not FreeDM.";
      $("status").style.color = "#a15c00";
    }
  } catch (e) {
    $("status").textContent = "FreeDM is not reachable. Is the app running?";
    $("status").style.color = "#b00020";
  } finally {
    clearTimeout(timer);
  }
}

$("save").addEventListener("click", save);
$("test").addEventListener("click", test);
load();
