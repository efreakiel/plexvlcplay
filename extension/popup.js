const statusEl = document.getElementById("status");
const actionsEl = document.getElementById("actions");

function setStatus(text, cls) {
  statusEl.className = cls || "muted";
  statusEl.textContent = text;
}

function addButton(label, cls, onClick) {
  const b = document.createElement("button");
  b.textContent = label;
  if (cls) b.className = cls;
  b.addEventListener("click", onClick);
  actionsEl.appendChild(b);
  return b;
}

async function currentTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function isPlexUrl(url) {
  if (!url) return false;
  try {
    const u = new URL(url);
    if (u.hostname === "app.plex.tv") return true;
    if (u.hostname.endsWith(".plex.direct")) return true;
    if ((u.hostname === "127.0.0.1" || u.hostname === "localhost") && u.pathname.includes("/web")) return true;
    if (u.port === "32400" || u.pathname.includes("/web")) return true;
    return false;
  } catch {
    return false;
  }
}

async function grantOrigin(tab) {
  const origin = new URL(tab.url).origin;
  const granted = await chrome.permissions.request({ origins: [origin + "/*"] });
  if (!granted) {
    setStatus("Permission was not granted.", "err");
    return;
  }
  await chrome.runtime.sendMessage({ type: "plexvlc.registerLan", origin });
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
  } catch {
    /* MAIN-world hook still needs a reload */
  }
  setStatus("Origin allowed. Reload the Plex tab once, then try again.", "ok");
  actionsEl.replaceChildren();
}

async function init() {
  const tab = await currentTab();
  if (!tab) {
    setStatus("No active tab.", "err");
    return;
  }
  if (!tab.url || !isPlexUrl(tab.url)) {
    setStatus("This tab is not a Plex page, or plexvlc has no permission for this origin.", "err");
    if (tab.url && tab.id != null) {
      addButton("Allow this origin", "secondary", () => grantOrigin(tab));
    }
    return;
  }

  let det;
  try {
    det = await chrome.tabs.sendMessage(tab.id, { type: "plexvlc.detect" });
  } catch {
    det = null;
  }
  if (!det) {
    setStatus("This tab is not a Plex page, or plexvlc has no permission for this origin.", "err");
    addButton("Allow this origin", "secondary", () => grantOrigin(tab));
    return;
  }
  if (!det.item) {
    setStatus(
      det.error === "unsupported_discover"
        ? "Plex Discover titles cannot be opened; use your library."
        : det.error === "no_token"
          ? "No Plex token on this page. Refresh Plex Web."
          : "Cannot detect a movie or episode on this page.",
      "err"
    );
    return;
  }

  const hint = det.item.titleHint || ("ratingKey " + det.item.ratingKey);
  setStatus(hint);
  const btn = addButton("Open in VLC");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    const res = await chrome.runtime.sendMessage({ type: "plexvlc.launch", item: det.item });
    if (res && res.ok) {
      const extra = res.pathHint ? "\n" + res.pathHint : "";
      setStatus((res.message || "Opened") + extra, "ok");
    } else {
      setStatus((res && res.message) || "Launch failed", "err");
    }
    btn.disabled = false;
  });
}

init();
