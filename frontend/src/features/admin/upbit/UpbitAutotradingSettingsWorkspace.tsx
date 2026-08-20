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
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { snapshotFromOpsStatus } from "@/features/admin/accounts/upbit24x7StackOrchestrator";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

import {
  CONSERVATIVE_PORTFOLIO_DEFAULTS,
  DEFAULT_UPBIT_AUTOTRADING_UBA_ID,
  formatUpbitAutotradingModeLabel,
  UPBIT_AUTOTRADING_TAB_KEYS,
  UPBIT_AUTOTRADING_TAB_LABELS,
  UPBIT_AUTOTRADING_TAB_ORDER,
} from "./upbitAutotradingSettingsConfig";

type Props = {
  ubaId: number;
  onUbaIdChange: (next: number) => void;
};

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
        limit: 100,
      }),
  });

  const opsQuery = useQuery({
    queryKey: ["admin", "uba-ops-status", ubaId],
    queryFn: () => adminApi.getAdminUbaOpsStatus(ubaId),
    enabled: ubaId > 0,
    refetchInterval: 20_000,
  });

  const fullMarketQuery = useQuery({
    queryKey: ["admin", "uba-full-market", ubaId],
    queryFn: () => adminApi.getAdminUbaFullMarketStatus(ubaId),
    enabled: ubaId > 0,
    refetchInterval: 20_000,
  });

  const portfolioQuery = useQuery({
    queryKey: ["admin", "uba-portfolio", ubaId],
    queryFn: () => adminApi.getAdminUbaPortfolioStatus(ubaId),
    enabled: ubaId > 0,
    refetchInterval: 20_000,
  });

  const opsSnap = opsQuery.data ? snapshotFromOpsStatus(opsQuery.data) : null;
  const opsRoot = asRecord(opsQuery.data);
  const fmFromOps = asRecord(opsRoot.full_market);
  const scanner = asRecord(opsRoot.scanner);
  const fm = { ...fmFromOps, ...asRecord(fullMarketQuery.data) };
  const portfolio = asRecord(portfolioQuery.data);
  const policy = asRecord(portfolio.policy);
  const summary = asRecord(portfolio.summary);
  const slots = Array.isArray(portfolio.slots) ? portfolio.slots : [];
  const modeRaw = String(
    portfolio.mode ?? fm.mode ?? "FIXED_SYMBOL",
  ).toUpperCase();
  const modeLabel = formatUpbitAutotradingModeLabel(modeRaw);
  const aiGate = String(fm.ai_live_gate_mode ?? "ENFORCE").toUpperCase();
  const candidates = Array.isArray(scanner.candidates)
    ? scanner.candidates
    : Array.isArray(asRecord(fullMarketQuery.data).latest_recommendations)
      ? (asRecord(fullMarketQuery.data).latest_recommendations as unknown[])
      : [];

  const ubaOptions = useMemo(() => {
    const root = asRecord(accountsQuery.data);
    const items = Array.isArray(root.items)
      ? root.items
      : Array.isArray(accountsQuery.data)
        ? (accountsQuery.data as unknown[])
        : [];
    const opts = items
      .map((row) => {
        const r = asRecord(row);
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

  const capitalInitial = useMemo(
    () => ({
      max_positions: Number(policy.max_positions ?? 3),
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
    }),
    [policy],
  );

  const entryInitial = useMemo(
    () => ({
      entry_cooldown_seconds: Number(policy.entry_cooldown_seconds ?? 300),
      candidate_max_age_seconds: Number(
        policy.candidate_max_age_seconds ?? 1800,
      ),
      portfolio_daily_entry_limit: Number(
        policy.portfolio_daily_entry_limit ?? 10,
      ),
      consecutive_loss_limit: Number(policy.consecutive_loss_limit ?? 3),
    }),
    [policy],
  );

  const safetyInitial = useMemo(
    () => ({
      daily_loss_limit_pct: Number(policy.daily_loss_limit_pct ?? 0.02),
      consecutive_loss_limit: Number(policy.consecutive_loss_limit ?? 3),
    }),
    [policy],
  );

  // 서버 policy가 바뀌면 폼 동기화 (페이지 로드 mutate 없음)
  useEffect(() => {
    capitalForm.setFieldsValue(capitalInitial);
  }, [capitalForm, capitalInitial]);

  useEffect(() => {
    entryForm.setFieldsValue(entryInitial);
  }, [entryForm, entryInitial]);

  useEffect(() => {
    safetyForm.setFieldsValue(safetyInitial);
  }, [safetyForm, safetyInitial]);

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
      const row = asRecord(res);
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
    modal.confirm({
      title: "포트폴리오 정책 저장",
      content:
        "Risk를 완화하면 경고가 표시됩니다. Enable/주문은 실행되지 않습니다. 계속할까요?",
      okText: "저장",
      onOk: () => savePolicyMut.mutateAsync(values),
    });
  };

  const drySelectMut = useMutation({
    mutationFn: () => adminApi.drySelectAdminUbaFullMarket(ubaId, {}),
    onSuccess: (data) => {
      const row = asRecord(data);
      const sel = asRecord(row.selected);
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
      const row = asRecord(res);
      message.info(
        `Dry Top-K: ${String(row.reason ?? "ok")} reserved=${JSON.stringify(row.reserved ?? [])}`,
      );
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
      setPreviewResult(asRecord(res));
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

  const riskFromOps = asRecord(opsRoot.risk);
  const accountRisk = asRecord(opsRoot.account_risk);
  const exitFromOps = asRecord(opsRoot.exit ?? opsRoot.protective_exit);
  const unattended = asRecord(opsRoot.unattended);

  const tabItems = UPBIT_AUTOTRADING_TAB_ORDER.map((key) => {
    const label = UPBIT_AUTOTRADING_TAB_LABELS[key];
    if (key === UPBIT_AUTOTRADING_TAB_KEYS.market) {
      return {
        key,
        label,
        children: (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              title="모드 표시 · Dry 시뮬레이션만. PORTFOLIO Enable은 자동 실행하지 않습니다."
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
              <Descriptions.Item label="TARGET">
                {String(fm.current_symbol ?? fm.template_symbol ?? "—")}
              </Descriptions.Item>
              <Descriptions.Item label="STATE">
                {String(fm.state ?? "IDLE")}
              </Descriptions.Item>
              <Descriptions.Item label="AI GATE">
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
                        const r = asRecord(c);
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
          </Space>
        ),
      };
    }

    if (key === UPBIT_AUTOTRADING_TAB_KEYS.capital) {
      return {
        key,
        label,
        children: (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              title="자금·슬롯 설정. [보수적 설정 적용]은 폼만 채우며 자동 저장하지 않습니다."
            />
            <Form form={capitalForm} layout="vertical" initialValues={capitalInitial}>
              <Space wrap size={12}>
                <Form.Item name="max_positions" label="최대 포지션">
                  <InputNumber min={1} max={10} />
                </Form.Item>
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
                  label="대기 진입 상한"
                >
                  <InputNumber min={1} max={10} />
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
                자금 · 포지션 저장
              </Button>
            </Space>
            <Typography.Text strong>Position Slots</Typography.Text>
            <Table
              size="small"
              pagination={false}
              rowKey={(r) =>
                String(asRecord(r).slot_id ?? asRecord(r).slot_no)
              }
              dataSource={slots as Record<string, unknown>[]}
              columns={[
                { title: "Slot", dataIndex: "slot_no", width: 56 },
                {
                  title: "Symbol",
                  dataIndex: "symbol",
                  render: (v) => v ?? "—",
                },
                {
                  title: "State",
                  dataIndex: "status",
                  render: (v) => <Tag>{String(v)}</Tag>,
                },
                {
                  title: "Allocated",
                  dataIndex: "allocated_amount_krw",
                  render: (v) => (v == null ? "—" : String(v)),
                },
                {
                  title: "Reserved",
                  dataIndex: "reserved_amount_krw",
                  render: (v) => (v == null ? "—" : String(v)),
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
        children: (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              title="score/confidence/warmup은 assignment·scanner 표시. 편집 가능 필드는 portfolio policy에 매핑됩니다."
            />
            <Descriptions size="small" bordered column={2}>
              <Descriptions.Item label="Min Score (표시)">
                {numOrDash(fm.min_score ?? asRecord(fm.selection_policy).min_score)}
              </Descriptions.Item>
              <Descriptions.Item label="Min Confidence (표시)">
                {numOrDash(
                  fm.min_confidence ??
                    asRecord(fm.selection_policy).min_confidence,
                )}
              </Descriptions.Item>
              <Descriptions.Item label="Warmup">
                {fm.warmup_ready == null
                  ? "—"
                  : fm.warmup_ready
                    ? "READY"
                    : "NOT READY"}
              </Descriptions.Item>
              <Descriptions.Item label="ENTRY STATE">
                {String(
                  summary.entry_state ?? policy.entry_state ?? "—",
                )}
              </Descriptions.Item>
              <Descriptions.Item label="연속 손실 카운트">
                {numOrDash(policy.consecutive_loss_count)}
              </Descriptions.Item>
              <Descriptions.Item label="후보 최대 연령">
                {numOrDash(policy.candidate_max_age_seconds)}초
              </Descriptions.Item>
            </Descriptions>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              연속 손실 한도 도달 시 ENTRY PAUSE. Warmup 미완료·후보 연령 초과 시
              신규 진입을 건너뜁니다 (서버 SoT).
            </Typography.Paragraph>
            <Form form={entryForm} layout="vertical" initialValues={entryInitial}>
              <Space wrap size={12}>
                <Form.Item
                  name="entry_cooldown_seconds"
                  label="진입 쿨다운 (초)"
                >
                  <InputNumber min={0} step={30} />
                </Form.Item>
                <Form.Item
                  name="candidate_max_age_seconds"
                  label="후보 최대 연령 (초)"
                >
                  <InputNumber min={60} step={60} />
                </Form.Item>
                <Form.Item
                  name="portfolio_daily_entry_limit"
                  label="일일 진입 한도"
                >
                  <InputNumber min={1} max={100} />
                </Form.Item>
                <Form.Item
                  name="consecutive_loss_limit"
                  label="연속 손실 한도 (진입 pause)"
                >
                  <InputNumber min={1} max={50} />
                </Form.Item>
              </Space>
            </Form>
            <Button
              type="primary"
              loading={savePolicyMut.isPending}
              onClick={async () => {
                const values = await entryForm.validateFields();
                confirmSavePolicy(values);
              }}
            >
              진입 규칙 저장
            </Button>
          </Space>
        ),
      };
    }

    if (key === UPBIT_AUTOTRADING_TAB_KEYS.exit) {
      return {
        key,
        label,
        children: (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Alert
              type="warning"
              showIcon
              title="보호성 EXIT(Protective Exit)는 항상 ON입니다. 청산 규칙은 표시 중심이며 이 화면에서 끄지 않습니다."
            />
            <Descriptions size="small" bordered column={2}>
              <Descriptions.Item label="Stop Loss">
                {numOrDash(
                  exitFromOps.stop_loss_pct ??
                    exitFromOps.sl_pct ??
                    riskFromOps.stop_loss_pct ??
                    accountRisk.stop_loss_pct,
                )}
              </Descriptions.Item>
              <Descriptions.Item label="Take Profit">
                {numOrDash(
                  exitFromOps.take_profit_pct ??
                    exitFromOps.tp_pct ??
                    riskFromOps.take_profit_pct ??
                    accountRisk.take_profit_pct,
                )}
              </Descriptions.Item>
              <Descriptions.Item label="Trailing">
                {numOrDash(
                  exitFromOps.trailing_pct ??
                    exitFromOps.trailing_stop_pct ??
                    riskFromOps.trailing_pct,
                )}
              </Descriptions.Item>
              <Descriptions.Item label="Exit Monitor">
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
              <Descriptions.Item label="Protective Exit">
                <Tag color="green">
                  {unattended.protective_exit_authorized === false
                    ? "LEASE 없음 · 모니터 경로 유지"
                    : "ALWAYS ON"}
                </Tag>
              </Descriptions.Item>
            </Descriptions>
            <Typography.Paragraph type="secondary">
              SL/TP/Trailing 값이 ops/risk에 없으면 「—」로 표시합니다. 세부
              리스크 한도는{" "}
              <Link href={adminRoutes.risk}>리스크 관리</Link>에서 확인하세요.
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
              rowKey={(_, idx) => String(idx)}
              dataSource={candidates.slice(0, 10) as Record<string, unknown>[]}
              locale={{ emptyText: "추천 없음" }}
              columns={[
                {
                  title: "Symbol",
                  dataIndex: "symbol",
                  render: (v) => v ?? "—",
                },
                {
                  title: "Rec",
                  dataIndex: "recommendation",
                  render: (v) => <Tag>{String(v ?? "—")}</Tag>,
                },
                {
                  title: "Score",
                  dataIndex: "score",
                  render: (v) => numOrDash(v),
                },
                {
                  title: "Confidence",
                  dataIndex: "confidence",
                  render: (v) => numOrDash(v),
                },
                {
                  title: "Rank",
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
                  asRecord(opsRoot.daily_loss).current,
              )}{" "}
              /{" "}
              {numOrDash(
                riskFromOps.max_daily_loss_limit ??
                  accountRisk.max_daily_loss_limit ??
                  asRecord(opsRoot.daily_loss).limit,
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
        title="설정 워크스페이스 — PORTFOLIO 자동 Enable · REAL 주문 · 로드 시 risk mutate 없음"
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
        <Descriptions.Item label="Reserved KRW">
          {numOrDash(summary.reserved_krw ?? 0)}
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
            <Descriptions.Item label="Symbol">
              {String(previewResult.symbol ?? previewSymbol)}
            </Descriptions.Item>
            <Descriptions.Item label="Recommended">
              {numOrDash(previewResult.recommended_amount_krw)}
            </Descriptions.Item>
            <Descriptions.Item label="Approved">
              {numOrDash(previewResult.approved_amount_krw)}
            </Descriptions.Item>
            <Descriptions.Item label="Reasons">
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

      <Tabs items={tabItems} />
    </Space>
  );
}
