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

let playerNameCache = "VLC";
chrome.storage.local.get({ playerName: "VLC" }, (st) => {
  playerNameCache = st.playerName || "VLC";
});
if (chrome.storage.onChanged) {
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes.playerName) {
      playerNameCache = changes.playerName.newValue || "VLC";
    }
  });
}

function parseAnyPlexHref(href) {
  if (!href) return {};
  try {
    const abs = new URL(href, location.href).href;
    const parsed = parsePlexLocation(abs);
    if (parsed.ratingKey) return parsed;
  } catch {
    /* ignore */
  }
  const m = String(href).match(/\/library\/metadata\/(\d+)/);
  if (m) return { ratingKey: m[1] };
  return {};
}

function itemFromKey(ratingKey, machineIdentifier, titleHint) {
  const token = intercepted.plexToken || sessionToken();
  if (!ratingKey) return { item: null, error: "no_key" };
  if (!token) return { item: null, error: "no_token" };
  const parsedPage = parsePlexLocation(location.href);
  let pmsBaseUrl = intercepted.pmsBaseUrl;
  if (!pmsBaseUrl && location.port === "32400") pmsBaseUrl = location.origin;
  if (pmsBaseUrl && pmsOriginScore(pmsBaseUrl) === 0) pmsBaseUrl = null;
  return {
    item: {
      ratingKey: String(ratingKey),
      machineIdentifier: machineIdentifier || parsedPage.machineIdentifier || null,
      pmsBaseUrl,
      plexToken: token,
      titleHint: titleHint || "",
      mediaId: null,
      partId: null,
      offsetMs: null,
    },
  };
}

function ratingKeyFromNode(node) {
  let el = node;
  for (let i = 0; i < 14 && el; i++, el = el.parentElement) {
    const hrefs = [];
    if (el.getAttribute) {
      const h = el.getAttribute("href");
      if (h) hrefs.push(h);
    }
    if (el.querySelectorAll) {
      el.querySelectorAll("a[href]").forEach((a) => hrefs.push(a.getAttribute("href")));
    }
    for (const href of hrefs) {
      const parsed = parseAnyPlexHref(href);
      if (parsed.ratingKey) return parsed;
    }
  }
  return null;
}

function titleFromCard(node) {
  const root =
    (node.closest &&
      node.closest('[class*="PosterCard"], [class*="MetadataDetailsRow"], [class*="ListItem"], [class*="MetadataPosterCard"]')) ||
    node.parentElement;
  if (!root) return "";
  const img = root.querySelector && root.querySelector("img[alt]");
  if (img && img.alt && img.alt.trim()) return img.alt.trim().slice(0, 200);
  const t = root.querySelector && root.querySelector('[class*="title"], h2, h3');
  if (t && t.textContent) return t.textContent.trim().slice(0, 200);
  return "";
}

function moreButtonFrom(el) {
  if (!el || !el.closest) return null;
  if (el.closest(".plexvlc-open, .plexvlc-menu-item, #plexvlc-toast")) return null;
  const node = el.closest("button, a, [role='button']") || el;
  const testid = node.getAttribute && (node.getAttribute("data-testid") || "");
  if (/sidebarLibrariesMoreButton/i.test(testid)) return null;
  const label = ((node.getAttribute && (node.getAttribute("aria-label") || node.getAttribute("title"))) || "").trim();
  const cls = node.className ? String(node.className) : "";
  if (/moreButton/i.test(testid)) return node;
  if (/^more actions$/i.test(label) || /^actions$/i.test(label)) return node;
  if (/moreButton/i.test(cls)) return node;
  return null;
}

let pendingMenu = null;

function rememberMenuItem(fromNode) {
  const parsed = ratingKeyFromNode(fromNode);
  if (!parsed || !parsed.ratingKey) return;
  pendingMenu = {
    ratingKey: parsed.ratingKey,
    machineIdentifier: parsed.machineIdentifier || null,
    titleHint: titleFromCard(fromNode),
    at: Date.now(),
  };
}

function pendingStillFresh() {
  return pendingMenu && Date.now() - pendingMenu.at < 15000;
}

function injectMenuItem(menu, name) {
  if (!pendingStillFresh()) return;
  if (menu.querySelector(".plexvlc-menu-item")) return;
  const det = itemFromKey(pendingMenu.ratingKey, pendingMenu.machineIdentifier, pendingMenu.titleHint);
  const sample = menu.querySelector('[class*="MenuItem-menuItem"]');
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = (sample ? sample.className + " " : "") + "plexvlc-menu-item";
  btn.textContent = "Open in " + name;
  btn.addEventListener("click", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    if (!det.item) {
      toast(userError(det.error), "error");
      return;
    }
    launchItem(det.item);
  });
  let play = null;
  menu.querySelectorAll('[class*="MenuItem-menuItem"], button, a').forEach((it) => {
    if (play) return;
    if (/^play$/i.test((it.textContent || "").trim())) play = it;
  });
  if (play && play.parentNode) play.parentNode.insertBefore(btn, play.nextSibling);
  else if (sample && sample.parentNode) sample.parentNode.insertBefore(btn, sample);
  else menu.insertBefore(btn, menu.firstChild);
}

function injectOverlayPlay(name) {
  if (!pendingStillFresh()) return;
  const plays = document.querySelectorAll("button, a");
  for (const n of plays) {
    if (n.id === "plexvlc-open-btn" || n.classList.contains("plexvlc-open") || n.classList.contains("plexvlc-menu-item")) continue;
    const label = (n.getAttribute("aria-label") || n.textContent || "").trim();
    if (!/^play$/i.test(label) && !/^watch$/i.test(label)) continue;
    const host = n.parentElement;
    if (!host || host.querySelector(".plexvlc-open, .plexvlc-menu-item")) continue;
    const inMenu = n.closest(
      '[class*="Menu-menu"], [class*="MenuItem"], [role="dialog"], [class*="Modal"], [class*="PrePlayActionBar"], [class*="PrePlayMetadata"]'
    );
    if (!inMenu) continue;
    const det = itemFromKey(pendingMenu.ratingKey, pendingMenu.machineIdentifier, pendingMenu.titleHint);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "plexvlc-open";
    btn.textContent = "Open in " + name;
    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (!det.item) {
        toast(userError(det.error), "error");
        return;
      }
      launchItem(det.item);
    });
    host.insertBefore(btn, n.nextSibling);
    return;
  }
}

function injectMenus() {
  if (!pendingStillFresh()) return;
  const name = playerNameCache;
  document.querySelectorAll('[class*="Menu-menu"]').forEach((menu) => {
    if (menu.querySelector('[class*="MenuItem-menuItem"]')) injectMenuItem(menu, name);
  });
  injectOverlayPlay(name);
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
  if (play.closest('[class*="Menu-menu"], [role="dialog"]')) return;
  if (document.getElementById("plexvlc-open-btn")) return;
  {
    const name = playerNameCache;
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
  }
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

document.addEventListener(
  "pointerdown",
  (ev) => {
    const more = moreButtonFrom(ev.target);
    if (more) rememberMenuItem(more);
  },
  true
);

function tick() {
  injectButton();
  injectMenus();
}

let tickTimer = null;
function scheduleTick() {
  if (tickTimer) return;
  tickTimer = setTimeout(() => {
    tickTimer = null;
    tick();
  }, 50);
}

tick();
setInterval(tick, 800);
window.addEventListener("hashchange", tick);
window.addEventListener("popstate", tick);
const obs = new MutationObserver(() => scheduleTick());
obs.observe(document.body || document.documentElement, { childList: true, subtree: true });
