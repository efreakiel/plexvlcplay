const DEFAULT_PORT = 18765;

const USER_ERRORS = {
  helper_unreachable: "plexvlc helper is not running. It starts with Plex after login; or run helper\\scripts\\start.ps1.",
  unauthorized: "This is not the installed plexvlc extension (frozen ID), or the helper rejected the request.",
  bad_pair_code: "Wrong or expired pairing code. Run the helper in a console for a new code.",
  forbidden_origin: "Load the official unpacked plexvlc extension (frozen ID).",
  bad_request: "Cannot detect a movie or episode on this page.",
  unsupported_discover: "Plex Discover titles cannot be opened; use your library.",
  ssrf_blocked: "Refusing to contact that server address.",
  plex_unreachable: "Plex Media Server is not responding.",
  plex_unauthorized: "Plex token expired. Refresh Plex Web.",
  plex_tls_failed: "Set Plex Secure connections to Preferred, or use LAN HTTP.",
  not_found: "Plex could not find that item.",
  unsupported_type: "Open a movie or episode, not that library type.",
  no_media: "This item has no playable file.",
  no_playable_part: "File is missing and no stream URL is available.",
  player_not_found: "Install VLC or set player.executable in config.json.",
  player_launch_failed: "Failed to start the player.",
  no_token: "No Plex token found. Refresh Plex Web or paste a token in plexvlc Options.",
};

function helperOrigin(port) {
  return "http://127.0.0.1:" + (port || DEFAULT_PORT);
}

function openLabel(name) {
  const n = String(name || "VLC").trim() || "VLC";
  return "Open in " + n;
}

async function applyPlayerName(name) {
  const n = String(name || "VLC").trim().slice(0, 64) || "VLC";
  await chrome.storage.local.set({ playerName: n });
  try {
    await chrome.action.setTitle({ title: openLabel(n) });
  } catch {
    /* ignore */
  }
  try {
    await chrome.contextMenus.update("plexvlc-open", { title: openLabel(n) });
  } catch {
    /* menu may not exist yet */
  }
  return n;
}

async function settings() {
  const st = await chrome.storage.local.get({
    helperSecret: "",
    helperPort: DEFAULT_PORT,
    playerName: "VLC",
  });
  let fallbackToken = "";
  try {
    const sess = await chrome.storage.session.get({ fallbackToken: "" });
    fallbackToken = sess.fallbackToken || "";
  } catch {
    fallbackToken = "";
  }
  return { ...st, fallbackToken };
}

async function helperFetch(path, { method = "GET", body = null, secret = true } = {}) {
  const st = await settings();
  const url = helperOrigin(st.helperPort) + path;
  const headers = { Accept: "application/json" };
  if (body) headers["Content-Type"] = "application/json";
  if (secret && st.helperSecret) headers["X-PlexVLC-Secret"] = st.helperSecret;
  try {
    const resp = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await resp.text();
    let data = {};
    try {
      data = JSON.parse(text);
    } catch {
      data = { ok: false, error: "helper_unreachable" };
    }
    return { http: resp.status, data };
  } catch {
    return { http: 0, data: { ok: false, error: "helper_unreachable" } };
  }
}

function toastMessage(data) {
  if (!data || !data.ok) {
    const err = (data && data.error) || "helper_unreachable";
    return USER_ERRORS[err] || err;
  }
  const title = data.title || "item";
  const player = (data.player || "VLC").trim() || "VLC";
  if (data.mode === "file") return "Opened " + title + " from disk";
  if (data.mode === "url") return "Streaming " + title + " from Plex (token on " + player + " command line)";
  return "Opened in " + player;
}

async function launchItem(item) {
  if (!item || !item.ratingKey) {
    return { ok: false, error: "bad_request", message: USER_ERRORS.bad_request };
  }
  const st = await settings();
  const token = item.plexToken || st.fallbackToken;
  if (!token) {
    return { ok: false, error: "bad_request", message: USER_ERRORS.no_token || "No Plex token." };
  }
  const body = {
    ratingKey: String(item.ratingKey),
    plexToken: token,
  };
  if (item.pmsBaseUrl) body.pmsBaseUrl = item.pmsBaseUrl;
  if (item.machineIdentifier) body.machineIdentifier = item.machineIdentifier;
  if (item.mediaId) body.mediaId = item.mediaId;
  if (item.partId) body.partId = item.partId;
  if (item.offsetMs != null) body.offsetMs = item.offsetMs;
  if (item.titleHint) body.titleHint = item.titleHint;
  const { data } = await helperFetch("/v1/launch", { method: "POST", body, secret: true });
  if (data && data.player) await applyPlayerName(data.player);
  const message = toastMessage(data);
  return {
    ok: !!data.ok,
    mode: data.mode,
    title: data.title,
    pathHint: data.pathHint,
    player: data.player,
    message,
    error: data.error,
  };
}

async function health() {
  const { data } = await helperFetch("/v1/health", { secret: false });
  const st = await settings();
  if (data && data.ok && data.player) await applyPlayerName(data.player);
  return {
    ok: !!data.ok,
    version: data.version,
    player: data.player || st.playerName,
    logPath: data.logPath,
    listen: data.listen,
    helperPort: st.helperPort,
    error: data.ok ? undefined : data.error || "helper_unreachable",
  };
}

async function pair(code) {
  const st = await settings();
  const url = helperOrigin(st.helperPort) + "/v1/pair";
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ code }),
    });
    const data = await resp.json();
    if (data && data.ok && data.secret) {
      await chrome.storage.local.set({
        helperSecret: data.secret,
        helperPort: data.port || st.helperPort,
      });
      return { ok: true, helperPort: data.port || st.helperPort };
    }
    return { ok: false, error: data.error || "bad_pair_code" };
  } catch {
    return { ok: false, error: "helper_unreachable" };
  }
}

async function registerLan(origin) {
  if (!origin || !/^https?:\/\//i.test(origin)) {
    return { ok: false, error: "bad_request" };
  }
  const originClean = origin.replace(/\/$/, "");
  try {
    await chrome.scripting.registerContentScripts([
      {
        id: "plexvlc-lan-" + originClean,
        matches: [originClean + "/web/*"],
        js: ["content.js"],
        css: ["content.css"],
        runAt: "document_idle",
        persistAcrossSessions: true,
      },
      {
        id: "plexvlc-lan-hook-" + originClean,
        matches: [originClean + "/web/*"],
        js: ["page-hook.js"],
        runAt: "document_start",
        world: "MAIN",
        persistAcrossSessions: true,
      },
    ]);
  } catch (err) {
    if (!String(err).includes("Duplicate")) {
      return { ok: false, error: String(err) };
    }
  }
  const granted = await chrome.storage.local.get({ allowedLanOrigins: [] });
  const list = new Set(granted.allowedLanOrigins || []);
  list.add(originClean);
  await chrome.storage.local.set({ allowedLanOrigins: [...list] });
  return { ok: true };
}

async function restoreLanScripts() {
  const st = await chrome.storage.local.get({ allowedLanOrigins: [] });
  for (const origin of st.allowedLanOrigins || []) {
    await registerLan(origin);
  }
}

function createContextMenu(title) {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "plexvlc-open",
      title: title || "Open in VLC",
      contexts: ["page"],
      documentUrlPatterns: [
        "https://app.plex.tv/*",
        "http://127.0.0.1/web/*",
        "http://localhost/web/*",
        "https://*.plex.direct/*",
      ],
    });
  });
}

chrome.runtime.onInstalled.addListener(async () => {
  const st = await settings();
  createContextMenu(openLabel(st.playerName));
  restoreLanScripts();
  health();
});

chrome.runtime.onStartup.addListener(() => {
  restoreLanScripts();
  health();
});

async function detectOnTab(tabId) {
  try {
    return await chrome.tabs.sendMessage(tabId, { type: "plexvlc.detect" });
  } catch {
    return { item: null, error: "no_receiver" };
  }
}

async function launchActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || tab.id == null) {
    return { ok: false, error: "bad_request", message: USER_ERRORS.bad_request };
  }
  const det = await detectOnTab(tab.id);
  if (!det || !det.item) {
    return { ok: false, error: det && det.error, message: USER_ERRORS[det && det.error] || USER_ERRORS.bad_request };
  }
  return launchItem(det.item);
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "plexvlc-open" || !tab || tab.id == null) return;
  const det = await detectOnTab(tab.id);
  if (det && det.item) await launchItem(det.item);
});

chrome.commands.onCommand.addListener(async (command) => {
  if (command === "open-in-player") await launchActiveTab();
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || !msg.type) return;
  if (msg.type === "plexvlc.launch") {
    launchItem(msg.item).then((r) => sendResponse({ type: "plexvlc.launchResult", ...r }));
    return true;
  }
  if (msg.type === "plexvlc.health") {
    health().then((r) => sendResponse({ type: "plexvlc.healthResult", ...r }));
    return true;
  }
  if (msg.type === "plexvlc.pair") {
    pair(msg.code).then((r) => sendResponse({ type: "plexvlc.pairResult", ...r }));
    return true;
  }
  if (msg.type === "plexvlc.registerLan") {
    registerLan(msg.origin).then(sendResponse);
    return true;
  }
});
