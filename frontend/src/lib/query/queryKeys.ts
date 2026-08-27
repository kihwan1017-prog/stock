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
    paperAccount: (id: number) => ["admin", "paper-account", id] as const,
    paperAccounts: (params?: object) =>
      ["admin", "paper-accounts", params ?? {}] as const,
    realtimeStrategy: () => ["admin", "realtime-strategy"] as const,
    realtimeExecution: () => ["admin", "realtime-execution"] as const,
    realtimeSessions: () => ["admin", "realtime-sessions"] as const,
    realtimeHubScopes: () => ["admin", "realtime-hub-scopes"] as const,
    realtimeHubConnections: () =>
      ["admin", "realtime-hub-connections"] as const,
    killSwitch: () => ["admin", "kill-switch"] as const,
    brokerRecoveryStatus: () => ["admin", "broker-recovery-status"] as const,
    dailyLoss: () => ["admin", "daily-loss"] as const,
    riskPolicies: () => ["admin", "risk-policies"] as const,
    systemRiskSettings: () => ["admin", "system-risk-settings"] as const,
    userRiskSettings: (userId: number) =>
      ["admin", "user-risk-settings", userId] as const,
    liveOrderAccounts: (userId: number) =>
      ["admin", "live-order-accounts", userId] as const,
    liveOpsDashboard: () => ["admin", "live-ops-dashboard"] as const,
    operationsCenterSummary: () =>
      ["admin", "operations-center", "summary"] as const,
    autotradingPerformance: (params?: {
      broker?: string;
      period?: string;
      includeOps?: boolean;
    }) =>
      ["admin", "autotrading-performance", params ?? {}] as const,
    runtimePreflight: (ubaId?: number) =>
      ubaId != null
        ? (["admin", "runtime", "preflight", ubaId] as const)
        : (["admin", "runtime", "preflight"] as const),
    aiProviderConfigurations: () =>
      ["admin", "ai-provider-configurations"] as const,
    aiPromptTemplates: () => ["admin", "ai-prompt-templates"] as const,
    aiOutputSchemas: () => ["admin", "ai-output-schemas"] as const,
    aiPolicies: () => ["admin", "ai-policies"] as const,
    aiExecutions: () => ["admin", "ai-executions"] as const,
    aiDocumentAnalyses: () => ["admin", "ai-document-analyses"] as const,
    aiMarketAnalyses: () => ["admin", "ai-market-analyses"] as const,
    aiReviews: () => ["admin", "ai-reviews"] as const,
    aiEvaluationDatasets: () => ["admin", "ai-evaluation-datasets"] as const,
    aiBenchmarks: () => ["admin", "ai-benchmarks"] as const,
    aiCandidateAssessments: () => ["admin", "ai-candidate-assessments"] as const,
    aiCandidateConsensuses: () => ["admin", "ai-candidate-consensuses"] as const,
    aiCandidateRecommendationQueues: () =>
      ["admin", "ai-candidate-recommendation-queues"] as const,
    aiCandidatePromotions: () =>
      ["admin", "ai-candidate-promotions"] as const,
    aiCandidateLifecycle: () =>
      ["admin", "ai-candidate-lifecycle"] as const,
    // STEP12-1 — Strategy Request 심사(관리자)
    strategyRequests: {
      list: (params?: object) =>
        ["admin", "strategy-requests", "list", params ?? {}] as const,
      detail: (id: number) =>
        ["admin", "strategy-requests", "detail", id] as const,
      history: (id: number) =>
        ["admin", "strategy-requests", "history", id] as const,
    },
    // STEP12-2-1 — Strategy Draft 저장/버전관리(관리자)
    strategyDrafts: {
      list: (params?: object) =>
        ["admin", "strategy-drafts", "list", params ?? {}] as const,
      detail: (id: number) =>
        ["admin", "strategy-drafts", "detail", id] as const,
      history: (id: number) =>
        ["admin", "strategy-drafts", "history", id] as const,
      version: (strategyRequestId: number, version: number) =>
        [
          "admin",
          "strategy-drafts",
          "version",
          strategyRequestId,
          version,
        ] as const,
    },
    // STEP12-2-2/12-2-3 — AI Strategy Draft Generator(관리자)
    strategyDraftGenerations: {
      list: (params?: object) =>
        ["admin", "strategy-draft-generations", "list", params ?? {}] as const,
      detail: (id: number) =>
        ["admin", "strategy-draft-generations", "detail", id] as const,
      attempts: (id: number) =>
        ["admin", "strategy-draft-generations", "attempts", id] as const,
    },
    // STEP12-2-3 — 비교/Timeline
    strategyDraftComparison: (draftId: number, compareDraftId: number) =>
      ["admin", "strategy-drafts", "comparison", draftId, compareDraftId] as const,
    draftTimeline: (strategyRequestId: number) =>
      ["admin", "strategy-requests", "draft-timeline", strategyRequestId] as const,
    // STEP12-3 — Strategy Draft 최종 승인
    strategyDraftApprovals: {
      forDraft: (draftId: number) =>
        ["admin", "strategy-draft-approvals", "for-draft", draftId] as const,
      detail: (id: number) =>
        ["admin", "strategy-draft-approvals", "detail", id] as const,
      history: (id: number) =>
        ["admin", "strategy-draft-approvals", "history", id] as const,
      list: (params?: object) =>
        ["admin", "strategy-draft-approvals", "list", params ?? {}] as const,
    },
    // STEP12-4 — Strategy Snapshot(승인으로 생성된 불변 Definition)
    strategySnapshot: {
      detail: (id: number) => ["admin", "strategy-snapshot", "detail", id] as const,
      history: (id: number) => ["admin", "strategy-snapshot", "history", id] as const,
    },
    // STEP12-5 — Backtest Readiness / Provenance Chain
    strategyReadiness: (id: number) =>
      ["admin", "strategy-readiness", id] as const,
    strategyProvenance: (id: number) =>
      ["admin", "strategy-provenance", id] as const,
    // STEP12-6 — Backtest Executable Specification(컴파일 진단, 실행 아님)
    strategyBacktestSpecification: (id: number) =>
      ["admin", "strategy-backtest-specification", id] as const,
    // STEP12-8 — Backtest 결과 기반 Performance Analytics
    backtestRunPerformance: (backtestRunId: number) =>
      ["admin", "backtest-run-performance", backtestRunId] as const,
    // STEP12-9 — Walk-Forward Analysis / Overfitting Report
    strategyWalkForward: (strategyDefinitionId: number, runId: number) =>
      ["admin", "strategy-walk-forward", strategyDefinitionId, runId] as const,
    strategyWalkForwardOverfitting: (strategyDefinitionId: number, runId: number) =>
      ["admin", "strategy-walk-forward-overfitting", strategyDefinitionId, runId] as const,
    // STEP12-10 — Strategy Quality Gate
    strategyQualityGate: (strategyDefinitionId: number, reportId: number) =>
      ["admin", "strategy-quality-gate", strategyDefinitionId, reportId] as const,
    // STEP12-11 — Parameter Sensitivity Analysis
    strategyParameterSensitivity: (strategyDefinitionId: number, reportId: number) =>
      ["admin", "strategy-parameter-sensitivity", strategyDefinitionId, reportId] as const,
    // STEP12-12 — Monte Carlo Simulation
    strategyMonteCarlo: (strategyDefinitionId: number, reportId: number) =>
      ["admin", "strategy-monte-carlo", strategyDefinitionId, reportId] as const,
    // STEP12-13 — Portfolio Validation(복수 Strategy 조합)
    portfolioValidation: (reportId: number) =>
      ["admin", "portfolio-validation", reportId] as const,
    // STEP12-14 — Strategy Explainability & Decision Evidence Layer
    strategyExplainability: (strategyDefinitionId: number, reportId: number) =>
      ["admin", "strategy-explainability", strategyDefinitionId, reportId] as const,
    strategyDefinitions: (params?: object) =>
      ["admin", "strategy-definitions", params ?? {}] as const,
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
    telegramMarketStatus: () => ["admin", "telegram-market-status"] as const,
    notificationTemplates: (params?: object) =>
      ["admin", "notification-templates", params ?? {}] as const,
    notificationDeliveryLogs: (params?: object) =>
      ["admin", "notification-delivery-logs", params ?? {}] as const,
    auditEvents: (params?: object) =>
      ["admin", "audit-events", params ?? {}] as const,
    upbitMarkets: () => ["admin", "upbit-markets"] as const,
    upbitAccountStatus: () => ["admin", "upbit-account-status"] as const,
    upbitAccountSnapshot: () => ["admin", "upbit-account-snapshot"] as const,
    upbitRateLimits: () => ["admin", "upbit-rate-limits"] as const,
    upbitOpportunityScanner: () =>
      ["admin", "upbit-opportunity-scanner"] as const,
    upbitResearchCollectionStatus: (ubaId: number) =>
      ["admin", "upbit-research-collection-status", ubaId] as const,
    upbitResearchCleanForward: (params?: object) =>
      ["admin", "upbit-research-clean-forward", params ?? {}] as const,
    upbitResearchCleanForwardDetail: (shadowId: number) =>
      ["admin", "upbit-research-clean-forward-detail", shadowId] as const,
    upbitResearchMarketContext: (params?: object) =>
      ["admin", "upbit-research-market-context", params ?? {}] as const,
    upbitResearchAssetContext: (params?: object) =>
      ["admin", "upbit-research-asset-context", params ?? {}] as const,
    upbitResearchNews: (params?: object) =>
      ["admin", "upbit-research-news", params ?? {}] as const,
    upbitResearchLlmAnalysis: (params?: object) =>
      ["admin", "upbit-research-llm-analysis", params ?? {}] as const,
    upbitResearchLlmDetail: (analysisId: number) =>
      ["admin", "upbit-research-llm-detail", analysisId] as const,
    upbitResearchExperiments: () =>
      ["admin", "upbit-research-experiments"] as const,
    upbitResearchMaExitForwardShadowSummary: (ubaId?: number) =>
      ["admin", "upbit-research-ma-exit-forward-shadow-summary", ubaId ?? null] as const,
    upbitResearchMaExitForwardShadowRows: (ubaId?: number) =>
      ["admin", "upbit-research-ma-exit-forward-shadow-rows", ubaId ?? null] as const,
    upbitResearchEntrySignalShadowSummary: (ubaId?: number) =>
      ["admin", "upbit-research-entry-signal-shadow-summary", ubaId ?? null] as const,
    upbitResearchEntrySignalShadowRows: (ubaId?: number) =>
      ["admin", "upbit-research-entry-signal-shadow-rows", ubaId ?? null] as const,
    upbitDualLlmStatus: () => ["admin", "upbit-dual-llm-status"] as const,
    upbitDualLlmRecent: (params?: object) =>
      ["admin", "upbit-dual-llm-recent", params ?? {}] as const,
    upbitDualLlmComparison: () =>
      ["admin", "upbit-dual-llm-comparison"] as const,
    upbitDualLlmRagFeedback: (params?: object) =>
      ["admin", "upbit-dual-llm-rag-feedback", params ?? {}] as const,
    upbitDualLlmRagFeedbackDetail: (analysisId: number) =>
      ["admin", "upbit-dual-llm-rag-feedback-detail", analysisId] as const,
    kiwoomDualLlmStatus: () => ["admin", "kiwoom-dual-llm-status"] as const,
    kiwoomDualLlmRecent: (params?: object) =>
      ["admin", "kiwoom-dual-llm-recent", params ?? {}] as const,
    kiwoomDualLlmRagFeedback: (params?: object) =>
      ["admin", "kiwoom-dual-llm-rag-feedback", params ?? {}] as const,
    kiwoomDualLlmRagFeedbackDetail: (analysisId: number) =>
      ["admin", "kiwoom-dual-llm-rag-feedback-detail", analysisId] as const,
    llmLearningSummary: (market?: string) =>
      ["admin", "llm-learning-summary", market ?? "ALL"] as const,
    llmLearningSamples: (market: string) =>
      ["admin", "llm-learning-samples", market] as const,
    llmLearningStages: (market?: string) =>
      ["admin", "llm-learning-stages", market ?? "ALL"] as const,
    llmLearningQuality: (market?: string) =>
      ["admin", "llm-learning-quality", market ?? "ALL"] as const,
    llmLearningTeacherReviews: (market?: string, params?: object) =>
      ["admin", "llm-learning-teacher", market ?? "ALL", params ?? {}] as const,
    llmLearningForwardShadow: () =>
      ["admin", "llm-learning-forward-shadow"] as const,
    llmLearningLoraReadiness: (market?: string) =>
      ["admin", "llm-learning-lora", market ?? "ALL"] as const,
    llmLearningComments: (market?: string) =>
      ["admin", "llm-learning-comments", market ?? "ALL"] as const,
    upbitNewsCollector: () => ["admin", "upbit-news-collector"] as const,
    upbitNewsCollectorRecent: () =>
      ["admin", "upbit-news-collector-recent"] as const,
    upbitNewsAnalysis: () => ["admin", "upbit-news-analysis"] as const,
    upbitNewsAnalysisRecent: () =>
      ["admin", "upbit-news-analysis-recent"] as const,
    upbitNewsSignals: () => ["admin", "upbit-news-signals"] as const,
    upbitNewsSignalsRecent: () =>
      ["admin", "upbit-news-signals-recent"] as const,
    upbitNewsSignalsStats: () =>
      ["admin", "upbit-news-signals-stats"] as const,
    upbitCombinedShadow: () =>
      ["admin", "upbit-combined-shadow"] as const,
    upbitCombinedShadowRecent: () =>
      ["admin", "upbit-combined-shadow-recent"] as const,
    upbitCombinedShadowStats: () =>
      ["admin", "upbit-combined-shadow-stats"] as const,
    marketQuality: () => ["admin", "market-quality"] as const,
    orderOutbox: () => ["admin", "order-outbox"] as const,
    liveTransitionHistory: () => ["admin", "live-transition-history"] as const,
    liveTransitionActive: () => ["admin", "live-transition-active"] as const,
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
    ollamaRoleModels: () => ["admin", "ollama-role-models"] as const,
    opsDbStatus: () => ["admin", "ops-db-status"] as const,
    opsMigration: () => ["admin", "ops-migration"] as const,
    opsBackup: () => ["admin", "ops-backup"] as const,
    opsDashboardOverview: () =>
      ["admin", "ops-dashboard", "overview"] as const,
    opsDashboardAccounts: (params?: object) =>
      ["admin", "ops-dashboard", "accounts", params ?? {}] as const,
    opsDashboardSchedulers: () =>
      ["admin", "ops-dashboard", "schedulers"] as const,
    opsDashboardRuntimes: () =>
      ["admin", "ops-dashboard", "runtimes"] as const,
    opsDashboardRisk: () => ["admin", "ops-dashboard", "risk"] as const,
    opsDashboardOrders: (params?: object) =>
      ["admin", "ops-dashboard", "orders", params ?? {}] as const,
    opsDashboardPositions: () =>
      ["admin", "ops-dashboard", "positions"] as const,
    opsDashboardAlerts: () => ["admin", "ops-dashboard", "alerts"] as const,
    opsDashboardAudits: (params?: object) =>
      ["admin", "ops-dashboard", "audits", params ?? {}] as const,
    opsDashboardNotifications: () =>
      ["admin", "ops-dashboard", "notifications"] as const,
    opsTables: (schema: string) => ["admin", "ops-tables", schema] as const,
    dartDisclosures: (params?: object) =>
      ["admin", "dart-disclosures", params ?? {}] as const,
    logsAudit: (params?: object) =>
      ["admin", "logs-audit", params ?? {}] as const,
    indicatorParameters: (params?: object) =>
      ["admin", "indicator-parameters", params ?? {}] as const,
    memberCleanupCandidates: (params?: object) =>
      ["admin", "member-cleanup-candidates", params ?? {}] as const,
    docsList: () => ["admin", "docs-list"] as const,
    docDetail: (slug: string) => ["admin", "doc", slug] as const,
  },
  mobile: {
    overview: () => ["mobile", "overview"] as const,
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
    riskSettings: () => ["user", "risk-settings"] as const,
    liveOrderStatus: () => ["user", "live-order-status"] as const,
    accountRiskSettings: (ubaId: number) =>
      ["user", "account-risk-settings", ubaId] as const,
    ownedStrategies: (scope?: string) =>
      ["user", "owned-strategies", scope ?? "all"] as const,
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
    accountStrategyPerformance: (accountId: number, params?: object) =>
      ["user", "account-strategy-performance", accountId, params ?? {}] as const,
    accountStrategyTrades: (
      accountId: number,
      strategyKey: string,
      params?: object,
    ) =>
      [
        "user",
        "account-strategy-trades",
        accountId,
        strategyKey,
        params ?? {},
      ] as const,
    paperOrders: (params?: object) =>
      ["user", "paper-orders", params ?? {}] as const,
    topCandidates: (ex: string) => ["user", "top-candidates", ex] as const,
    latestCandidates: (ex: string) => ["user", "latest-candidates", ex] as const,
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
    // STEP12-1 — Strategy Request 승인 게이트(내 요청)
    strategyRequests: {
      list: (params?: object) =>
        ["user", "strategy-requests", "list", params ?? {}] as const,
      detail: (id: number) =>
        ["user", "strategy-requests", "detail", id] as const,
      candidateLifecycle: (candidateId: number) =>
        ["user", "ai-candidate-lifecycle", candidateId] as const,
    },
    // STEP12-2-1 — Strategy Draft 조회(내 요청, 읽기 전용)
    strategyDrafts: {
      list: (params?: object) =>
        ["user", "strategy-drafts", "list", params ?? {}] as const,
      detail: (id: number) =>
        ["user", "strategy-drafts", "detail", id] as const,
    },
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
    // STEP 8-5-13 — KRX Session Timeline Phase
    marketSessionStatus: (exchangeCode = "KRX") =>
      ["user", "market-session-status", exchangeCode] as const,
  },
};
