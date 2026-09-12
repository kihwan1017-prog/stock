/* Mobile PWA V2 — navigation shell only.
 * V1은 .js/.css까지 캐시하고, fetch 실패 시 /mobile HTML을 스크립트에 돌려
 * 파싱 오류 → 전체 리로드 루프를 유발했다. V2는 문서 네비게이션만 처리한다.
 */
const SHELL_CACHE = "stock-mobile-shell-v2";
/** 인증 HTML(/mobile)은 precache 금지 — 로그인 리다이렉트 페이지가 캐시되는 것 방지 */
const STATIC_URLS = ["/manifest.webmanifest", "/favicon.ico"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(STATIC_URLS))
      .catch(() => undefined),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((key) => key !== SHELL_CACHE).map((key) => caches.delete(key)),
      );
      await self.clients.claim();
    })(),
  );
});

function isSameOrigin(url) {
  return url.origin === self.location.origin;
}

function isApiPath(pathname) {
  return pathname.includes("/api/") || pathname.includes("/mobile/overview");
}

function isMobileNavigation(request, url) {
  const acceptsHtml = (request.headers.get("accept") || "").includes("text/html");
  const isNavigate = request.mode === "navigate" || acceptsHtml;
  if (!isNavigate) {
    return false;
  }
  return url.pathname === "/mobile" || url.pathname.startsWith("/mobile/");
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") {
    return;
  }

  let url;
  try {
    url = new URL(req.url);
  } catch {
    return;
  }

  if (!isSameOrigin(url)) {
    return;
  }

  // API — network only (오프라인은 JSON 503)
  if (isApiPath(url.pathname)) {
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

  // _next chunk / CSS / RSC 등 — 가로채지 않음 (HTML fallback 절대 금지)
  if (!isMobileNavigation(req, url)) {
    return;
  }

  event.respondWith(
    (async () => {
      try {
        const response = await fetch(req);
        // 로그인으로 떨어진 응답은 /mobile 키로 캐시하지 않음
        const finalPath = new URL(response.url).pathname;
        const landedOnLogin =
          finalPath === "/login" || finalPath.startsWith("/login/");
        if (
          response.ok &&
          response.type === "basic" &&
          !landedOnLogin
        ) {
          const copy = response.clone();
          const cache = await caches.open(SHELL_CACHE);
          await cache.put(req, copy);
        }
        return response;
      } catch {
        const cached = await caches.match(req);
        if (cached) {
          return cached;
        }
        const shell = await caches.match("/mobile");
        if (shell) {
          return shell;
        }
        return new Response(
          "오프라인입니다. 네트워크 연결 후 다시 시도하세요.",
          {
            status: 503,
            headers: { "Content-Type": "text/plain; charset=utf-8" },
          },
        );
      }
    })(),
  );
});
