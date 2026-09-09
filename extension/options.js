const healthEl = document.getElementById("health");
const logEl = document.getElementById("logPath");
const portEl = document.getElementById("port");
const lanStatus = document.getElementById("lanStatus");

async function refreshHealth() {
  const res = await chrome.runtime.sendMessage({ type: "plexvlc.health" });
  if (res && res.ok) {
    healthEl.className = "ok";
    healthEl.textContent = "Helper " + res.version + " listening on " + res.listen + " (player: " + res.player + ")";
    logEl.textContent = res.logPath || "—";
    if (res.helperPort) portEl.value = String(res.helperPort);
    const openEl = document.getElementById("openLabel");
    if (openEl && res.player) openEl.textContent = "Open in " + res.player;
  } else {
    healthEl.className = "err";
    healthEl.textContent = "Helper is not running. It starts with Plex after login; or run helper\\scripts\\start.ps1.";
  }
}

document.getElementById("savePort").addEventListener("click", async () => {
  const n = parseInt(portEl.value, 10);
  if (!n || n < 1 || n > 65535) return;
  await chrome.storage.local.set({ helperPort: n });
  await refreshHealth();
});

document.getElementById("saveToken").addEventListener("click", async () => {
  const token = document.getElementById("plexToken").value.trim();
  const tokenStatus = document.getElementById("tokenStatus");
  if (token.length < 8) {
    tokenStatus.className = "err";
    tokenStatus.textContent = "Token looks too short.";
    return;
  }
  await chrome.storage.session.set({ fallbackToken: token });
  tokenStatus.className = "ok";
  tokenStatus.textContent = "Session token saved (until the browser closes).";
});

document.getElementById("grantLan").addEventListener("click", async () => {
  let origin = document.getElementById("lanOrigin").value.trim().replace(/\/$/, "");
  if (!origin) {
    lanStatus.className = "err";
    lanStatus.textContent = "Enter an origin.";
    return;
  }
  try {
    origin = new URL(origin).origin;
  } catch {
    lanStatus.className = "err";
    lanStatus.textContent = "Not a valid URL.";
    return;
  }
  const granted = await chrome.permissions.request({ origins: [origin + "/*"] });
  if (!granted) {
    lanStatus.className = "err";
    lanStatus.textContent = "Permission was not granted.";
    return;
  }
  const res = await chrome.runtime.sendMessage({ type: "plexvlc.registerLan", origin });
  lanStatus.className = res && res.ok ? "ok" : "err";
  lanStatus.textContent = res && res.ok ? "Granted. Reload the Plex tab once." : (res && res.error) || "Failed";
});

chrome.storage.local.get({ helperPort: 18765 }, (st) => {
  portEl.value = String(st.helperPort || 18765);
});
refreshHealth();
