"use client";

/**
 * UPBIT 자동매매 설정 워크스페이스 (6탭).
 * PORTFOLIO Enable 자동 호출·REAL 주문·페이지 로드 시 risk mutate 금지.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { snapshotFromOpsStatus } from "@/features/admin/accounts/upbit24x7StackOrchestrator";
import { UpbitPortfolioPolicyPanel } from "@/features/admin/upbit/UpbitPortfolioPolicyPanel";
import {
  PORTFOLIO_POLICY_CONFIRM_TEXT,
  validatePolicyFormValues,
} from "@/features/admin/upbit/upbitPortfolioPolicyHelpers";
import { UpbitOneClickAutotradingControl } from "@/features/admin/autotrading/UpbitOneClickAutotradingControl";
import { UpbitResearchCollectionSummaryCard } from "@/features/admin/upbit/UpbitResearchCollectionSummaryCard";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

import {
  CONSERVATIVE_PORTFOLIO_DEFAULTS,
  CONFIRM_DISABLE_PORTFOLIO,
  CONFIRM_ENABLE_PORTFOLIO,
  DEFAULT_UPBIT_AUTOTRADING_UBA_ID,
  formatUpbitAutotradingModeLabel,
  resolvePortfolioEnableControl,
  resolveStrategyIdFromSources,
  UPBIT_AUTOTRADING_EMPTY_LABELS,
  UPBIT_AUTOTRADING_TAB_KEYS,
  UPBIT_AUTOTRADING_TAB_LABELS,
  UPBIT_AUTOTRADING_TAB_ORDER,
} from "./upbitAutotradingSettingsConfig";
import { UpbitOpsStatusPanel } from "./UpbitOpsStatusPanel";
import { UpbitUnattendedAutoRenewPanel } from "./UpbitUnattendedAutoRenewPanel";
import { entryBlockReasonKo } from "@/features/admin/autotrading/entryBlockReasonKo";
import {
  slotStatusLabelKo,
  slotStatusTooltipKo,
} from "@/features/admin/autotrading/slotStatusLabels";

type Props = {
  ubaId: number;
  onUbaIdChange: (next: number) => void;
};

/** 로딩/에러 시 null 중첩 접근 방지 */
function asObj(value: unknown): Record<string, unknown> {
  return asRecord(value) ?? {};
}

function pctLabel(value: unknown, digits = 0): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

function numOrDash(value: unknown): string {
  if (value == null || value === "") return "—";
  return String(value);
}

export function UpbitAutotradingSettingsWorkspace({
  ubaId,
  onUbaIdChange,
}: Props) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [capitalForm] = Form.useForm();
  const [entryForm] = Form.useForm();
  const [safetyForm] = Form.useForm();
  const [activeTab, setActiveTab] = useState<string>(
    UPBIT_AUTOTRADING_TAB_KEYS.market,
  );
  const [enableOpen, setEnableOpen] = useState(false);
  const [previewResult, setPreviewResult] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [previewSymbol, setPreviewSymbol] = useState("KRW-ETH");
  const [previewAvailable, setPreviewAvailable] = useState(500_000);
  const [previewMaxOrder, setPreviewMaxOrder] = useState(10_000);

  const accountsQuery = useQuery({
    queryKey: ["admin", "broker-accounts", "UPBIT", "autotrading-settings"],
    queryFn: () =>
      adminApi.listAdminBrokerAccounts({
        broker_code: "UPBIT",
        include_inactive: false,
        include_test_accounts: false,
        enrich: false,
        limit: 100,
      }),
  });

  const opsQuery = useQuery({
    queryKey: ["admin", "uba-ops-status", ubaId],
    queryFn: () => adminApi.getAdminUbaOpsStatus(ubaId),
    enabled: ubaId > 0,
    refetchInterval: 30_000,
    staleTime: 20_000,
  });

  // 현황/자금 탭에서만 폴링 — 숨은 탭 eager fetch 제거
  const fullMarketQuery = useQuery({
    queryKey: ["admin", "uba-full-market", ubaId],
    queryFn: () => adminApi.getAdminUbaFullMarketStatus(ubaId),
    enabled:
      ubaId > 0 &&
      (activeTab === UPBIT_AUTOTRADING_TAB_KEYS.market ||
        activeTab === UPBIT_AUTOTRADING_TAB_KEYS.capital),
    refetchInterval: 30_000,
  });

  const portfolioQuery = useQuery({
    queryKey: ["admin", "uba-portfolio", ubaId],
    queryFn: () => adminApi.getAdminUbaPortfolioStatus(ubaId),
    enabled:
      ubaId > 0 &&
      (activeTab === UPBIT_AUTOTRADING_TAB_KEYS.market ||
        activeTab === UPBIT_AUTOTRADING_TAB_KEYS.capital ||
        activeTab === UPBIT_AUTOTRADING_TAB_KEYS.entry),
    refetchInterval: 30_000,
  });

  const readinessQuery = useQuery({
    queryKey: ["admin", "autotrading-readiness", ubaId],
    queryFn: () => adminApi.getAdminUbaAutotradingReadiness(ubaId),
    enabled:
      ubaId > 0 &&
      (activeTab === UPBIT_AUTOTRADING_TAB_KEYS.market ||
        activeTab === UPBIT_AUTOTRADING_TAB_KEYS.safety),
    refetchInterval: 30_000,
  });

  const ownershipQuery = useQuery({
    queryKey: ["admin", "symbol-ownership", ubaId, "UPBIT"],
    queryFn: () => adminApi.listAdminSymbolOwnership(ubaId, "UPBIT"),
    enabled:
      ubaId > 0 &&
      (activeTab === UPBIT_AUTOTRADING_TAB_KEYS.market ||
        activeTab === UPBIT_AUTOTRADING_TAB_KEYS.capital),
    refetchInterval: 60_000,
  });

  const ownershipBySymbol = useMemo(() => {
    const map = new Map<string, string>();
    const root = asObj(ownershipQuery.data);
    const items = Array.isArray(root.items) ? root.items : [];
    for (const raw of items) {
      const r = asObj(raw);
      const sym = String(r.symbol ?? "").toUpperCase();
      if (sym) map.set(sym, String(r.owner ?? "").toUpperCase());
    }
    return map;
  }, [ownershipQuery.data]);

  const opsSnap = opsQuery.data ? snapshotFromOpsStatus(opsQuery.data) : null;
  const strategyIdNum = resolveStrategyIdFromSources({
    portfolio: portfolioQuery.data,
    fullMarket: fullMarketQuery.data,
    ops: opsQuery.data,
  });
  const invalidateOps = () => {
    void queryClient.invalidateQueries({
      queryKey: ["admin", "uba-ops-status", ubaId],
    });
    void queryClient.invalidateQueries({
      queryKey: ["admin", "autotrading-readiness", ubaId],
    });
  };
  const opsRoot = asObj(opsQuery.data);
  const fmFromOps = asObj(opsRoot.full_market);
  const scanner = asObj(opsRoot.scanner);
  const fm = { ...fmFromOps, ...asObj(fullMarketQuery.data) };
  const portfolio = asObj(portfolioQuery.data);
  const policy = asObj(portfolio.policy);
  const summary = asObj(portfolio.summary);
  const slots = (Array.isArray(portfolio.slots) ? portfolio.slots : []).filter(
    (row): row is Record<string, unknown> =>
      row != null && typeof row === "object" && !Array.isArray(row),
  );
  const modeRaw = String(
    portfolio.mode ?? fm.mode ?? "FIXED_SYMBOL",
  ).toUpperCase();
  const modeLabel = formatUpbitAutotradingModeLabel(modeRaw);
  const aiGate = String(fm.ai_live_gate_mode ?? "ENFORCE").toUpperCase();
  const fmLatest = asObj(fullMarketQuery.data).latest_recommendations;
  const candidates = Array.isArray(scanner.candidates)
    ? scanner.candidates
    : Array.isArray(fmLatest)
      ? fmLatest
      : [];

  const ubaOptions = useMemo(() => {
    const root = asObj(accountsQuery.data);
    const items = Array.isArray(root.items)
      ? root.items
      : Array.isArray(accountsQuery.data)
        ? (accountsQuery.data as unknown[])
        : [];
    const opts = items
      .map((row) => {
        const r = asObj(row);
        const id = Number(r.user_broker_account_id ?? r.id ?? 0);
        if (!id) return null;
        const alias = String(r.account_alias ?? r.alias ?? "").trim();
        return {
          value: id,
          label: alias ? `UBA ${id} · ${alias}` : `UBA ${id}`,
        };
      })
      .filter((x): x is { value: number; label: string } => x != null);
    if (!opts.some((o) => o.value === DEFAULT_UPBIT_AUTOTRADING_UBA_ID)) {
      opts.unshift({
        value: DEFAULT_UPBIT_AUTOTRADING_UBA_ID,
        label: `UBA ${DEFAULT_UPBIT_AUTOTRADING_UBA_ID}`,
      });
    }
    return opts;
  }, [accountsQuery.data]);

  const capitalInitial = useMemo(() => {
    const policy = asObj(asObj(portfolioQuery.data).policy);
    return {
      portfolio_capital_limit_krw:
        policy.portfolio_capital_limit_krw != null
          ? Number(policy.portfolio_capital_limit_krw)
          : undefined,
      per_position_target_pct: Number(policy.per_position_target_pct ?? 0.08),
      max_symbol_exposure_pct: Number(policy.max_symbol_exposure_pct ?? 0.12),
      max_total_exposure_pct: Number(policy.max_total_exposure_pct ?? 0.3),
      min_cash_reserve_pct: Number(policy.min_cash_reserve_pct ?? 0.6),
      portfolio_max_pending_entries: Number(
        policy.portfolio_max_pending_entries ?? 1,
      ),
      allow_averaging_down: Boolean(policy.allow_averaging_down),
      allow_duplicate_symbol: Boolean(policy.allow_duplicate_symbol),
    };
  }, [portfolioQuery.data]);

  const entryInitial = useMemo(() => {
    const policy = asObj(asObj(portfolioQuery.data).policy);
    return {
      max_positions: Number(policy.max_positions ?? 3),
      entry_signal_policy: String(
        policy.entry_signal_policy ?? "BULLISH_STATE",
      ).toUpperCase(),
      short_ma_window: Number(policy.short_ma_window ?? 5),
      long_ma_window: Number(policy.long_ma_window ?? 20),
      min_ma_separation_pct: Number(policy.min_ma_separation_pct ?? 0.05),
      rsi_max: Number(policy.rsi_max ?? 70),
      min_volume_surge: Number(policy.min_volume_surge ?? 0.8),
      require_ai_allow: Boolean(policy.require_ai_allow ?? true),
      entry_cooldown_seconds: Number(policy.entry_cooldown_seconds ?? 300),
      exit_min_ma_separation_pct: Number(
        policy.exit_min_ma_separation_pct ?? 0.03,
      ),
      ma_exit_min_holding_seconds: Number(
        policy.ma_exit_min_holding_seconds ?? 180,
      ),
      candidate_max_age_seconds: Number(
        policy.candidate_max_age_seconds ?? 1800,
      ),
      candidate_hold_seconds: Number(policy.candidate_hold_seconds ?? 1800),
      candidate_max_wait_seconds: Number(
        policy.candidate_max_wait_seconds ?? 10800,
      ),
      candidate_switch_min_score_delta: Number(
        policy.candidate_switch_min_score_delta ?? 8,
      ),
      portfolio_daily_entry_limit: Number(
        policy.portfolio_daily_entry_limit ?? 6,
      ),
      portfolio_daily_entry_limit_mode: String(
        policy.portfolio_daily_entry_limit_mode ?? "LIMITED",
      ).toUpperCase(),
      realtime_monitored_symbol_target:
        policy.realtime_monitored_symbol_target == null
          ? 5
          : Number(policy.realtime_monitored_symbol_target),
      consecutive_loss_limit: Number(policy.consecutive_loss_limit ?? 3),
    };
  }, [portfolioQuery.data]);

  const safetyInitial = useMemo(() => {
    const policy = asObj(asObj(portfolioQuery.data).policy);
    return {
      daily_loss_limit_pct: Number(policy.daily_loss_limit_pct ?? 0.02),
      consecutive_loss_limit: Number(policy.consecutive_loss_limit ?? 3),
    };
  }, [portfolioQuery.data]);

  // Form이 탭에 묶여 있으므로 forceRender 전에는 setFieldsValue 하지 않음
  const formsReady =
    portfolioQuery.isFetched || portfolioQuery.isError;

  useEffect(() => {
    if (!formsReady) return;
    capitalForm.setFieldsValue(capitalInitial);
  }, [capitalForm, capitalInitial, formsReady]);

  useEffect(() => {
    if (!formsReady) return;
    entryForm.setFieldsValue(entryInitial);
  }, [entryForm, entryInitial, formsReady]);

  useEffect(() => {
    if (!formsReady) return;
    safetyForm.setFieldsValue(safetyInitial);
  }, [safetyForm, safetyInitial, formsReady]);

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["admin", "uba-portfolio", ubaId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["admin", "uba-full-market", ubaId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["admin", "uba-ops-status", ubaId],
      }),
    ]);
  };

  const savePolicyMut = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      adminApi.patchAdminUbaPortfolioPolicy(ubaId, body),
    onSuccess: async (res) => {
      const row = asObj(res);
      const warnings = Array.isArray(row.warnings) ? row.warnings : [];
      if (warnings.length) {
        message.warning(`저장됨 · Risk 완화 경고: ${warnings.join(", ")}`);
      } else {
        message.success("포트폴리오 정책 저장");
      }
      await invalidate();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const confirmSavePolicy = (values: Record<string, unknown>) => {
    const validationError = validatePolicyFormValues(values);
    if (validationError) {
      message.error(validationError);
      return;
    }
    modal.confirm({
      title: "설정 저장",
      content: PORTFOLIO_POLICY_CONFIRM_TEXT,
      okText: "설정 저장",
      onOk: () => savePolicyMut.mutateAsync(values),
    });
  };

  const drySelectMut = useMutation({
    mutationFn: () => adminApi.drySelectAdminUbaFullMarket(ubaId, {}),
    onSuccess: (data) => {
      const row = asObj(data);
      const sel = asObj(row.selected);
      if (row.ok) {
        message.success(
          `Dry select: ${String(sel.symbol ?? "")} rank=#${String(sel.rank ?? "")}`,
        );
      } else {
        message.warning(`Dry select: ${String(row.reason ?? "NO_SELECTION")}`);
      }
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const dryTopKMut = useMutation({
    mutationFn: () =>
      adminApi.dryTopKAdminUbaPortfolio(ubaId, {
        scanner_run_id: "ui-settings-dry-topk",
        available_krw: previewAvailable,
        account_max_order_amount: previewMaxOrder,
      }),
    onSuccess: (res) => {
      const row = asObj(res);
      message.info(
        `Dry Top-K: ${String(row.reason ?? "ok")} reserved=${JSON.stringify(row.reserved ?? [])}`,
      );
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const enablePortfolioMut = useMutation({
    mutationFn: () =>
      adminApi.enableAdminUbaPortfolio(ubaId, {
        confirmation_text: CONFIRM_ENABLE_PORTFOLIO,
        strategy_id:
          Number(fm.strategy_id ?? portfolio.strategy_id ?? 0) || undefined,
        deployment_id:
          Number(fm.deployment_id ?? portfolio.deployment_id ?? 0) || undefined,
        template_symbol: String(
          fm.template_symbol ?? fm.current_symbol ?? "KRW-XRP",
        ),
        max_positions: Number(policy.max_positions ?? 3),
        portfolio_capital_limit_krw:
          policy.portfolio_capital_limit_krw != null
            ? Number(policy.portfolio_capital_limit_krw)
            : undefined,
      }),
    onSuccess: async () => {
      message.success("FULL_MARKET_PORTFOLIO enabled (강제 주문 없음)");
      setEnableOpen(false);
      await invalidate();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const disablePortfolioMut = useMutation({
    mutationFn: () =>
      adminApi.disableAdminUbaPortfolio(ubaId, {
        confirmation_text: CONFIRM_DISABLE_PORTFOLIO,
        fallback_mode: "FULL_MARKET_SINGLE",
      }),
    onSuccess: async () => {
      message.success("PORTFOLIO 중지 → FULL_MARKET_SINGLE (강제 청산 없음)");
      await invalidate();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const previewMut = useMutation({
    mutationFn: () =>
      adminApi.previewAdminUbaPortfolioSizing(ubaId, {
        symbol: previewSymbol,
        available_krw: previewAvailable,
        account_max_order_amount: previewMaxOrder,
      }),
    onSuccess: (res) => {
      setPreviewResult(asObj(res));
      message.success("Sizing Preview 완료 (주문 없음)");
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const applyConservativeToForms = () => {
    capitalForm.setFieldsValue({
      max_positions: CONSERVATIVE_PORTFOLIO_DEFAULTS.max_positions,
      portfolio_capital_limit_krw:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.portfolio_capital_limit_krw,
      per_position_target_pct:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.per_position_target_pct,
      max_symbol_exposure_pct:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.max_symbol_exposure_pct,
      max_total_exposure_pct:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.max_total_exposure_pct,
      min_cash_reserve_pct:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.min_cash_reserve_pct,
      portfolio_max_pending_entries:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.portfolio_max_pending_entries,
      allow_averaging_down:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.allow_averaging_down,
      allow_duplicate_symbol:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.allow_duplicate_symbol,
    });
    entryForm.setFieldsValue({
      entry_cooldown_seconds:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.entry_cooldown_seconds,
      candidate_max_age_seconds:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.candidate_max_age_seconds,
      candidate_hold_seconds:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.candidate_hold_seconds,
      candidate_max_wait_seconds:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.candidate_max_wait_seconds,
      candidate_switch_min_score_delta:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.candidate_switch_min_score_delta,
      portfolio_daily_entry_limit:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.portfolio_daily_entry_limit,
      consecutive_loss_limit:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.consecutive_loss_limit,
    });
    safetyForm.setFieldsValue({
      daily_loss_limit_pct:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.daily_loss_limit_pct,
      consecutive_loss_limit:
        CONSERVATIVE_PORTFOLIO_DEFAULTS.consecutive_loss_limit,
    });
    message.info("보수적 기본값을 폼에 채웠습니다. 저장은 별도 확인이 필요합니다.");
  };

  const riskFromOps = asObj(opsRoot.risk);
  const accountRisk = asObj(opsRoot.account_risk);
  const exitFromOps = asObj(opsRoot.exit ?? opsRoot.protective_exit);
  const unattended = asObj(opsRoot.unattended);
  const portfolioOn = modeLabel === "PORTFOLIO";
  const enableControl = resolvePortfolioEnableControl({
    portfolioOn,
    live: opsSnap?.live,
    arm: opsSnap?.arm,
    unattendedEnabled: opsSnap?.unattendedEnabled,
    unattendedRemainingSeconds: Number(unattended.remaining_seconds ?? 0),
    primaryBlocker: opsSnap?.primaryBlocker,
    killActive: Boolean(
      riskFromOps.kill_switch_active === true ||
        opsRoot.kill_switch === true ||
        String(opsRoot.kill_switch ?? "").toUpperCase() === "ON",
    ),
    conflictHighCritical: Number(
      asObj(opsRoot.conflicts).high_critical_count ??
        asObj(opsRoot.recovery).high_critical_count ??
        0,
    ),
  });

  const tabItems = UPBIT_AUTOTRADING_TAB_ORDER.map((key) => {
    const label = UPBIT_AUTOTRADING_TAB_LABELS[key];
    // 폼이 있는 탭은 비활성 시에도 마운트 — useForm 연결 경고 방지
    const forceRender =
      key === UPBIT_AUTOTRADING_TAB_KEYS.capital ||
      key === UPBIT_AUTOTRADING_TAB_KEYS.entry ||
      key === UPBIT_AUTOTRADING_TAB_KEYS.safety;
    if (key === UPBIT_AUTOTRADING_TAB_KEYS.market) {
      return {
        key,
        label,
        forceRender: false,
        children: (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <UpbitOpsStatusPanel
              ubaId={ubaId}
              ops={opsRoot}
              portfolio={portfolio}
              readiness={asObj(readinessQuery.data)}
              ownershipBySymbol={ownershipBySymbol}
            />
            <Alert
              type="info"
              showIcon
              title="모드 전환은 명시 버튼으로만. Dry Select/Top-K는 시뮬레이션이며 Enable과 다릅니다."
            />
            <Descriptions size="small" bordered column={2}>
              <Descriptions.Item label="MODE">
                <Tag
                  color={
                    modeLabel === "PORTFOLIO"
                      ? "orange"
                      : modeLabel === "SINGLE"
                        ? "blue"
                        : "default"
                  }
                >
                  {modeLabel} ({modeRaw})
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="PORTFOLIO">
                <Tag color={portfolioOn ? "orange" : "default"}>
                  {portfolioOn ? "ON" : "OFF"}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="UBA">{ubaId}</Descriptions.Item>
              <Descriptions.Item label="Broker">UPBIT REAL</Descriptions.Item>
              <Descriptions.Item label="TARGET">
                {String(fm.current_symbol ?? fm.template_symbol ?? "—")}
              </Descriptions.Item>
              <Descriptions.Item label="STATE">
                {String(fm.state ?? "IDLE")}
              </Descriptions.Item>
              <Descriptions.Item label="Max positions">
                {numOrDash(policy.max_positions ?? 3)}
              </Descriptions.Item>
              <Descriptions.Item label="동시 매수 처리">
                {numOrDash(
                  policy.max_concurrent_entries_effective
                    ?? policy.portfolio_max_pending_entries
                    ?? 1,
                )}
                {" / 2"}
              </Descriptions.Item>
              <Descriptions.Item label="Total exposure">
                {(Number(policy.max_total_exposure_pct ?? 0.3) * 100).toFixed(0)}
                %
              </Descriptions.Item>
              <Descriptions.Item label="Cash reserve">
                {(Number(policy.min_cash_reserve_pct ?? 0.6) * 100).toFixed(0)}%
              </Descriptions.Item>
              <Descriptions.Item label="LIVE / ARM">
                LIVE {opsSnap?.live ?? "—"} · ARM {opsSnap?.arm ?? "—"}
              </Descriptions.Item>
              <Descriptions.Item label="24H / STACK">
                24H {opsSnap?.unattendedEnabled ? "ON" : "OFF"} ·{" "}
                {opsSnap?.stackLabel ?? "—"}
              </Descriptions.Item>
              <Descriptions.Item label="AI GATE" span={2}>
                {aiGate}
              </Descriptions.Item>
              <Descriptions.Item label="SCANNER" span={2}>
                {numOrDash(scanner.universe_count)} →{" "}
                {numOrDash(scanner.liquidity_pass_count)} →{" "}
                {numOrDash(scanner.top_n)}
                {scanner.enabled != null
                  ? ` · enabled=${String(scanner.enabled)}`
                  : ""}
              </Descriptions.Item>
              <Descriptions.Item label="TOP 후보" span={2}>
                {candidates.length
                  ? candidates
                      .slice(0, 5)
                      .map((c) => {
                        const r = asObj(c);
                        return `${r.symbol}(${r.recommendation ?? r.score ?? "—"})`;
                      })
                      .join(" · ")
                  : "—"}
              </Descriptions.Item>
              <Descriptions.Item label="COOLDOWN">
                {String(fm.cooldown_until ?? "—")}
              </Descriptions.Item>
              <Descriptions.Item label="WARMUP">
                {fm.warmup_ready == null
                  ? "—"
                  : fm.warmup_ready
                    ? "READY"
                    : "NOT READY"}
              </Descriptions.Item>
            </Descriptions>
            <Space wrap>
              {enableControl.showEnable ? (
                <Tooltip
                  title={
                    enableControl.enableDisabled
                      ? `Enable 불가: ${enableControl.disableReasons.join(", ")}`
                      : "확인 후 FULL_MARKET_PORTFOLIO 시작"
                  }
                >
                  <Button
                    type="primary"
                    danger
                    disabled={enableControl.enableDisabled}
                    onClick={() => setEnableOpen(true)}
                  >
                    FULL MARKET PORTFOLIO 시작
                  </Button>
                </Tooltip>
              ) : null}
              {enableControl.showDisable ? (
                <Button
                  danger
                  loading={disablePortfolioMut.isPending}
                  onClick={() => {
                    modal.confirm({
                      title: "FULL MARKET PORTFOLIO 중지",
                      content: (
                        <Space orientation="vertical">
                          <Typography.Paragraph>
                            신규 ENTRY만 중지합니다. OPEN slot 강제 청산 없음 ·
                            protective EXIT 유지 · 자연 종료 후 SINGLE 전환.
                          </Typography.Paragraph>
                          <Typography.Text>
                            확인:{" "}
                            <Typography.Text code>
                              {CONFIRM_DISABLE_PORTFOLIO}
                            </Typography.Text>
                          </Typography.Text>
                        </Space>
                      ),
                      okText: "FULL MARKET PORTFOLIO 중지",
                      okButtonProps: { danger: true },
                      onOk: () => disablePortfolioMut.mutateAsync(),
                    });
                  }}
                >
                  FULL MARKET PORTFOLIO 중지
                </Button>
              ) : null}
              <Button
                loading={drySelectMut.isPending}
                onClick={() => drySelectMut.mutate()}
              >
                Dry Select
              </Button>
              <Button
                loading={dryTopKMut.isPending}
                onClick={() => dryTopKMut.mutate()}
              >
                Dry Top-K
              </Button>
            </Space>
            {enableControl.showEnable && enableControl.enableDisabled ? (
              <Alert
                type="warning"
                showIcon
                title={`Enable 버튼 표시 · 비활성: ${enableControl.disableReasons.join(", ")}`}
              />
            ) : null}
          </Space>
        ),
      };
    }

    if (key === UPBIT_AUTOTRADING_TAB_KEYS.capital) {
      return {
        key,
        label,
        forceRender,
        children: (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              title="자금·슬롯 설정. [보수적 설정 적용]은 폼만 채우며 자동 저장하지 않습니다."
            />
            <Form form={capitalForm} layout="vertical" initialValues={capitalInitial}>
              <Space wrap size={12}>
                <Form.Item
                  name="portfolio_capital_limit_krw"
                  label="자금 한도 (KRW)"
                >
                  <InputNumber min={0} step={10_000} style={{ width: 160 }} />
                </Form.Item>
                <Form.Item
                  name="per_position_target_pct"
                  label="포지션 목표 비중"
                >
                  <InputNumber min={0.01} max={1} step={0.01} />
                </Form.Item>
                <Form.Item
                  name="max_symbol_exposure_pct"
                  label="종목 노출 상한"
                >
                  <InputNumber min={0.01} max={1} step={0.01} />
                </Form.Item>
                <Form.Item
                  name="max_total_exposure_pct"
                  label="총 노출 상한"
                >
                  <InputNumber min={0.01} max={1} step={0.01} />
                </Form.Item>
                <Form.Item name="min_cash_reserve_pct" label="현금 예비 비중">
                  <InputNumber min={0} max={1} step={0.05} />
                </Form.Item>
                <Form.Item
                  name="portfolio_max_pending_entries"
                  label="동시 매수 처리 상한"
                  extra="동시에 진행할 수 있는 신규 매수 진입 수 (최대 2)"
                >
                  <InputNumber min={1} max={2} />
                </Form.Item>
                <Form.Item
                  name="allow_averaging_down"
                  label="물타기"
                  valuePropName="checked"
                >
                  <Switch checkedChildren="ON" unCheckedChildren="OFF" />
                </Form.Item>
                <Form.Item
                  name="allow_duplicate_symbol"
                  label="중복 심볼"
                  valuePropName="checked"
                >
                  <Switch checkedChildren="ON" unCheckedChildren="OFF" />
                </Form.Item>
              </Space>
            </Form>
            <Space wrap>
              <Button onClick={applyConservativeToForms}>
                보수적 설정 적용
              </Button>
              <Button
                type="primary"
                loading={savePolicyMut.isPending}
                onClick={async () => {
                  const values = await capitalForm.validateFields();
                  confirmSavePolicy(values);
                }}
              >
                포지션·자금 저장
              </Button>
            </Space>
            <Typography.Text strong>자동매매 후보 감시 슬롯</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
              매수 후보를 등록해 조건을 감시합니다. 빈 슬롯(후보 대기)은 오류가
              아니며 현재 적격 후보가 없다는 의미입니다.
            </Typography.Paragraph>
            <Table
              size="small"
              pagination={false}
              rowKey={(r) =>
                String(asObj(r).slot_id ?? asObj(r).slot_no)
              }
              dataSource={slots as Record<string, unknown>[]}
              columns={[
                { title: "슬롯", dataIndex: "slot_no", width: 56 },
                {
                  title: "종목",
                  dataIndex: "symbol",
                  render: (v) => v ?? "—",
                },
                {
                  title: "상태",
                  dataIndex: "status",
                  render: (v) => (
                    <Tooltip title={slotStatusTooltipKo(String(v))}>
                      <Tag>{slotStatusLabelKo(String(v))}</Tag>
                    </Tooltip>
                  ),
                },
                {
                  title: "점수",
                  dataIndex: "scanner_score",
                  width: 72,
                  render: (_: unknown, row) => {
                    const o = asObj(row);
                    const v = o.scanner_score ?? o.score;
                    return v == null ? "—" : String(v);
                  },
                },
                {
                  title: "AI 판단",
                  dataIndex: "ai_recommendation",
                  width: 88,
                  render: (v) => (v == null ? "—" : String(v)),
                },
                {
                  title: "매수 판단",
                  key: "entry_eval",
                  width: 120,
                  render: (_: unknown, row) => {
                    const o = asObj(row);
                    const d = o.last_entry_decision ?? o.entry_decision;
                    return d == null ? "—" : String(d);
                  },
                },
                {
                  title: "대기 이유",
                  key: "block_reason",
                  ellipsis: true,
                  render: (_: unknown, row) => {
                    const o = asObj(row);
                    const v =
                      o.last_entry_block_reason ?? o.entry_block_reason;
                    const mapped = entryBlockReasonKo(
                      v == null ? null : String(v),
                    );
                    if (!mapped.rawCode) return "—";
                    return (
                      <Tooltip title={`${mapped.detail} (${mapped.rawCode})`}>
                        <span>{mapped.label}</span>
                      </Tooltip>
                    );
                  },
                },
                {
                  title: "배정 금액",
                  dataIndex: "allocated_amount_krw",
                  render: (v) => (v == null ? "—" : String(v)),
                },
                {
                  title: "예상/예약 금액",
                  key: "amount_display",
                  render: (_: unknown, row) => {
                    const o = asObj(row);
                    const reserved = o.reserved_amount_krw;
                    const recommended = o.recommended_amount_krw;
                    const st = String(o.status ?? "").toUpperCase();
                    if (reserved != null) return `예약 ${String(reserved)}`;
                    if (st === "WAITING_SIGNAL" || st === "ENTRY_PENDING") {
                      if (recommended != null) {
                        return `예상 ${String(recommended)}`;
                      }
                    }
                    return "—";
                  },
                },
                {
                  title: "Cooldown",
                  dataIndex: "cooldown_until",
                  render: (v) => (v ? String(v) : "—"),
                },
              ]}
            />
          </Space>
        ),
      };
    }

    if (key === UPBIT_AUTOTRADING_TAB_KEYS.entry) {
      return {
        key,
        label,
        forceRender,
        children: (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <UpbitPortfolioPolicyPanel
              policy={policy}
              slots={slots as Record<string, unknown>[]}
              entryForm={entryForm}
              entryInitial={entryInitial}
              dailyEntry={asObj(summary.daily_entry)}
              dailyEntryLabelKo={
                summary.daily_entry_label_ko != null
                  ? String(summary.daily_entry_label_ko)
                  : null
              }
            />
            <Button
              type="primary"
              loading={savePolicyMut.isPending}
              onClick={async () => {
                const values = await entryForm.validateFields();
                confirmSavePolicy(values);
              }}
            >
              설정 저장
            </Button>
          </Space>
        ),
      };
    }

    if (key === UPBIT_AUTOTRADING_TAB_KEYS.exit) {
      const exitProtection = asObj(
        opsRoot.exit_protection ?? riskFromOps.resolved_exit_protection,
      );
      const exitPolicy = asObj(opsRoot.exit_policy);
      const exitShadow = asObj(opsRoot.exit_shadow);
      const sourceLabel = (source?: string | null) => {
        const s = String(source ?? "").toUpperCase();
        if (s === "UBA" || s === "ACCOUNT") return "UBA 명시 설정";
        if (s === "USER") return "사용자 설정";
        if (s === "SYSTEM") return "SYSTEM DEFAULT 상속";
        if (s === "STRATEGY") return "전략 설정";
        if (s === "POLICY") return "운영 정책";
        return s || "—";
      };
      const realLabel = (item: Record<string, unknown> | null, fallbackKey: string) => {
        const mode = String(item?.mode ?? exitPolicy[fallbackKey] ?? "").toUpperCase();
        const enabled = item?.effective_enabled === true || mode === "REAL" || mode === "ENABLED";
        if (mode === "DISABLED" || item?.effective_enabled === false) {
          return { text: "사용 안 함", color: "default" as const };
        }
        if (enabled) return { text: "사용 중", color: "green" as const };
        return { text: "미확인", color: "orange" as const };
      };
      const shadowLabel = (keyName: string) => {
        const v = String(exitShadow[keyName] ?? "ACTIVE").toUpperCase();
        return v === "ACTIVE" || v === "COLLECTING"
          ? { text: "수집 중", color: "blue" as const }
          : { text: v || "—", color: "default" as const };
      };
      const sl = asObj(exitProtection.stop_loss);
      const tp = asObj(exitProtection.take_profit);
      const tr = asObj(exitProtection.trailing_stop);
      const slReal = realLabel(sl, "STOP_LOSS");
      const tpReal = realLabel(tp, "TAKE_PROFIT");
      const trReal = realLabel(tr, "TRAILING");
      const slShadow = shadowLabel("STOP_LOSS");
      const tpShadow = shadowLabel("TAKE_PROFIT");
      const trShadow = shadowLabel("TRAILING");
      const timeShadow = shadowLabel("TIME_EXIT");

      return {
        key,
        label,
        children: (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              title="REAL 청산과 Shadow 연구는 분리됩니다. REAL 비활성이 Shadow 수집을 끄지 않습니다."
              description="NULL rate만으로 미설정을 판단하지 않습니다. mode=DISABLED면 SYSTEM DEFAULT가 있어도 REAL executor는 사용하지 않습니다."
            />
            <Descriptions size="small" bordered column={1}>
              <Descriptions.Item label="손절">
                <Space wrap>
                  <Tag color={slReal.color}>REAL: {slReal.text}</Tag>
                  <Tag color={slShadow.color}>Shadow: {slShadow.text}</Tag>
                  <Typography.Text type="secondary">
                    출처: {sourceLabel(String(sl.source ?? ""))}
                  </Typography.Text>
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="익절">
                <Space wrap>
                  <Tag color={tpReal.color}>REAL: {tpReal.text}</Tag>
                  <Tag color={tpShadow.color}>Shadow: {tpShadow.text}</Tag>
                  <Typography.Text type="secondary">
                    출처: {sourceLabel(String(tp.source ?? ""))}
                  </Typography.Text>
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="트레일링">
                <Space wrap>
                  <Tag color={trReal.color}>REAL: {trReal.text}</Tag>
                  <Tag color={trShadow.color}>Shadow: {trShadow.text}</Tag>
                  <Typography.Text type="secondary">
                    출처: {sourceLabel(String(tr.source ?? ""))}
                  </Typography.Text>
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="이동평균 데드크로스">
                <Tag color="green">REAL: 사용 중</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="최대 보유시간">
                <Space wrap>
                  <Tag>REAL: 사용 안 함</Tag>
                  <Tag color={timeShadow.color}>Shadow: {timeShadow.text}</Tag>
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="청산 감시">
                {opsSnap?.exitMonitor ?? "—"}
              </Descriptions.Item>
              <Descriptions.Item label="청산 후 쿨다운">
                {String(
                  exitFromOps.cooldown_after_exit ??
                    policy.entry_cooldown_seconds ??
                    "—",
                )}
                {policy.entry_cooldown_seconds != null ? "초 (진입 쿨다운 연동)" : ""}
              </Descriptions.Item>
            </Descriptions>

            <Card size="small" title="전략 청산 조건 (MA_DEAD_CROSS)">
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                title="손절/익절/트레일링 보호청산에는 적용되지 않습니다."
                description="짧은 MA 반전과 수수료 churn만 줄입니다. 손실이어도 confirmed dead-cross면 전략 청산은 가능합니다."
              />
              <Form form={entryForm} layout="vertical">
                <Space wrap size={12}>
                  <Form.Item
                    name="exit_min_ma_separation_pct"
                    label="MA Exit 최소 역전폭 (%)"
                  >
                    <InputNumber min={0} max={50} step={0.01} />
                  </Form.Item>
                  <Form.Item
                    name="ma_exit_min_holding_seconds"
                    label="MA Exit 최소 보유시간 (초)"
                  >
                    <InputNumber min={0} max={86400} step={30} />
                  </Form.Item>
                  <Form.Item
                    name="entry_cooldown_seconds"
                    label="동일종목 재진입 대기 (초)"
                  >
                    <InputNumber min={0} step={30} />
                  </Form.Item>
                </Space>
                <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
                  Entry 최소 MA 간격 {numOrDash(policy.min_ma_separation_pct)}%
                  와 비대칭 hysteresis. 재진입 대기는 기존 slot cooldown과 동일
                  SoT입니다.
                </Typography.Paragraph>
                <Button
                  type="primary"
                  loading={savePolicyMut.isPending}
                  onClick={async () => {
                    const values = await entryForm.validateFields([
                      "exit_min_ma_separation_pct",
                      "ma_exit_min_holding_seconds",
                      "entry_cooldown_seconds",
                    ]);
                    confirmSavePolicy(values);
                  }}
                >
                  전략 청산 조건 저장
                </Button>
              </Form>
            </Card>

            <Typography.Paragraph type="secondary">
              REAL SL/TP/Trailing 모드 변경은{" "}
              <Link href={adminRoutes.risk}>리스크 관리</Link>
              에서 설정합니다. Shadow 실험값은 Research 화면에서 확인합니다.
            </Typography.Paragraph>
          </Space>
        ),
      };
    }

    if (key === UPBIT_AUTOTRADING_TAB_KEYS.ai) {
      return {
        key,
        label,
        children: (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              title="AI Gate 표시만. FORCE ALLOW / Gate 강제 완화는 제공하지 않습니다."
            />
            <Descriptions size="small" bordered column={2}>
              <Descriptions.Item label="AI LIVE Gate">
                <Tag
                  color={
                    aiGate === "ENFORCE"
                      ? "green"
                      : aiGate === "SHADOW"
                        ? "blue"
                        : "default"
                  }
                >
                  {aiGate}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="AI State (ops)">
                {opsSnap?.aiState ?? "—"}
              </Descriptions.Item>
            </Descriptions>
            <Typography.Text strong>최근 추천 (Scanner / Full-Market)</Typography.Text>
            <Table
              size="small"
              pagination={false}
              rowKey={(r) => {
                const row = asObj(r);
                return [
                  String(row.symbol ?? "sym"),
                  String(row.rank ?? ""),
                  String(row.recommendation ?? ""),
                  String(row.score ?? ""),
                ].join("|");
              }}
              dataSource={candidates.slice(0, 10) as Record<string, unknown>[]}
              locale={{ emptyText: "추천 없음" }}
              columns={[
                {
                  title: "종목",
                  dataIndex: "symbol",
                  render: (v) => v ?? "—",
                },
                {
                  title: "AI 판단",
                  dataIndex: "recommendation",
                  render: (v) => <Tag>{String(v ?? "—")}</Tag>,
                },
                {
                  title: "점수",
                  dataIndex: "score",
                  render: (v) => numOrDash(v),
                },
                {
                  title: "신뢰도",
                  dataIndex: "confidence",
                  render: (v) => numOrDash(v),
                },
                {
                  title: "순위",
                  dataIndex: "rank",
                  render: (v) => numOrDash(v),
                },
              ]}
            />
          </Space>
        ),
      };
    }

    // safety
    return {
      key: UPBIT_AUTOTRADING_TAB_KEYS.safety,
      label: UPBIT_AUTOTRADING_TAB_LABELS.safety,
      forceRender,
      children: (
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="warning"
            showIcon
            title="계좌 Risk와 포트폴리오 Risk는 별개입니다"
            description="계좌 일손실/Kill Switch는 Account Risk SoT, 포트폴리오 daily/consecutive loss는 Portfolio Policy입니다. 완화 저장 시 RISK_RELAX_* 경고가 뜹니다."
          />
          <Descriptions size="small" bordered column={2}>
            <Descriptions.Item label="일손실 (ops/risk)">
              {numOrDash(
                riskFromOps.current_daily_loss ??
                  accountRisk.current_daily_loss ??
                  asObj(opsRoot.daily_loss).current,
              )}{" "}
              /{" "}
              {numOrDash(
                riskFromOps.max_daily_loss_limit ??
                  accountRisk.max_daily_loss_limit ??
                  asObj(opsRoot.daily_loss).limit,
              )}
            </Descriptions.Item>
            <Descriptions.Item label="포트폴리오 일손실 %">
              {pctLabel(policy.daily_loss_limit_pct, 1)}
            </Descriptions.Item>
            <Descriptions.Item label="연속 손실">
              {numOrDash(policy.consecutive_loss_count)} /{" "}
              {numOrDash(policy.consecutive_loss_limit)}
            </Descriptions.Item>
            <Descriptions.Item label="Kill / Recovery">
              {String(
                opsRoot.kill_switch ??
                  riskFromOps.kill_switch_active ??
                  opsSnap?.primaryBlocker ??
                  "NONE",
              )}
            </Descriptions.Item>
            <Descriptions.Item label="24H">
              {opsSnap?.unattendedEnabled
                ? `ON · ${opsSnap.unattendedRemainingLabel}`
                : "OFF"}
              {opsSnap?.unattendedAutoRenewEnabled ? " · 자동갱신 ON" : ""}
            </Descriptions.Item>
            <Descriptions.Item label="LIVE / ARM">
              LIVE {opsSnap?.live ?? "—"} · ARM {opsSnap?.arm ?? "—"}
            </Descriptions.Item>
            <Descriptions.Item label="Activation">
              {opsSnap?.activation ?? "—"}
            </Descriptions.Item>
            <Descriptions.Item label="Blockers">
              {(opsSnap?.blockers ?? []).length
                ? (opsSnap?.blockers ?? []).join(", ")
                : "NONE"}
            </Descriptions.Item>
          </Descriptions>
          <Form form={safetyForm} layout="vertical" initialValues={safetyInitial}>
            <Space wrap size={12}>
              <Form.Item
                name="daily_loss_limit_pct"
                label="포트폴리오 일손실 한도"
              >
                <InputNumber min={0.001} max={1} step={0.005} />
              </Form.Item>
              <Form.Item
                name="consecutive_loss_limit"
                label="연속 손실 한도"
              >
                <InputNumber min={1} max={50} />
              </Form.Item>
            </Space>
          </Form>
          <Button
            danger
            loading={savePolicyMut.isPending}
            onClick={async () => {
              const values = await safetyForm.validateFields();
              modal.confirm({
                title: "손실 제한 저장 (Risk 완화 주의)",
                content:
                  "한도를 완화하면 RISK_RELAX 경고가 납니다. 계좌 Kill Switch·Account Risk는 변경되지 않습니다.",
                okText: "저장",
                okButtonProps: { danger: true },
                onOk: () => savePolicyMut.mutateAsync(values),
              });
            }}
          >
            손실 제한 저장
          </Button>
        </Space>
      ),
    };
  });

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Space wrap align="center">
        <Typography.Text strong>UBA</Typography.Text>
        <Select
          style={{ minWidth: 220 }}
          value={ubaId}
          options={ubaOptions}
          loading={accountsQuery.isLoading}
          onChange={(v) => onUbaIdChange(Number(v))}
        />
        <Typography.Text type="secondary">
          쿼리 <Typography.Text code>?ubaId=</Typography.Text> 동기화 · 기본{" "}
          {DEFAULT_UPBIT_AUTOTRADING_UBA_ID}
        </Typography.Text>
      </Space>

      <Alert
        type="info"
        showIcon
        title="실계좌 포트폴리오 자동매매 설정"
        description={
          <Tooltip title="로드 시 risk mutate 없음 · PORTFOLIO Enable은 운영 정책에 따름">
            <span>화면을 열어도 리스크 설정이 자동으로 바뀌지 않습니다.</span>
          </Tooltip>
        }
      />

      <Card size="small" title="원클릭 자동매매">
        {strategyIdNum == null ? (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            title={UPBIT_AUTOTRADING_EMPTY_LABELS.noStrategy}
            description="portfolio/full-market 상태에 strategy_id가 없어도 정상일 수 있습니다. LIVE 전략 링크·PORTFOLIO Enable 후 다시 확인하세요."
          />
        ) : null}
        <UpbitOneClickAutotradingControl
          ubaId={ubaId}
          strategyId={strategyIdNum}
          needsReauthorize={Boolean(opsSnap?.needsReauthorize)}
          autoTradingRunning={
            String(opsSnap?.autoTradingState ?? "").toUpperCase() === "RUNNING"
          }
          onDone={invalidateOps}
        />
      </Card>

      <UpbitUnattendedAutoRenewPanel
        ubaId={ubaId}
        opsSnap={opsSnap}
        unattendedPayload={unattended}
        onChanged={invalidateOps}
      />

      <Alert
        type="warning"
        showIcon
        title="역할 구분: 이 화면은 UBA별 LIVE Portfolio 운영 정책입니다"
        description={
          <>
            Provider/Prompt/Policy 등 전역 전략·AI 시스템 설정은{" "}
            <Link href={adminRoutes.aiProviders}>전략·분석 → AI 설정</Link>
            에서 관리합니다. 연구·후보·검증은{" "}
            <Link href={adminRoutes.researchData}>연구 데이터</Link>
            ·{" "}
            <Link href={adminRoutes.strategyCandidates}>전략·후보</Link>
            를 사용하세요. 여기서는 계좌(UBA) LIVE 자동매매 정책만 다룹니다.
          </>
        }
      />

      <Row gutter={[12, 12]}>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card size="small">
            <Typography.Text type="secondary">AUTO</Typography.Text>
            <div>
              <Tag>{opsSnap?.autoTradingState ?? "—"}</Tag>
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card size="small">
            <Typography.Text type="secondary">MODE</Typography.Text>
            <div>
              <Tag>{modeLabel}</Tag>
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card size="small">
            <Typography.Text type="secondary">24H</Typography.Text>
            <div>
              <Tag color={opsSnap?.unattendedEnabled ? "green" : "default"}>
                {opsSnap?.unattendedEnabled ? "ON" : "OFF"}
              </Tag>
              {opsSnap?.unattendedAutoRenewEnabled ? (
                <Tag color="blue" style={{ marginInlineStart: 4 }}>
                  Auto
                </Tag>
              ) : null}
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card size="small">
            <Typography.Text type="secondary">LIVE</Typography.Text>
            <div>
              <Tag color={opsSnap?.live === "ON" ? "green" : "default"}>
                {opsSnap?.live ?? "—"}
              </Tag>
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card size="small">
            <Typography.Text type="secondary">ARM</Typography.Text>
            <div>
              <Tag color={opsSnap?.arm === "ON" ? "green" : "default"}>
                {opsSnap?.arm ?? "—"}
              </Tag>
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card size="small">
            <Typography.Text type="secondary">STACK</Typography.Text>
            <div>
              <Tag>{opsSnap?.stackLabel ?? "—"}</Tag>
            </div>
          </Card>
        </Col>
      </Row>

      <UpbitResearchCollectionSummaryCard ubaId={ubaId} />

      <Descriptions size="small" bordered column={{ xs: 1, sm: 2, md: 3 }}>
        <Descriptions.Item label="Positions">
          {numOrDash(summary.positions_open ?? 0)} /{" "}
          {numOrDash(summary.max_positions ?? policy.max_positions ?? 3)}
        </Descriptions.Item>
        <Descriptions.Item label="Exposure">
          {summary.exposure_pct != null
            ? pctLabel(summary.exposure_pct, 1)
            : "—"}{" "}
          / {pctLabel(summary.max_total_exposure_pct ?? policy.max_total_exposure_pct ?? 0.3, 0)}
        </Descriptions.Item>
        <Descriptions.Item label="Cash Reserve">
          {pctLabel(
            summary.min_cash_reserve_pct ?? policy.min_cash_reserve_pct ?? 0.6,
            0,
          )}
        </Descriptions.Item>
        <Descriptions.Item label="Consecutive Loss">
          {numOrDash(policy.consecutive_loss_count)} /{" "}
          {numOrDash(policy.consecutive_loss_limit)}
        </Descriptions.Item>
        <Descriptions.Item label="ENTRY">
          {String(summary.entry_state ?? policy.entry_state ?? "—")}
        </Descriptions.Item>
        <Descriptions.Item label="Waiting Signal">
          {numOrDash(summary.candidates_waiting ?? 0)}
        </Descriptions.Item>
        <Descriptions.Item label="Pending Orders">
          {numOrDash(summary.pending_orders ?? 0)}
        </Descriptions.Item>
        <Descriptions.Item label="예약 금액(실제)">
          {summary.reserved_krw == null || Number(summary.reserved_krw) === 0
            ? "없음"
            : numOrDash(summary.reserved_krw)}
        </Descriptions.Item>
      </Descriptions>

      <Card size="small" title="Sizing Preview">
        <Space wrap style={{ marginBottom: 12 }}>
          <Select
            style={{ width: 140 }}
            value={previewSymbol}
            onChange={setPreviewSymbol}
            options={[
              { value: "KRW-ETH", label: "KRW-ETH" },
              { value: "KRW-BTC", label: "KRW-BTC" },
              { value: "KRW-XRP", label: "KRW-XRP" },
              { value: "KRW-SOL", label: "KRW-SOL" },
            ]}
          />
          <Space size={4}>
            <Typography.Text type="secondary">가용</Typography.Text>
            <InputNumber
              min={0}
              step={10_000}
              value={previewAvailable}
              onChange={(v) => setPreviewAvailable(Number(v ?? 0))}
            />
          </Space>
          <Space size={4}>
            <Typography.Text type="secondary">주문상한</Typography.Text>
            <InputNumber
              min={0}
              step={1_000}
              value={previewMaxOrder}
              onChange={(v) => setPreviewMaxOrder(Number(v ?? 0))}
            />
          </Space>
          <Button
            type="primary"
            loading={previewMut.isPending}
            onClick={() => previewMut.mutate()}
          >
            Preview 실행
          </Button>
        </Space>
        {previewResult ? (
          <Descriptions size="small" bordered column={2}>
            <Descriptions.Item label="종목">
              {String(previewResult.symbol ?? previewSymbol)}
            </Descriptions.Item>
            <Descriptions.Item label="권장 금액">
              {numOrDash(previewResult.recommended_amount_krw)}
            </Descriptions.Item>
            <Descriptions.Item label="승인 금액">
              {numOrDash(previewResult.approved_amount_krw)}
            </Descriptions.Item>
            <Descriptions.Item label="사유">
              {(Array.isArray(previewResult.clamp_reasons)
                ? previewResult.clamp_reasons
                : []
              ).join(" | ") || "—"}
            </Descriptions.Item>
          </Descriptions>
        ) : (
          <Typography.Text type="secondary">
            Preview를 실행하면 recommended / approved / clamp reasons가
            표시됩니다.
          </Typography.Text>
        )}
      </Card>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        destroyOnHidden={false}
        items={tabItems}
      />

      <Modal
        title="FULL MARKET PORTFOLIO 시작"
        open={enableOpen}
        onCancel={() => setEnableOpen(false)}
        okText="FULL MARKET PORTFOLIO 시작"
        okButtonProps={{
          danger: true,
          loading: enablePortfolioMut.isPending,
        }}
        onOk={() => enablePortfolioMut.mutateAsync()}
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          title="최대 3개 종목까지 자동으로 순차 진입할 수 있습니다. 강제 REAL 주문은 아닙니다."
        />
        <Typography.Paragraph>
          확인 문구(API audit):{" "}
          <Typography.Text code>{CONFIRM_ENABLE_PORTFOLIO}</Typography.Text>
        </Typography.Paragraph>
        <ul>
          <li>
            업비트 계좌 {ubaId} · REAL · 현재 모드 {modeLabel} ({modeRaw})
          </li>
          <li>
            target/current{" "}
            {String(fm.current_symbol ?? fm.template_symbol ?? "—")}
          </li>
          <li>max positions {String(policy.max_positions ?? 3)}</li>
          <li>
            capital limit{" "}
            {policy.portfolio_capital_limit_krw != null
              ? String(policy.portfolio_capital_limit_krw)
              : "미설정(보수 비율)"}
          </li>
          <li>
            per-position{" "}
            {(Number(policy.per_position_target_pct ?? 0.08) * 100).toFixed(0)}%
            · symbol max{" "}
            {(Number(policy.max_symbol_exposure_pct ?? 0.12) * 100).toFixed(0)}%
            · total{" "}
            {(Number(policy.max_total_exposure_pct ?? 0.3) * 100).toFixed(0)}%
          </li>
          <li>
            cash reserve{" "}
            {(Number(policy.min_cash_reserve_pct ?? 0.6) * 100).toFixed(0)}% ·
            daily loss{" "}
            {(Number(policy.daily_loss_limit_pct ?? 0.02) * 100).toFixed(0)}% ·
            consecutive {String(policy.consecutive_loss_limit ?? 3)}
          </li>
          <li>
            averaging{" "}
            {policy.allow_averaging_down ? "ON" : "OFF"} · duplicate{" "}
            {policy.allow_duplicate_symbol ? "ON" : "OFF"} · pending BUY=
            {String(policy.portfolio_max_pending_entries ?? 1)}
          </li>
          <li>
            LIVE {opsSnap?.live ?? "—"} · ARM {opsSnap?.arm ?? "—"} · 24H{" "}
            {opsSnap?.unattendedEnabled ? "ON" : "OFF"} ·{" "}
            {opsSnap?.stackLabel ?? "—"}
          </li>
        </ul>
      </Modal>
    </Space>
  );
}
