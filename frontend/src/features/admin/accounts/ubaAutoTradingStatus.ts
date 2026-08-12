/**
 * UBA 자동매매 readiness 응답 → 화면 표시 모델.
 * 조회 전용 — LIVE/ARM/Worker/Runtime 변경 없음.
 */

export type AutoTradingHeadline =
  | "READY"
  | "BLOCKED"
  | "RUNNING"
  | "PAUSED";

export type PassBlock = "PASS" | "BLOCK";

export type AiRecommendation = "ALLOW" | "HOLD" | "REDUCE" | "UNKNOWN";

export interface UbaAutoTradingViewModel {
  headline: AutoTradingHeadline;
  statusRaw: string;
  blockers: string[];
  warnings: string[];
  displayBlockers: string[];
  strategy: {
    strategyId: string;
    name: string;
    symbol: string;
    broker: string;
    strategyActive: boolean | null;
    linkActive: boolean | null;
    deploymentId: string;
    runtimeStatus: string;
  };
  marketFeed: {
    healthy: boolean;
    reason: string;
    hubStatus: string;
    connected: boolean | null;
    running: boolean | null;
    symbols: string[];
    latestPrice: string;
    lastReceivedAt: string;
    ageSeconds: string;
    stale: boolean | null;
  };
  aiAnalysis: {
    analysisId: string;
    analysisAt: string;
    fresh: boolean | null;
    recommendation: AiRecommendation;
    confidence: string;
    riskLevel: string;
    provider: string;
    model: string;
    reasons: string[];
    analysisStatus: string;
    trend: string;
    momentum: string;
    volatility: string;
    parseWarning: string;
    parseNormalizedFallback: boolean | null;
  };
  aiScheduler: {
    enabled: boolean | null;
    running: boolean | null;
    intervalSeconds: string;
    lastRun: string;
    lastSuccess: string;
    nextRun: string;
    successCount: string;
    failureCount: string;
  };
  aiGate: {
    paperOn: boolean | null;
    liveOn: boolean | null;
    failClosed: boolean | null;
    assumedResult: string;
    recommendation: AiRecommendation;
  };
  dailyRisk: {
    kstDate: string;
    dailyOrderCount: string;
    dailyOrderLimit: string;
    maxOrderAmount: string;
    dailyMaxOrderAmount: string;
    riskCountedOrderIds: string;
  };
  ops: {
    activationLabel: string;
    transitionId: string;
    expiresAt: string;
    remainingTtl: string;
    liveOn: boolean | null;
    armOn: boolean | null;
    armExpires: string;
    workerEnabled: boolean | null;
    workerRunning: boolean | null;
    pendingOutbox: string;
  };
  checklist: Array<{ label: string; result: PassBlock }>;
  finalLabel: "READY_FOR_AUTO_TRADING" | "BLOCKED";
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function str(value: unknown, fallback = "-"): string {
  if (value == null || value === "") return fallback;
  return String(value);
}

function boolOrNull(value: unknown): boolean | null {
  if (typeof value === "boolean") return value;
  return null;
}

function normalizeRecommendation(raw: unknown): AiRecommendation {
  const u = String(raw ?? "").toUpperCase();
  if (u === "ALLOW" || u === "BUY") return "ALLOW";
  if (u === "HOLD") return "HOLD";
  if (u === "REDUCE") return "REDUCE";
  return "UNKNOWN";
}

function humanizeBlocker(code: string, recommendation: AiRecommendation): string {
  const map: Record<string, string> = {
    LIVE_OFF: "LIVE OFF",
    ARM_OFF_OR_EXPIRED: "ARM OFF",
    ACTIVATION_INACTIVE: "ACTIVATION INACTIVE",
    MARKET_FEED_UNHEALTHY: "MARKET FEED UNHEALTHY",
    STRATEGY_REQUIRED: "STRATEGY REQUIRED",
    STRATEGY_LINK_INACTIVE: "STRATEGY LINK INACTIVE",
    STRATEGY_NOT_LIVE_APPROVED: "STRATEGY NOT APPROVED",
    RISK_POLICY_MISSING: "RISK POLICY MISSING",
    LIVE_OUTBOX_WORKER_DISABLED: "WORKER DISABLED",
    RUNTIME_BLOCKED: "RUNTIME BLOCKED",
    CONFLICT_ACTIVE: "CONFLICT ACTIVE",
    LIVE_NOT_APPROVED: "LIVE NOT APPROVED",
  };
  if (code === "AI_ANALYSIS_STALE_OR_MISSING") return "AI STALE";
  if (map[code]) return map[code];
  return code.replaceAll("_", " ");
}

function formatTtl(seconds: unknown): string {
  const n = Number(seconds);
  if (!Number.isFinite(n)) return "-";
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function gateAssumedResult(
  liveGateOn: boolean | null,
  recommendation: AiRecommendation,
): string {
  if (liveGateOn !== true) {
    return "LIVE_GATE_OFF (recommendation ignored for LIVE)";
  }
  if (recommendation === "ALLOW") return "AI_GATE_ALLOW";
  if (recommendation === "HOLD") return "AI_GATE_HOLD";
  if (recommendation === "REDUCE") return "AI_GATE_REDUCE";
  return "AI_GATE_UNKNOWN";
}

function passBlock(ok: boolean): PassBlock {
  return ok ? "PASS" : "BLOCK";
}

/** readiness JSON → 화면 ViewModel */
export function buildUbaAutoTradingViewModel(
  payload: unknown,
): UbaAutoTradingViewModel {
  const root = asRecord(payload);
  const checks = asRecord(root.checks);
  const blockers = asArray(root.blockers).map((x) => String(x));
  const warnings = asArray(root.warnings).map((x) => String(x));
  const statusRaw = str(root.status, "BLOCKED");

  const strategyLinks = asRecord(checks.strategy_links);
  const linkItems = asArray(strategyLinks.items).map(asRecord);
  const primaryLink =
    linkItems.find((row) => row.is_active && row.approved) ??
    linkItems.find((row) => row.is_active) ??
    linkItems[0] ??
    {};

  const runtime = asRecord(checks.runtime);
  const matching = asArray(runtime.matching).map(asRecord);
  const runtimeEntry = matching[0] ?? {};
  const runtimeStatus = str(
    runtime.status ?? runtimeEntry.status ?? root.runtime_status,
    "-",
  ).toUpperCase();

  const marketFeed = asRecord(checks.market_feed);
  const quoteWs = asRecord(marketFeed.quote_ws);
  const hub = asRecord(marketFeed.hub);
  const cacheHit = asRecord(marketFeed.cache_hit);

  const aiGate = asRecord(checks.ai_signal_gate);
  const marketContext = asRecord(checks.market_context);
  const latestAnalysis = asRecord(marketContext.latest_analysis);
  const latestFromGate = asRecord(aiGate.latest);
  const job = asRecord(marketContext.ai_analysis_job);

  const recommendation = normalizeRecommendation(
    latestAnalysis.recommendation ?? latestFromGate.recommendation,
  );
  const fresh =
    typeof latestAnalysis.fresh === "boolean"
      ? latestAnalysis.fresh
      : typeof aiGate.stale === "boolean"
        ? !aiGate.stale
        : null;

  const activation = asRecord(checks.activation);
  const live = asRecord(checks.live);
  const arm = asRecord(checks.arm);
  const worker = asRecord(checks.live_outbox_worker);
  const risk = asRecord(checks.risk);
  const pipeline = asRecord(checks.pipeline);

  const liveOn = boolOrNull(live.live_order_enabled);
  const armOn =
    boolOrNull(arm.armed) === true && boolOrNull(arm.expired) !== true
      ? true
      : boolOrNull(arm.armed) === false || boolOrNull(arm.expired) === true
        ? false
        : null;
  const liveGateOn = boolOrNull(aiGate.live_enabled);
  const paperGateOn =
    boolOrNull(aiGate.paper_active) ?? boolOrNull(aiGate.enabled);

  let headline: AutoTradingHeadline = "BLOCKED";
  if (statusRaw === "READY_FOR_AUTO_TRADING") {
    headline = runtimeStatus === "RUNNING" ? "RUNNING" : "READY";
  } else if (runtimeStatus === "PAUSED" && blockers.length === 0) {
    headline = "PAUSED";
  } else if (runtimeStatus === "RUNNING" && blockers.length === 0) {
    headline = "RUNNING";
  } else {
    headline = "BLOCKED";
  }

  const displayBlockers = [
    ...blockers.map((code) => humanizeBlocker(code, recommendation)),
  ];
  if (
    recommendation === "HOLD" &&
    !displayBlockers.some((x) => x.includes("AI HOLD"))
  ) {
    displayBlockers.unshift("AI HOLD");
  }
  if (
    fresh === false &&
    !displayBlockers.some((x) => x.includes("AI STALE") || x.includes("STALE"))
  ) {
    displayBlockers.push("AI STALE");
  }

  const activationOk = activation.ok === true;
  const feedOk = marketFeed.ok === true;
  const riskOk = risk.resolved === true;
  const strategyOk =
    Number(strategyLinks.approved_active_count ?? 0) > 0 ||
    Boolean(primaryLink.approved && primaryLink.is_active);
  const runtimeOk =
    ["READY", "RUNNING", "PAUSED"].includes(runtimeStatus) || strategyOk;
  const aiFreshOk = fresh === true;
  // Gate PASS = 설정 조회 가능(OFF도 정상 표시). LIVE Gate ON 강제 아님.
  const aiGateOk = !("error" in aiGate);
  const accountSafetyOk =
    pipeline.ops_ready === true ||
    (!asArray(pipeline.blockers).length && !("error" in pipeline));
  const liveOk = liveOn === true;
  const armOk = armOn === true;
  const workerOk =
    boolOrNull(worker.enabled) === true &&
    boolOrNull(worker.running) === true;
  const outboxOk = Number(checks.pending_live_outbox ?? 0) === 0;

  const checklist: Array<{ label: string; result: PassBlock }> = [
    { label: "Strategy", result: passBlock(strategyOk) },
    { label: "Runtime", result: passBlock(runtimeOk) },
    { label: "Daily Risk", result: passBlock(riskOk) },
    { label: "Activation", result: passBlock(activationOk) },
    { label: "Market Feed", result: passBlock(feedOk) },
    {
      label: "AI Analysis",
      result: passBlock(aiFreshOk && recommendation !== "UNKNOWN"),
    },
    { label: "AI Gate", result: passBlock(aiGateOk) },
    { label: "Account Safety", result: passBlock(Boolean(accountSafetyOk)) },
    { label: "LIVE", result: passBlock(liveOk) },
    { label: "ARM", result: passBlock(armOk) },
    { label: "Worker", result: passBlock(workerOk) },
    { label: "Outbox", result: passBlock(outboxOk) },
  ];

  const reasons = asArray(
    latestAnalysis.reasons ?? latestFromGate.reasons,
  ).map((x) => String(x));
  if (!reasons.length && latestAnalysis.summary) {
    reasons.push(String(latestAnalysis.summary));
  }

  const age =
    latestAnalysis.age_seconds ?? aiGate.age_seconds ?? marketFeed.age_seconds;

  return {
    headline,
    statusRaw,
    blockers,
    warnings,
    displayBlockers: Array.from(new Set(displayBlockers)),
    strategy: {
      strategyId: str(primaryLink.strategy_id ?? runtimeEntry.strategy_id),
      name: str(primaryLink.name ?? runtimeEntry.strategy_code),
      symbol: str(
        primaryLink.symbol ?? runtimeEntry.symbol ?? latestFromGate.symbol,
        "KRW-XRP",
      ),
      broker: str(
        runtimeEntry.broker_code ?? runtimeEntry.market_code ?? "UPBIT",
      ),
      strategyActive:
        typeof primaryLink.strategy_is_active === "boolean"
          ? primaryLink.strategy_is_active
          : null,
      linkActive:
        typeof primaryLink.is_active === "boolean"
          ? primaryLink.is_active
          : null,
      deploymentId: str(runtimeEntry.deployment_id),
      runtimeStatus,
    },
    marketFeed: {
      healthy: feedOk,
      reason: str(marketFeed.reason, feedOk ? "OK" : "UNHEALTHY"),
      hubStatus: str(hub.hub_status ?? hub.status, "-"),
      connected: boolOrNull(quoteWs.connected),
      running: boolOrNull(quoteWs.running),
      symbols: asArray(marketFeed.symbols).map((x) => String(x)),
      latestPrice: str(
        cacheHit.trade_price ?? cacheHit.price ?? marketFeed.latest_price,
      ),
      lastReceivedAt: str(
        marketFeed.last_received_at ??
          cacheHit.received_at ??
          quoteWs.last_received_at,
      ),
      ageSeconds:
        age == null ? "-" : `${Math.round(Number(age))}s`,
      stale:
        typeof age === "number" && typeof marketFeed.stale_limit_seconds === "number"
          ? Number(age) > Number(marketFeed.stale_limit_seconds)
          : feedOk
            ? false
            : null,
    },
    aiAnalysis: {
      analysisId: str(
        latestAnalysis.market_analysis_id ??
          latestFromGate.market_analysis_id,
      ),
      analysisAt: str(
        latestAnalysis.analysis_at ?? latestFromGate.analysis_at,
      ),
      fresh,
      recommendation,
      confidence: str(
        latestAnalysis.confidence ?? latestFromGate.confidence,
      ),
      riskLevel: str(
        latestAnalysis.risk_level ?? latestFromGate.risk_level,
      ),
      provider: str(latestAnalysis.provider ?? latestFromGate.provider),
      model: str(latestAnalysis.model ?? latestFromGate.model),
      reasons,
      analysisStatus: str(
        latestAnalysis.analysis_status ?? latestFromGate.analysis_status,
      ),
      trend: str(latestAnalysis.trend ?? latestFromGate.trend),
      momentum: str(latestAnalysis.momentum ?? latestFromGate.momentum),
      volatility: str(
        latestAnalysis.volatility ?? latestFromGate.volatility,
      ),
      parseWarning: str(latestAnalysis.parse_warning),
      parseNormalizedFallback:
        typeof latestAnalysis.parse_normalized_fallback === "boolean"
          ? latestAnalysis.parse_normalized_fallback
          : null,
    },
    aiScheduler: {
      enabled: boolOrNull(job.enabled),
      running: boolOrNull(job.running),
      intervalSeconds: str(job.interval_seconds),
      lastRun: str(job.last_run_at),
      lastSuccess: str(job.last_success_at),
      nextRun: str(job.next_run_at),
      successCount: str(job.success_count, "0"),
      failureCount: str(job.failure_count, "0"),
    },
    aiGate: {
      paperOn: paperGateOn,
      liveOn: liveGateOn,
      failClosed: boolOrNull(aiGate.live_fail_closed),
      assumedResult: gateAssumedResult(liveGateOn, recommendation),
      recommendation,
    },
    dailyRisk: {
      kstDate: str(risk.kst_date),
      dailyOrderCount: str(risk.daily_order_count, "0"),
      dailyOrderLimit: str(risk.daily_order_limit),
      maxOrderAmount: str(risk.max_order_amount),
      dailyMaxOrderAmount: str(risk.daily_max_order_amount),
      riskCountedOrderIds: asArray(risk.risk_counted_order_ids).length
        ? asArray(risk.risk_counted_order_ids).join(", ")
        : "-",
    },
    ops: {
      activationLabel: activationOk
        ? str(activation.activation_status, "ACTIVE")
        : str(activation.activation_status, "INACTIVE"),
      transitionId: str(activation.transition_id),
      expiresAt: str(activation.expires_at),
      remainingTtl: formatTtl(activation.remaining_ttl_seconds),
      liveOn,
      armOn,
      armExpires: str(arm.expires_at),
      workerEnabled: boolOrNull(worker.enabled),
      workerRunning: boolOrNull(worker.running),
      pendingOutbox: str(checks.pending_live_outbox, "0"),
    },
    checklist,
    finalLabel:
      statusRaw === "READY_FOR_AUTO_TRADING"
        ? "READY_FOR_AUTO_TRADING"
        : "BLOCKED",
  };
}

export function recommendationBadgeColor(
  recommendation: AiRecommendation,
): string {
  if (recommendation === "ALLOW") return "green";
  if (recommendation === "HOLD") return "orange";
  if (recommendation === "REDUCE") return "gold";
  return "default";
}

export function headlineAlertType(
  headline: AutoTradingHeadline,
): "success" | "warning" | "error" | "info" {
  if (headline === "READY" || headline === "RUNNING") return "success";
  if (headline === "PAUSED") return "info";
  return "warning";
}
