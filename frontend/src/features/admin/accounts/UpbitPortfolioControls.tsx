"use client";

/**
 * UPBIT FULL_MARKET_PORTFOLIO 설정/슬롯/사이징 프리뷰.
 * 기본 OFF. REAL 주문/자동 Enable 없음.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Descriptions,
  Form,
  InputNumber,
  Modal,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { toApiError } from "@/lib/api/apiError";

const CONFIRM_ENABLE = "전체시장 포트폴리오 모드 시작";
const CONFIRM_DISABLE = "전체시장 포트폴리오 모드 중지";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

type Props = {
  ubaId: number;
  strategyId?: number;
  deploymentId?: number;
  templateSymbol?: string;
};

export function UpbitPortfolioControls({
  ubaId,
  strategyId,
  deploymentId,
  templateSymbol,
}: Props) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [enableOpen, setEnableOpen] = useState(false);
  const [form] = Form.useForm();

  const statusQuery = useQuery({
    queryKey: ["admin", "uba-portfolio", ubaId],
    queryFn: () => adminApi.getAdminUbaPortfolioStatus(ubaId),
    enabled: ubaId > 0,
    refetchInterval: 20_000,
  });

  const data = asRecord(statusQuery.data);
  const policy = asRecord(data.policy);
  const summary = asRecord(data.summary);
  const slots = Array.isArray(data.slots) ? data.slots : [];
  const mode = String(data.mode ?? "FIXED_SYMBOL").toUpperCase();
  const portfolioOn = mode === "FULL_MARKET_PORTFOLIO";

  const invalidate = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["admin", "uba-portfolio", ubaId],
    });
    await queryClient.invalidateQueries({
      queryKey: ["admin", "uba-full-market", ubaId],
    });
    await queryClient.invalidateQueries({
      queryKey: ["admin", "uba-ops-status", ubaId],
    });
  };

  const enableMut = useMutation({
    mutationFn: () =>
      adminApi.enableAdminUbaPortfolio(ubaId, {
        confirmation_text: CONFIRM_ENABLE,
        strategy_id: strategyId,
        deployment_id: deploymentId,
        template_symbol: templateSymbol,
        max_positions: Number(policy.max_positions ?? 3),
        portfolio_capital_limit_krw:
          policy.portfolio_capital_limit_krw != null
            ? Number(policy.portfolio_capital_limit_krw)
            : undefined,
      }),
    onSuccess: async () => {
      message.success("PORTFOLIO mode enabled (주문 강제 없음 · default 운영은 별도)");
      setEnableOpen(false);
      await invalidate();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const disableMut = useMutation({
    mutationFn: () =>
      adminApi.disableAdminUbaPortfolio(ubaId, {
        confirmation_text: CONFIRM_DISABLE,
        fallback_mode: "FULL_MARKET_SINGLE",
      }),
    onSuccess: async () => {
      message.success("PORTFOLIO 중지 → FULL_MARKET_SINGLE");
      await invalidate();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const saveMut = useMutation({
    mutationFn: async () => {
      const values = await form.validateFields();
      return adminApi.patchAdminUbaPortfolioPolicy(ubaId, values);
    },
    onSuccess: async (res) => {
      const row = asRecord(res);
      const warnings = Array.isArray(row.warnings) ? row.warnings : [];
      if (warnings.length) {
        message.warning(`저장됨 · Risk 완화 경고: ${warnings.join(", ")}`);
      } else {
        message.success("Portfolio policy 저장");
      }
      await invalidate();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const previewMut = useMutation({
    mutationFn: () =>
      adminApi.previewAdminUbaPortfolioSizing(ubaId, {
        symbol: "KRW-ETH",
        available_krw: 500_000,
        account_max_order_amount: 10_000,
      }),
    onSuccess: (res) => {
      const row = asRecord(res);
      message.info(
        `Preview ${String(row.symbol)}: recommended=${String(row.recommended_amount_krw)} approved=${String(row.approved_amount_krw)} (${(Array.isArray(row.clamp_reasons) ? row.clamp_reasons : []).join("|") || "—"})`,
      );
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const dryTopKMut = useMutation({
    mutationFn: () =>
      adminApi.dryTopKAdminUbaPortfolio(ubaId, {
        scanner_run_id: "ui-dry-topk",
        available_krw: 500_000,
        account_max_order_amount: 10_000,
        candidates: [
          { symbol: "KRW-CAP", rank: 1, score: 90, recommendation: "HOLD", confidence: 0.9 },
          { symbol: "KRW-ETH", rank: 2, score: 88, recommendation: "ALLOW", confidence: 0.86 },
          { symbol: "KRW-BTC", rank: 3, score: 85, recommendation: "ALLOW", confidence: 0.84 },
          { symbol: "KRW-SOL", rank: 4, score: 80, recommendation: "ALLOW", confidence: 0.8 },
          { symbol: "KRW-XRP", rank: 5, score: 78, recommendation: "ALLOW", confidence: 0.78 },
        ],
      }),
    onSuccess: (res) => {
      const row = asRecord(res);
      message.info(
        `Dry Top-K: ${String(row.reason)} reserved=${JSON.stringify(row.reserved ?? [])}`,
      );
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const formInitial = useMemo(
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
      daily_loss_limit_pct: Number(policy.daily_loss_limit_pct ?? 0.02),
      consecutive_loss_limit: Number(policy.consecutive_loss_limit ?? 3),
      entry_cooldown_seconds: Number(policy.entry_cooldown_seconds ?? 300),
      portfolio_max_pending_entries: Number(
        policy.portfolio_max_pending_entries ?? 1,
      ),
      allow_averaging_down: Boolean(policy.allow_averaging_down),
      allow_duplicate_symbol: Boolean(policy.allow_duplicate_symbol),
    }),
    [policy],
  );

  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      <Typography.Text strong>UPBIT 포트폴리오 (Multi-Position)</Typography.Text>
      <Alert
        type={portfolioOn ? "warning" : "info"}
        showIcon
        title={
          portfolioOn
            ? "FULL_MARKET_PORTFOLIO — 최대 3 slots (Enable 된 계좌만)"
            : "PORTFOLIO default OFF — 기존 FIXED / FULL_MARKET_SINGLE 유지"
        }
      />

      <Descriptions size="small" column={2} bordered>
        <Descriptions.Item label="MODE">
          <Tag color={portfolioOn ? "purple" : "default"}>{mode}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="ENTRY">
          {String(summary.entry_state ?? policy.entry_state ?? "—")}
        </Descriptions.Item>
        <Descriptions.Item label="POSITIONS">
          {String(summary.positions_open ?? 0)} /{" "}
          {String(summary.max_positions ?? 3)}
        </Descriptions.Item>
        <Descriptions.Item label="EXPOSURE">
          {summary.exposure_pct != null
            ? `${(Number(summary.exposure_pct) * 100).toFixed(1)}%`
            : "—"}{" "}
          / {(Number(summary.max_total_exposure_pct ?? 0.3) * 100).toFixed(0)}%
        </Descriptions.Item>
        <Descriptions.Item label="RESERVED">
          {String(summary.reserved_krw ?? 0)}
        </Descriptions.Item>
        <Descriptions.Item label="CASH RESERVE">
          {(Number(summary.min_cash_reserve_pct ?? 0.6) * 100).toFixed(0)}%
        </Descriptions.Item>
      </Descriptions>

      <Table
        size="small"
        pagination={false}
        rowKey={(r) => String(asRecord(r).slot_id ?? asRecord(r).slot_no)}
        dataSource={slots as Record<string, unknown>[]}
        columns={[
          { title: "Slot", dataIndex: "slot_no", width: 56 },
          { title: "Symbol", dataIndex: "symbol", render: (v) => v ?? "—" },
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

      <Form
        form={form}
        layout="vertical"
        key={JSON.stringify(formInitial)}
        initialValues={formInitial}
        style={{ maxWidth: 720 }}
      >
        <Space wrap size={12}>
          <Form.Item name="max_positions" label="Max Positions">
            <InputNumber min={1} max={10} />
          </Form.Item>
          <Form.Item name="portfolio_capital_limit_krw" label="Capital Limit">
            <InputNumber min={0} step={10000} />
          </Form.Item>
          <Form.Item name="per_position_target_pct" label="Per Pos %">
            <InputNumber min={0.01} max={1} step={0.01} />
          </Form.Item>
          <Form.Item name="max_total_exposure_pct" label="Max Total Exp %">
            <InputNumber min={0.01} max={1} step={0.01} />
          </Form.Item>
          <Form.Item name="min_cash_reserve_pct" label="Cash Reserve %">
            <InputNumber min={0} max={1} step={0.05} />
          </Form.Item>
          <Form.Item name="portfolio_max_pending_entries" label="Max Pending BUY">
            <InputNumber min={1} max={10} />
          </Form.Item>
          <Form.Item
            name="allow_averaging_down"
            label="Averaging Down"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="allow_duplicate_symbol"
            label="Duplicate Symbol"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
        </Space>
      </Form>

      <Space wrap>
        <Switch
          checked={portfolioOn}
          checkedChildren="PORTFOLIO"
          unCheckedChildren="OFF"
          onChange={(checked) => {
            if (checked) {
              setEnableOpen(true);
              return;
            }
            modal.confirm({
              title: "포트폴리오 모드 중지",
              content: (
                <Typography.Paragraph>
                  OPEN slot 강제 청산 없음. 확인:{" "}
                  <Typography.Text code>{CONFIRM_DISABLE}</Typography.Text>
                </Typography.Paragraph>
              ),
              okText: "중지",
              okButtonProps: { danger: true },
              onOk: () => disableMut.mutateAsync(),
            });
          }}
        />
        <Button
          loading={saveMut.isPending}
          onClick={() => {
            modal.confirm({
              title: "Portfolio 설정 저장",
              content: "Risk를 완화하면 경고가 표시됩니다. 계속할까요?",
              onOk: () => saveMut.mutateAsync(),
            });
          }}
        >
          Save Policy
        </Button>
        <Button loading={previewMut.isPending} onClick={() => previewMut.mutate()}>
          Sizing Preview
        </Button>
        <Button loading={dryTopKMut.isPending} onClick={() => dryTopKMut.mutate()}>
          Dry Top-K
        </Button>
      </Space>

      <Modal
        title="전체시장 포트폴리오 모드 시작"
        open={enableOpen}
        onCancel={() => setEnableOpen(false)}
        okText="Enable PORTFOLIO"
        okButtonProps={{ danger: true, loading: enableMut.isPending }}
        onOk={() => enableMut.mutateAsync()}
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          title="명시 Enable만. REAL 주문/UBA1380 자동 전환 없음."
        />
        <Typography.Paragraph>
          확인 문구: <Typography.Text code>{CONFIRM_ENABLE}</Typography.Text>
        </Typography.Paragraph>
        <ul>
          <li>UBA {ubaId} · UPBIT</li>
          <li>Max Positions {String(policy.max_positions ?? 3)}</li>
          <li>Pending BUY 순차 1건 권장</li>
          <li>Averaging Down OFF · Duplicate OFF</li>
          <li>Account Risk / Activation clamp 유지</li>
        </ul>
      </Modal>
    </Space>
  );
}
