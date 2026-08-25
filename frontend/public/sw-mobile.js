/* Mobile PWA V1 service worker — status API는 network-first, stale를 최신처럼 표시하지 않음 */
const SHELL_CACHE = "stock-mobile-shell-v1";
const SHELL_URLS = ["/mobile", "/manifest.webmanifest", "/favicon.ico"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_URLS)).catch(() => undefined),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== SHELL_CACHE)
          .map((k) => caches.delete(k)),
      ),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") {
    return;
  }
  const url = new URL(req.url);

  // API / mobile overview — 절대 캐시 응답으로 최신인 척 금지
  if (url.pathname.includes("/api/") || url.pathname.includes("/mobile/overview")) {
    event.respondWith(
      fetch(req).catch(
        () =>
          new Response(
            JSON.stringify({
              error: "OFFLINE",
              message: "현재 연결되지 않았습니다.",
            }),
            {
              status: 503,
              headers: { "Content-Type": "application/json" },
            },
          ),
      ),
    );
    return;
  }

  // 정적/HTML — network first, 실패 시 shell cache
  event.respondWith(
    fetch(req)
      .then((res) => {
        const copy = res.clone();
        if (res.ok && (url.pathname.startsWith("/mobile") || url.pathname.endsWith(".js") || url.pathname.endsWith(".css"))) {
          void caches.open(SHELL_CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req).then((c) => c || caches.match("/mobile"))),
  );
});
