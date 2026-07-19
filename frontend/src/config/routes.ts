export const adminRoutes = {
  home: "/admin",
  login: "/login",
  dashboard: "/admin/dashboard",
  members: "/admin/members",
  roles: "/admin/roles",
  accounts: "/admin/accounts",
  trading: "/admin/trading",
  strategies: "/admin/strategies",
  ai: "/admin/ai",
  news: "/admin/news",
  disclosures: "/admin/disclosures",
  portfolio: "/admin/portfolio",
  backtests: "/admin/backtests",
  orders: "/admin/orders",
  trades: "/admin/trades",
  risk: "/admin/risk",
  scheduler: "/admin/scheduler",
  systemSettings: "/admin/system-settings",
  envSettings: "/admin/env-settings",
  logs: "/admin/logs",
  monitoring: "/admin/monitoring",
  /** STEP56: 데이터 관리 메뉴 → 모니터링 (실체 페이지 없음) */
  data: "/admin/monitoring",
  db: "/admin/db",
  api: "/admin/api",
  ollama: "/admin/ollama",
  kiwoom: "/admin/kiwoom",
  upbit: "/admin/upbit",
  batch: "/admin/batch",
  notifications: "/admin/notifications",
  telegram: "/admin/telegram",
  docs: "/admin/docs",
  operations: "/admin/operations",
  // 하위 호환·리다이렉트용
  market: "/admin/monitoring",
  positions: "/admin/portfolio",
  settings: "/admin/env-settings",
} as const;

export const userRoutes = {
  home: "/user",
  login: "/login",
  dashboard: "/user/dashboard",
  account: "/user/account",
  trading: "/user/trading",
  autoTrading: "/user/auto-trading",
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

/** 공개 인증 경로 */
export const authRoutes = {
  login: "/login",
  signup: "/signup",
} as const;

/** @deprecated Admin 경로 — adminRoutes 사용. signup 은 authRoutes 권장 */
export const routes = {
  ...adminRoutes,
  signup: authRoutes.signup,
} as const;

export type AdminRoute = (typeof adminRoutes)[keyof typeof adminRoutes];
export type UserRoute = (typeof userRoutes)[keyof typeof userRoutes];
export type AppRoute = AdminRoute | UserRoute;

const adminTitles: Record<string, string> = {
  [adminRoutes.home]: "Admin",
  [adminRoutes.login]: "Login",
  [adminRoutes.dashboard]: "Dashboard",
  [adminRoutes.members]: "회원관리",
  [adminRoutes.roles]: "권한관리",
  [adminRoutes.accounts]: "계좌관리",
  [adminRoutes.trading]: "자동매매관리",
  [adminRoutes.strategies]: "전략관리",
  [adminRoutes.ai]: "AI 관리",
  [adminRoutes.news]: "뉴스관리",
  [adminRoutes.disclosures]: "공시관리",
  [adminRoutes.portfolio]: "포트폴리오",
  [adminRoutes.backtests]: "백테스트",
  [adminRoutes.orders]: "주문관리",
  [adminRoutes.trades]: "거래내역",
  [adminRoutes.risk]: "Risk 관리",
  [adminRoutes.scheduler]: "Scheduler 관리",
  [adminRoutes.operations]: "운영센터",
  [adminRoutes.systemSettings]: "시스템 설정",
  [adminRoutes.envSettings]: "환경설정",
  [adminRoutes.logs]: "로그 조회",
  [adminRoutes.monitoring]: "시스템 모니터링 · 데이터",
  [adminRoutes.db]: "DB 관리",
  [adminRoutes.api]: "API 관리",
  [adminRoutes.ollama]: "Ollama 관리",
  [adminRoutes.kiwoom]: "키움 API 관리",
  [adminRoutes.upbit]: "업비트 관리",
  [adminRoutes.batch]: "배치 관리",
  [adminRoutes.notifications]: "알림 관리",
  [adminRoutes.telegram]: "Telegram 운영",
  [adminRoutes.docs]: "문서 관리",
};

const userTitles: Record<string, string> = {
  [userRoutes.home]: "User",
  [userRoutes.dashboard]: "Dashboard",
  [userRoutes.account]: "내 계좌",
  [userRoutes.trading]: "매매",
  [userRoutes.autoTrading]: "자동매매",
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
  "/signup": "회원가입",
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
