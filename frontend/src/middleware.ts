import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Admin/User 보호 라우트 — 쿠키 또는 Authorization 헤더 없으면 로그인으로.
 * 토큰은 sessionStorage 우선(클라이언트). 서버 미들웨어는 쿠키 기반 보조 게이트.
 */
const PROTECTED_PREFIXES = ["/admin", "/user", "/mypage", "/portfolio", "/mobile"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const needsAuth = PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
  if (!needsAuth) {
    return NextResponse.next();
  }

  const cookieToken =
    request.cookies.get("kiki-admin-token")?.value ||
    request.cookies.get("kiki-access-token")?.value;
  const headerAuth = request.headers.get("authorization");
  if (cookieToken || (headerAuth && headerAuth.startsWith("Bearer "))) {
    return NextResponse.next();
  }

  // 클라이언트 sessionStorage만 쓰는 경우 미들웨어는 통과시키고
  // 레이아웃/가드에서 최종 차단 — 단, 공개 로그인으로 soft-redirect 힌트 제공
  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  loginUrl.searchParams.set("next", pathname);
  // Soft gate: HTML 네비게이션만 리다이렉트 (API/prefetch는 통과)
  const accept = request.headers.get("accept") || "";
  if (accept.includes("text/html")) {
    return NextResponse.redirect(loginUrl);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/admin/:path*",
    "/user/:path*",
    "/mypage/:path*",
    "/portfolio/:path*",
    "/mobile",
    "/mobile/:path*",
  ],
};
