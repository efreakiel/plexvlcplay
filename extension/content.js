/* parsePlexLocation must match tests/hashutil.py */

function parsePlexLocation(href) {
  let url;
  try {
    url = new URL(href);
  } catch {
    return { error: "bad_key" };
  }
  let hash = url.hash || "";
  if (hash.startsWith("#")) hash = hash.slice(1);
  if (hash.startsWith("!")) hash = hash.slice(1);
  const qIndex = hash.indexOf("?");
  let path;
  let query;
  if (qIndex === -1) {
    path = hash;
    query = "";
  } else {
    path = hash.slice(0, qIndex);
    query = hash.slice(qIndex + 1);
  }
  const params = new URLSearchParams(query);
  const keyRaw = params.get("key");
  if (!keyRaw) return { error: "no_key" };
  let key;
  try {
    key = decodeURIComponent(keyRaw);
  } catch {
    key = keyRaw;
  }
  const local = key.match(/^\/library\/metadata\/([0-9]+)$/);
  let ratingKey;
  if (local) {
    ratingKey = local[1];
  } else if (/^\/library\/metadata\/([0-9a-f]{20,})$/i.test(key)) {
    return { error: "unsupported_discover" };
  } else {
    return { error: "bad_key" };
  }
  const result = { ratingKey };
  const mm = path.match(/\/(?:server|media)\/([^/]+)\//);
  if (mm) result.machineIdentifier = mm[1];
  else if (params.get("server")) result.machineIdentifier = params.get("server");
  return result;
}

const intercepted = {
  ratingKey: null,
  pmsBaseUrl: null,
  plexToken: null,
};

function pmsOriginScore(origin) {
  try {
    const u = new URL(origin);
    const host = (u.hostname || "").toLowerCase();
    if (host === "app.plex.tv" || host.endsWith(".plex.tv") || host.endsWith(".plex.services")) {
      return 0;
    }
    if (host.endsWith(".plex.direct")) return 4;
    if (host === "127.0.0.1" || host === "localhost" || host === "::1") return 4;
    if (u.port === "32400") return 3;
    return 2;
  } catch {
    return 0;
  }
}

window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  if (event.origin !== location.origin) return;
  if (!event.data || event.data.source !== "plexvlc-page-hook") return;
  if (event.data.kind === "pms-request") {
    intercepted.ratingKey = event.data.ratingKey || intercepted.ratingKey;
    const next = event.data.pmsBaseUrl;
    if (next && pmsOriginScore(next) >= pmsOriginScore(intercepted.pmsBaseUrl || "")) {
      intercepted.pmsBaseUrl = next;
    }
    if (event.data.plexToken) intercepted.plexToken = event.data.plexToken;
  }
});

function sessionToken() {
  try {
    return localStorage.getItem("myPlexAccessToken") || "";
  } catch {
    return "";
  }
}

function detectItem() {
  const parsed = parsePlexLocation(location.href);
  const token = intercepted.plexToken || sessionToken();
  if (parsed.error === "unsupported_discover") {
    return { item: null, error: "unsupported_discover" };
  }
  let ratingKey = null;
  let machineIdentifier = parsed.machineIdentifier || null;
  if (parsed.ratingKey) {
    ratingKey = parsed.ratingKey;
  } else if (intercepted.ratingKey) {
    ratingKey = intercepted.ratingKey;
  } else {
    return { item: null, error: parsed.error || "no_key" };
  }
  if (!token) return { item: null, error: "no_token" };
  let pmsBaseUrl = intercepted.pmsBaseUrl;
  if (!pmsBaseUrl && location.port === "32400") pmsBaseUrl = location.origin;
  if (pmsBaseUrl && pmsOriginScore(pmsBaseUrl) === 0) pmsBaseUrl = null;
  return {
    item: {
      ratingKey: String(ratingKey),
      machineIdentifier,
      pmsBaseUrl,
      plexToken: token,
      titleHint: document.title || "",
      mediaId: null,
      partId: null,
      offsetMs: null,
    },
  };
}

function toast(text, kind) {
  let el = document.getElementById("plexvlc-toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "plexvlc-toast";
    document.documentElement.appendChild(el);
  }
  el.className = "plexvlc-toast plexvlc-toast-" + (kind || "info");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    el.hidden = true;
  }, 5000);
}

function launchItem(item) {
  chrome.runtime.sendMessage({ type: "plexvlc.launch", item }, (res) => {
    if (chrome.runtime.lastError) {
      toast("plexvlc extension error: " + chrome.runtime.lastError.message, "error");
      return;
    }
    if (!res || !res.ok) {
      const err = (res && res.error) || "helper_unreachable";
      if (err === "helper_unreachable") {
        toast("plexvlc helper is not running. It starts with Plex after login; or run helper\\scripts\\start.ps1.", "error");
      } else {
        toast(res && res.message ? res.message : "Could not open in VLC (" + err + ")", "error");
      }
      return;
    }
    toast(res.message || "Opened in VLC", "ok");
  });
}

function playerLabel(cb) {
  chrome.storage.local.get({ playerName: "VLC" }, (st) => cb(st.playerName || "VLC"));
}

function injectButton() {
  const parsed = parsePlexLocation(location.href);
  if (!parsed.ratingKey) return;
  if (document.getElementById("plexvlc-open-btn")) return;
  const nodes = document.querySelectorAll("button, a");
  let play = null;
  for (const n of nodes) {
    const label = (n.getAttribute("aria-label") || n.textContent || "").trim();
    if (/^play$/i.test(label) || /^watch$/i.test(label)) {
      play = n;
      break;
    }
  }
  if (!play || !play.parentElement) return;
  playerLabel((name) => {
    if (document.getElementById("plexvlc-open-btn")) return;
    const btn = document.createElement("button");
    btn.id = "plexvlc-open-btn";
    btn.type = "button";
    btn.className = "plexvlc-open";
    btn.textContent = "Open in " + name;
    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const det = detectItem();
      if (!det.item) {
        toast(userError(det.error), "error");
        return;
      }
      launchItem(det.item);
    });
    play.parentElement.insertBefore(btn, play.nextSibling);
  });
}

function userError(code) {
  switch (code) {
    case "unsupported_discover":
      return "Plex Discover titles cannot be opened; use your library.";
    case "no_token":
      return "No Plex token found. Refresh Plex Web or paste a token in plexvlc Options.";
    case "no_key":
      return "Cannot detect a movie or episode on this page.";
    default:
      return "Cannot detect a movie or episode on this page.";
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || !msg.type) return;
  if (msg.type === "plexvlc.detect") {
    const det = detectItem();
    sendResponse({ type: "plexvlc.detectResult", item: det.item || null, error: det.error });
  }
});

injectButton();
setInterval(injectButton, 1000);
window.addEventListener("hashchange", injectButton);
window.addEventListener("popstate", injectButton);
const obs = new MutationObserver(() => injectButton());
obs.observe(document.body || document.documentElement, { childList: true, subtree: true });
setTimeout(() => {}, 500);
