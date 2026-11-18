/* Lokföraren (LOK-14): the app's shell stays in the phone, so that it opens without the network
 * at the meet. Only the shell: the page, its built files and the icons under /lokforaren/. The
 * API (/api/...) is never stored here, and neither is anyone's photo: what Drift says is always
 * read anew (LOK-12, LOK-37). Ported from the old Server's sw.js.
 *
 * The page: the network first, so that a new version always comes through; the stored copy only
 * when the hub does not answer. The built files carry their content in their names and never
 * change under the same address: the stored copy first. When a new page has come, the files it
 * no longer names are taken away. */
const CACHE = "lokforaren-1";
const SCOPE = "/lokforaren/";
const PAGE = SCOPE;
const SHELL = [PAGE, SCOPE + "manifest.webmanifest", SCOPE + "favicon.svg", SCOPE + "icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key.startsWith("lokforaren-") && key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

/** The built files the page names: the rest are an older version's. */
async function prune(cache, html) {
  const named = new Set([...html.matchAll(/\/lokforaren\/assets\/[^"'\s)]+/g)].map((match) => match[0]));
  for (const request of await cache.keys()) {
    const path = new URL(request.url).pathname;
    if (path.startsWith(SCOPE + "assets/") && /\.(js|css)$/.test(path) && !named.has(path)) await cache.delete(request);
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith(SCOPE) || url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then(async (cache) => {
              await cache.put(PAGE, copy.clone());
              await prune(cache, await copy.text());
            });
          }
          return response;
        })
        .catch(() => caches.match(PAGE, { cacheName: CACHE }).then((cached) => cached || Response.error())),
    );
    return;
  }

  const built = url.pathname.startsWith(SCOPE + "assets/");
  if (!built && !SHELL.includes(url.pathname)) return;
  event.respondWith(
    caches.open(CACHE).then((cache) =>
      cache.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            if (response.ok) cache.put(request, response.clone());
            return response;
          }),
      ),
    ),
  );
});
