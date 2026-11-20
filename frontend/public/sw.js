/* F4.1 — Service Worker: offline-first (AK) + auditní opravy 2026-11:
 * - navigace (/spa/ index.html): network-first s offline fallbackem — cache-first
 *   servíroval zastaralý index po novém deployu bundle (white screen);
 * - API GET: cachují se jen OK odpovědi (4xx/5xx se dříve trvale ukládaly);
 * - statické assety (hash v názvu, immutable): cache-first beze změny.
 */
const CACHE = "stopa-spa-v2";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(["/spa/"])));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // navigace (/spa/ index.html): network-first + offline fallback na cached kopii
  if (req.mode === "navigate" && url.pathname.startsWith("/spa")) {
    event.respondWith(
      fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put("/spa/", copy));
        return res;
      }).catch(() => caches.match(req)),
    );
    return;
  }

  // API: network-first + cache fallback (offline read-only); jen OK odpovědi
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(req).then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => caches.match(req)),
    );
    return;
  }

  // statické assety: cache-first
  event.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(req, copy));
      return res;
    })),
  );
});
