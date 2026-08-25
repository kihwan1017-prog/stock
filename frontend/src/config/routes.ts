export const adminRoutes = {
  home: "/admin",
  login: "/login",
  dashboard: "/admin/dashboard",
  members: "/admin/members",
  roles: "/admin/roles",
  accounts: "/admin/accounts",
  trading: "/admin/trading",
  strategies: "/admin/strategies",
  /** 전략·분석 허브 — 시장 selector + 기존 화면 링크 */
  strategyCandidates: "/admin/strategy-candidates",
  marketAnalysis: "/admin/market-analysis",
  newsDisclosures: "/admin/news-disclosures",
  aiAnalysis: "/admin/ai-analysis",
  llmLearning: "/admin/llm-learning",
  strategyValidation: "/admin/strategy-validation",
  researchData: "/admin/research",
  ai: "/admin/ai",
  aiProviders: "/admin/ai/providers",
  aiPrompts: "/admin/ai/prompts",
  aiSchemas: "/admin/ai/schemas",
  aiPolicies: "/admin/ai/policies",
  aiExecutions: "/admin/ai/executions",
  aiDocumentAnalyses: "/admin/ai/document-analyses",
  aiMarketAnalyses: "/admin/ai/market-analyses",
  aiReviews: "/admin/ai/reviews",
  aiEvaluationDatasets: "/admin/ai/evaluation-datasets",
  aiBenchmarks: "/admin/ai/benchmarks",
  aiCandidateAssessments: "/admin/ai/candidate-assessments",
  aiCandidateConsensuses: "/admin/ai/candidate-consensuses",
  aiCandidateRecommendationQueues: "/admin/ai/candidate-recommendation-queues",
  aiCandidatePromotions: "/admin/ai/candidate-promotions",
  aiCandidateLifecycle: "/admin/ai/candidate-lifecycle",
  /** STEP12-1: AI Candidate -> Strategy Request 승인 게이트(관리자 심사) */
  strategyRequests: "/admin/strategy-requests",
  /** STEP12-2-1: 승인된 Strategy Request 위의 Strategy Draft 저장/버전관리 */
  strategyDrafts: "/admin/strategy-drafts",
  /** STEP12-13: 복수 승인 Strategy Definition의 기존 Backtest 결과 조합 검증 */
  portfolioValidations: "/admin/portfolio-validations",
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
  upbitMarkets: "/admin/upbit/markets",
  /** UPBIT 자동매매 설정 워크스페이스 (6탭) */
  upbitAutotrading: "/admin/upbit/autotrading",
  /** 단일 운영자 — Broker Workspace canonical */
  autotradingUpbit: "/admin/autotrading/upbit",
  autotradingKiwoom: "/admin/autotrading/kiwoom",
  /** 주문·체결 통합 허브 (trades는 탭/리다이렉트) */
  orderFills: "/admin/orders",
  liveValidationUpbit: "/admin/live-validation/upbit",
  /** STEP4-6: 기술지표 관리 — 준비중(ComingSoon) */
  indicators: "/admin/indicators",
  /** STEP4-6: 장애 복구 센터 — 준비중(ComingSoon) */
  recovery: "/admin/recovery",
  batch: "/admin/batch",
  notifications: "/admin/notifications",
  telegram: "/admin/telegram",
  docs: "/admin/docs",
  /** 운영관리 → 문서관리 → 매뉴얼 (화면 내 통합 조회) */
  docsManual: "/admin/docs/manual",
  operations: "/admin/operations",
  operationsDashboard: "/admin/operations-dashboard",
  /** STEP 9-7: LIVE ON 전 Pre-flight Check */
  operationsPreflight: "/admin/operations/preflight",
  /** STEP4-6: 관리자 내 정보 — 준비중(ComingSoon) */
  profile: "/admin/profile",
  // 하위 호환·리다이렉트용
  market: "/admin/monitoring",
  positions: "/admin/portfolio",
  settings: "/admin/env-settings",
} as const;

export const userRoutes = {
  home: "/user",
  login: "/login",
  dashboard: "/user/dashboard",

  /** 내 계좌 — STEP4-6: /user/account → /user/accounts로 개편 */
  accounts: "/user/accounts",
  accountsKiwoom: "/user/accounts/kiwoom",
  accountsUpbit: "/user/accounts/upbit",
  accountsPaper: "/user/accounts/paper",

  /** 매매(수동 주문 실행) — 경로 변경 없음 */
  trading: "/user/trading",
  autoTrading: "/user/auto-trading",

  /** 내 전략 */
  strategies: "/user/strategies",
  /** STEP4-6: /user/strategies/auto → /user/auto-trading 별칭 경로 */
  strategiesAuto: "/user/strategies/auto",
  backtests: "/user/backtests",

  portfolio: "/user/portfolio",
  watchlist: "/user/watchlist",

  /** 내 주문·체결 — STEP4-6: /user/trades → /user/orders로 개편 */
  orders: "/user/orders",
  ordersKiwoom: "/user/orders/kiwoom",
  ordersUpbit: "/user/orders/upbit",
  ordersPaper: "/user/orders/paper",

  ai: "/user/ai",
  /** STEP12-1: AI Candidate -> Strategy Request 승인 게이트(내 요청) */
  strategyRequests: "/user/strategy-requests",
  /** STEP12-2-1: 내 Strategy Request 위의 Strategy Draft 조회(읽기 전용) */
  strategyDrafts: "/user/strategy-drafts",

  /** 시장 정보 — STEP4-6: /user/market → /user/markets/{stocks|crypto}로 개편 */
  marketsStocks: "/user/markets/stocks",
  marketsCrypto: "/user/markets/crypto",

  /** 매매 후보 — STEP4-6 신규 */
  candidatesStocks: "/user/candidates/stocks",
  candidatesCrypto: "/user/candidates/crypto",
  candidatesLlm: "/user/candidates/llm",

  news: "/user/news",
  disclosures: "/user/disclosures",
  notifications: "/user/notifications",
  reports: "/user/reports",

  /** 내 리스크 — STEP4-6 신규(준비중) */
  risk: "/user/risk",
  liveValidationUpbit: "/user/live-validation/upbit",

  settings: "/user/settings",
  profile: "/user/profile",
} as const;

/** @deprecated 구 경로 — 리다이렉트 소스로만 사용. 신규 코드는 위 캐노니컬 경로를 사용 */
export const legacyUserRoutes = {
  account: "/user/account",
  trades: "/user/trades",
  market: "/user/market",
} as const;

/** 공개 인증 경로 */
export const authRoutes = {
  login: "/login",
  signup: "/signup",
  changePassword: "/change-password",
  onboarding: "/onboarding",
  forbidden: "/forbidden",
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
  [adminRoutes.dashboard]: "관리자 대시보드",
  [adminRoutes.members]: "회원관리",
  [adminRoutes.roles]: "권한관리",
  [adminRoutes.accounts]: "전체 계좌",
  [adminRoutes.trading]: "자동매매 Runtime",
  [adminRoutes.strategies]: "전략관리",
  [adminRoutes.strategyCandidates]: "전략·후보",
  [adminRoutes.marketAnalysis]: "시장 분석",
  [adminRoutes.newsDisclosures]: "뉴스·공시",
  [adminRoutes.aiAnalysis]: "AI 분석",
  [adminRoutes.strategyValidation]: "전략 검증",
  [adminRoutes.researchData]: "연구 데이터",
  [adminRoutes.ai]: "후보·LLM 관리",
  [adminRoutes.aiProviders]: "AI Provider 관리",
  [adminRoutes.aiPrompts]: "AI Prompt 관리",
  [adminRoutes.aiSchemas]: "AI Output Schema 관리",
  [adminRoutes.aiPolicies]: "AI Policy 관리",
  [adminRoutes.aiExecutions]: "AI Execution 관리",
  [adminRoutes.aiDocumentAnalyses]: "AI 문서 분석",
  [adminRoutes.aiMarketAnalyses]: "AI 시장·차트 분석",
  [adminRoutes.aiReviews]: "AI 분석 품질 검토",
  [adminRoutes.aiEvaluationDatasets]: "AI 평가 데이터셋",
  [adminRoutes.aiBenchmarks]: "AI 벤치마크·스코어카드",
  [adminRoutes.aiCandidateAssessments]: "AI 후보 평가 초안",
  [adminRoutes.aiCandidateConsensuses]: "Multi-AI 합의 초안",
  [adminRoutes.aiCandidateRecommendationQueues]: "후보 추천 검토 큐",
  [adminRoutes.aiCandidatePromotions]: "Candidate Promotion Gateway",
  [adminRoutes.aiCandidateLifecycle]: "Candidate Lifecycle",
  [adminRoutes.strategyRequests]: "전략 요청",
  [adminRoutes.strategyDrafts]: "전략 초안",
  [adminRoutes.portfolioValidations]: "포트폴리오 검증",
  [adminRoutes.news]: "뉴스관리",
  [adminRoutes.disclosures]: "공시관리",
  [adminRoutes.portfolio]: "보유자산·손익",
  [adminRoutes.backtests]: "백테스트",
  [adminRoutes.orders]: "주문·체결",
  [adminRoutes.trades]: "주문·체결",
  [adminRoutes.risk]: "리스크 관리",
  [adminRoutes.scheduler]: "스케줄러 관리",
  [adminRoutes.operations]: "시스템 운영",
  [adminRoutes.operationsDashboard]: "거래 운영 현황",
  [adminRoutes.operationsPreflight]: "Pre-flight Check",
  [adminRoutes.systemSettings]: "시스템 설정",
  [adminRoutes.envSettings]: "환경설정",
  [adminRoutes.logs]: "로그 조회",
  [adminRoutes.monitoring]: "시스템 상태",
  [adminRoutes.db]: "DB 관리",
  [adminRoutes.api]: "API 관리",
  [adminRoutes.ollama]: "Ollama 관리",
  [adminRoutes.kiwoom]: "키움 계좌",
  [adminRoutes.upbit]: "업비트 계좌",
  [adminRoutes.upbitMarkets]: "업비트 시세",
  [adminRoutes.upbitAutotrading]: "업비트 자동매매",
  [adminRoutes.autotradingUpbit]: "업비트 자동매매",
  [adminRoutes.autotradingKiwoom]: "키움 자동매매",
  [adminRoutes.liveValidationUpbit]: "업비트 소액 LIVE 검증",
  [adminRoutes.indicators]: "기술지표 관리",
  [adminRoutes.recovery]: "장애 복구",
  [adminRoutes.batch]: "배치 관리",
  [adminRoutes.notifications]: "알림 관리",
  [adminRoutes.telegram]: "Telegram 운영",
  [adminRoutes.docs]: "문서 CMS",
  [adminRoutes.docsManual]: "매뉴얼",
  [adminRoutes.profile]: "관리자 내 정보",
};

const userTitles: Record<string, string> = {
  [userRoutes.home]: "User",
  [userRoutes.dashboard]: "대시보드",
  [userRoutes.accounts]: "전체 계좌",
  [userRoutes.accountsKiwoom]: "키움 계좌",
  [userRoutes.accountsUpbit]: "업비트 계좌",
  [userRoutes.accountsPaper]: "Paper 계좌",
  [userRoutes.trading]: "매매",
  [userRoutes.autoTrading]: "자동매매",
  [userRoutes.strategies]: "전략",
  [userRoutes.strategiesAuto]: "전략 · 자동매매",
  [userRoutes.backtests]: "백테스트",
  [userRoutes.portfolio]: "내 잔고·손익",
  [userRoutes.watchlist]: "관심종목",
  [userRoutes.orders]: "내 주문·체결",
  [userRoutes.ordersKiwoom]: "키움 주문·체결",
  [userRoutes.ordersUpbit]: "업비트 주문·체결",
  [userRoutes.ordersPaper]: "Paper 주문·체결",
  [userRoutes.ai]: "AI 추천 · LLM 분석",
  [userRoutes.strategyRequests]: "전략 요청",
  [userRoutes.strategyDrafts]: "전략 초안",
  [userRoutes.marketsStocks]: "주식 시장정보",
  [userRoutes.marketsCrypto]: "암호화폐 시장정보",
  [userRoutes.candidatesStocks]: "주식 매매 후보",
  [userRoutes.candidatesCrypto]: "업비트 매매 후보",
  [userRoutes.candidatesLlm]: "LLM 분석",
  [userRoutes.news]: "뉴스",
  [userRoutes.disclosures]: "공시",
  [userRoutes.notifications]: "알림",
  [userRoutes.reports]: "내 리포트",
  [userRoutes.risk]: "내 리스크",
  [userRoutes.liveValidationUpbit]: "업비트 LIVE 검증(읽기)",
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
