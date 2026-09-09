(() => {
  const SKIP = /\/(children|extras|related|tree|similar)(\?|$)/;
  const META = /\/library\/metadata\/(\d+)/;

  function tokenFrom(url, headers) {
    try {
      const u = new URL(url, location.href);
      const q = u.searchParams.get("X-Plex-Token") || u.searchParams.get("X-Plex-Token".toLowerCase());
      if (q) return q;
    } catch {
      /* ignore */
    }
    if (headers) {
      if (typeof headers.get === "function") {
        return headers.get("X-Plex-Token") || headers.get("x-plex-token");
      }
      if (typeof headers === "object") {
        return headers["X-Plex-Token"] || headers["x-plex-token"] || null;
      }
    }
    return null;
  }

  function maybeAnnounce(requestUrl, headers) {
    let u;
    try {
      u = new URL(requestUrl, location.href);
    } catch {
      return;
    }
    const path = u.pathname || "";
    const m = path.match(META);
    if (!m) return;
    if (SKIP.test(path)) return;
    const token = tokenFrom(u.href, headers);
    const host = (u.hostname || "").toLowerCase();
    if (
      host === "app.plex.tv" ||
      host.endsWith(".plex.tv") ||
      host.endsWith(".plex.services")
    ) {
      return;
    }
    window.postMessage(
      {
        source: "plexvlc-page-hook",
        kind: "pms-request",
        ratingKey: m[1],
        pmsBaseUrl: u.origin,
        plexToken: token || null,
        href: u.href,
      },
      location.origin
    );
  }

  const origFetch = window.fetch;
  if (typeof origFetch === "function") {
    window.fetch = function patchedFetch(input, init) {
      try {
        const url = typeof input === "string" ? input : input && input.url;
        const headers = (init && init.headers) || (input && input.headers);
        if (url) maybeAnnounce(url, headers);
      } catch {
        /* ignore */
      }
      return origFetch.apply(this, arguments);
    };
  }

  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__plexvlcUrl = url;
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function (body) {
    try {
      if (this.__plexvlcUrl) maybeAnnounce(this.__plexvlcUrl, null);
    } catch {
      /* ignore */
    }
    return origSend.apply(this, arguments);
  };
})();
