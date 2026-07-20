export const queryKeys = {
  auth: {
    all: ["auth"] as const,
    me: () => ["auth", "me"] as const,
  },
  system: {
    all: ["system"] as const,
    status: () => ["system", "status"] as const,
    health: () => ["system", "health"] as const,
    healthLive: () => ["system", "health-live"] as const,
    healthReady: () => ["system", "health-ready"] as const,
    version: () => ["system", "version"] as const,
    dashboard: (params?: object) => ["system", "dashboard", params ?? {}] as const,
    monitoringOverview: (params?: object) =>
      ["system", "monitoring-overview", params ?? {}] as const,
    monitoringAlerts: () => ["system", "monitoring-alerts"] as const,
  },
  dashboard: {
    all: ["dashboard"] as const,
    summary: (accountId = "1") => ["dashboard", "summary", accountId] as const,
    risk: () => ["dashboard", "risk"] as const,
    strategyOps: () => ["dashboard", "strategy-ops"] as const,
  },
  admin: {
    all: ["admin"] as const,
    brokerAccount: () => ["admin", "broker-account"] as const,
    kiwoomConfig: () => ["admin", "kiwoom-config"] as const,
    paperPositions: (id: number) => ["admin", "paper-positions", id] as const,
    paperAccounts: (params?: object) =>
      ["admin", "paper-accounts", params ?? {}] as const,
    realtimeStrategy: () => ["admin", "realtime-strategy"] as const,
    realtimeExecution: () => ["admin", "realtime-execution"] as const,
    realtimeSessions: () => ["admin", "realtime-sessions"] as const,
    killSwitch: () => ["admin", "kill-switch"] as const,
    dailyLoss: () => ["admin", "daily-loss"] as const,
    riskPolicies: () => ["admin", "risk-policies"] as const,
    strategyRuntime: () => ["admin", "strategy-runtime"] as const,
    activeDeployment: (market = "KRX") =>
      ["admin", "active-deployment", market] as const,
    strategyRanking: () => ["admin", "strategy-ranking"] as const,
    strategySelection: () => ["admin", "strategy-selection"] as const,
    backtestRuns: (params?: object) =>
      ["admin", "backtest-runs", params ?? {}] as const,
    portfolioSummary: (accountId = 1) =>
      ["admin", "portfolio-summary", accountId] as const,
    positions: () => ["admin", "positions"] as const,
    orders: (params?: object) => ["admin", "orders", params ?? {}] as const,
    orderDetail: (id: number) => ["admin", "order", id] as const,
    executions: (params?: object) =>
      ["admin", "executions", params ?? {}] as const,
    paperOrders: () => ["admin", "paper-orders"] as const,
    topCandidates: (ex: string, date: string) =>
      ["admin", "top-candidates", ex, date] as const,
    aiLatest: (ex: string) => ["admin", "ai-latest", ex] as const,
    aiRuns: () => ["admin", "ai-runs"] as const,
    news: (ex: string, sym: string) => ["admin", "news", ex, sym] as const,
    newsFailures: () => ["admin", "news-failures"] as const,
    jobs: () => ["admin", "jobs"] as const,
    jobHistory: () => ["admin", "job-history"] as const,
    pipelineLatest: () => ["admin", "pipeline-latest"] as const,
    dailyReports: () => ["admin", "daily-reports"] as const,
    notificationStatus: () => ["admin", "notification-status"] as const,
    auditEvents: (params?: object) =>
      ["admin", "audit-events", params ?? {}] as const,
    upbitMarkets: () => ["admin", "upbit-markets"] as const,
    marketQuality: () => ["admin", "market-quality"] as const,
    orderOutbox: () => ["admin", "order-outbox"] as const,
    liveTransitionHistory: () => ["admin", "live-transition-history"] as const,
    members: (params?: object) => ["admin", "members", params ?? {}] as const,
    memberDetail: (id: string) => ["admin", "member", id] as const,
    roles: () => ["admin", "roles"] as const,
    permissions: (category?: string) =>
      ["admin", "permissions", category ?? "all"] as const,
    settings: (category?: string) =>
      ["admin", "settings", category ?? "all"] as const,
    settingCategories: () => ["admin", "setting-categories"] as const,
    settingHistory: (params?: object) =>
      ["admin", "setting-history", params ?? {}] as const,
    ollamaModels: () => ["admin", "ollama-models"] as const,
    ollamaStatus: () => ["admin", "ollama-status"] as const,
    opsDbStatus: () => ["admin", "ops-db-status"] as const,
    opsMigration: () => ["admin", "ops-migration"] as const,
    opsBackup: () => ["admin", "ops-backup"] as const,
    opsTables: (schema: string) => ["admin", "ops-tables", schema] as const,
    dartDisclosures: (params?: object) =>
      ["admin", "dart-disclosures", params ?? {}] as const,
    logsAudit: (params?: object) =>
      ["admin", "logs-audit", params ?? {}] as const,
    docsList: () => ["admin", "docs-list"] as const,
    docDetail: (slug: string) => ["admin", "doc", slug] as const,
  },
  user: {
    brokerAccount: () => ["user", "broker-account"] as const,
    kiwoomConfig: () => ["user", "kiwoom-config"] as const,
    paperPositions: (id: number) => ["user", "paper-positions", id] as const,
    realtimeStrategy: () => ["user", "realtime-strategy"] as const,
    realtimeExecution: () => ["user", "realtime-execution"] as const,
    realtimeExecutionHistory: () =>
      ["user", "realtime-execution-history"] as const,
    realtimeSessions: () => ["user", "realtime-sessions"] as const,
    realtimeRisk: () => ["user", "realtime-risk"] as const,
    killSwitch: () => ["user", "kill-switch"] as const,
    strategyRuntime: () => ["user", "strategy-runtime"] as const,
    activeDeployment: (marketCode = "KRX") =>
      ["user", "active-deployment", marketCode] as const,
    strategyRanking: () => ["user", "strategy-ranking"] as const,
    strategySelection: () => ["user", "strategy-selection"] as const,
    backtestRuns: () => ["user", "backtest-runs"] as const,
    walkForwardLast: () => ["user", "walk-forward-last"] as const,
    portfolioBacktestLast: () => ["user", "portfolio-backtest-last"] as const,
    portfolioSummary: (accountId = "1") =>
      ["user", "portfolio-summary", accountId] as const,
    positions: () => ["user", "positions"] as const,
    orders: (params?: object) => ["user", "orders", params ?? {}] as const,
    executions: (params?: object) =>
      ["user", "executions", params ?? {}] as const,
    paperOrders: (params?: object) =>
      ["user", "paper-orders", params ?? {}] as const,
    topCandidates: (ex: string) => ["user", "top-candidates", ex] as const,
    aiLatest: (ex: string) => ["user", "ai-latest", ex] as const,
    aiRuns: (ex?: string) => ["user", "ai-runs", ex ?? "all"] as const,
    aiRationale: (runId: number, symbol: string) =>
      ["user", "ai-rationale", runId, symbol] as const,
    ollamaStatus: () => ["user", "ollama-status"] as const,
    ollamaModels: () => ["user", "ollama-models"] as const,
    news: (ex: string, sym: string) => ["user", "news", ex, sym] as const,
    notificationStatus: () => ["user", "notification-status"] as const,
    health: () => ["user", "health"] as const,
    investmentKpis: (accountId = 1) =>
      ["user", "investment-kpis", accountId] as const,
    paperAccounts: () => ["user", "paper-accounts"] as const,
    myPaperAccount: () => ["user", "paper-account", "me"] as const,
    userAccounts: (params?: object) =>
      ["user", "accounts", params ?? {}] as const,
    portfolioHistory: (params?: object) =>
      ["user", "portfolio-history", params ?? {}] as const,
    portfolioAssetSummary: (params?: object) =>
      ["user", "portfolio-asset-summary", params ?? {}] as const,
    dartDisclosures: (stockCode: string, rangeKey = "default") =>
      ["user", "dart-disclosures", stockCode, rangeKey] as const,
    // STEP67 — 관심종목
    watchlist: () => ["user", "watchlist"] as const,
    watchlistSearch: (params?: object) =>
      ["user", "watchlist-search", params ?? {}] as const,
    // STEP68 — 관심종목 뉴스
    userNews: {
      all: ["user", "user-news"] as const,
      list: (params?: object) =>
        ["user", "user-news", "list", params ?? {}] as const,
      detail: (newsId: number) =>
        ["user", "user-news", "detail", newsId] as const,
      unreadCount: () => ["user", "user-news", "unread-count"] as const,
    },
    // STEP69 — 관심종목 공시·AI 요약
    userDisclosures: {
      all: ["user", "user-disclosures"] as const,
      list: (params?: object) =>
        ["user", "user-disclosures", "list", params ?? {}] as const,
      detail: (id: number) =>
        ["user", "user-disclosures", "detail", id] as const,
      unreadCount: () =>
        ["user", "user-disclosures", "unread-count"] as const,
      aiSummary: (id: number) =>
        ["user", "user-disclosures", "ai-summary", id] as const,
      recentSummaries: () =>
        ["user", "user-disclosures", "ai-summaries-recent"] as const,
    },
    userAiStatus: () => ["user", "ai-status"] as const,
    // STEP70 — 사용자 AI 추천
    userAi: {
      status: () => ["user", "ai-status"] as const,
      recommendations: {
        list: (params?: object) =>
          ["user", "ai-recommendations", "list", params ?? {}] as const,
        latest: (params?: object) =>
          ["user", "ai-recommendations", "latest", params ?? {}] as const,
        detail: (requestId: number) =>
          ["user", "ai-recommendations", "detail", requestId] as const,
      },
    },
    // STEP71 — Notification Center
    notifications: {
      all: ["user", "notifications"] as const,
      list: (params?: object) =>
        ["user", "notifications", "list", params ?? {}] as const,
      detail: (id: number) =>
        ["user", "notifications", "detail", id] as const,
      unreadCount: () =>
        ["user", "notifications", "unread-count"] as const,
      subscriptions: () =>
        ["user", "notifications", "subscriptions"] as const,
    },
    // STEP72 — User Preferences
    settings: {
      all: ["user", "settings"] as const,
      get: () => ["user", "settings", "get"] as const,
    },
    // STEP73 — My Profile
    profile: {
      all: ["user", "profile"] as const,
      detail: () => ["user", "profile", "detail"] as const,
      sessions: () => ["user", "profile", "sessions"] as const,
      connections: () => ["user", "profile", "connections"] as const,
      accountsSummary: () =>
        ["user", "profile", "accounts-summary"] as const,
    },
    paperAccount: (id: number) => ["user", "paper-account", id] as const,
    latestPrice: (ex: string, sym: string) =>
      ["user", "latest-price", ex, sym] as const,
    realtimeQuote: (ex: string, sym: string) =>
      ["user", "realtime-quote", ex, sym] as const,
    realtimeQuotesStatus: () => ["user", "realtime-quotes-status"] as const,
    marketSymbols: (market: string) =>
      ["user", "market-symbols", market] as const,
    strategyOps: () => ["user", "strategy-ops"] as const,
  },
};
