export const adminRoutes = {
  home: "/admin",
  login: "/login",
  dashboard: "/admin/dashboard",
  market: "/admin/market",
  ai: "/admin/ai",
  trading: "/admin/trading",
  orders: "/admin/orders",
  positions: "/admin/positions",
  risk: "/admin/risk",
  strategies: "/admin/strategies",
  news: "/admin/news",
  disclosures: "/admin/disclosures",
  backtests: "/admin/backtests",
  operations: "/admin/operations",
  settings: "/admin/settings",
} as const;

export const userRoutes = {
  home: "/user",
  login: "/login",
  dashboard: "/user/dashboard",
  account: "/user/account",
  trading: "/user/trading",
  strategies: "/user/strategies",
  backtests: "/user/backtests",
  portfolio: "/user/portfolio",
  trades: "/user/trades",
  ai: "/user/ai",
  news: "/user/news",
  disclosures: "/user/disclosures",
  notifications: "/user/notifications",
  settings: "/user/settings",
  profile: "/user/profile",
} as const;

/** @deprecated Admin 경로 — adminRoutes 사용 */
export const routes = adminRoutes;

export type AdminRoute = (typeof adminRoutes)[keyof typeof adminRoutes];
export type UserRoute = (typeof userRoutes)[keyof typeof userRoutes];
export type AppRoute = AdminRoute | UserRoute;

const adminTitles: Record<string, string> = {
  [adminRoutes.home]: "Admin",
  [adminRoutes.login]: "Login",
  [adminRoutes.dashboard]: "Dashboard",
  [adminRoutes.market]: "Market",
  [adminRoutes.ai]: "AI Center",
  [adminRoutes.trading]: "Trading",
  [adminRoutes.orders]: "Orders",
  [adminRoutes.positions]: "Positions",
  [adminRoutes.risk]: "Risk",
  [adminRoutes.strategies]: "Strategy",
  [adminRoutes.news]: "News",
  [adminRoutes.disclosures]: "Disclosure",
  [adminRoutes.backtests]: "Backtest",
  [adminRoutes.operations]: "Operations",
  [adminRoutes.settings]: "Settings",
};

const userTitles: Record<string, string> = {
  [userRoutes.home]: "User",
  [userRoutes.dashboard]: "Dashboard",
  [userRoutes.account]: "내 계좌",
  [userRoutes.trading]: "자동매매",
  [userRoutes.strategies]: "전략",
  [userRoutes.backtests]: "백테스트",
  [userRoutes.portfolio]: "포트폴리오",
  [userRoutes.trades]: "거래내역",
  [userRoutes.ai]: "AI 추천",
  [userRoutes.news]: "뉴스",
  [userRoutes.disclosures]: "공시",
  [userRoutes.notifications]: "알림",
  [userRoutes.settings]: "설정",
  [userRoutes.profile]: "내 정보",
};

export const routeTitles: Record<string, string> = {
  ...adminTitles,
  ...userTitles,
  "/login": "Login",
};

export function getRouteTitle(pathname: string): string {
  const exact = routeTitles[pathname];
  if (exact) {
    return exact;
  }
  const matched = Object.entries(routeTitles).find(
    ([path]) => pathname === path || pathname.startsWith(`${path}/`),
  );
  return matched?.[1] ?? "KIKI Trade";
}
