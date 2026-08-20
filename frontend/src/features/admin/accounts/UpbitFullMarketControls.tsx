"use client";

/**
 * UPBIT Full-Market Dynamic Selection — 관리자 전용.
 * 기본 OFF(FIXED_SYMBOL). REAL 주문/자동 Enable 없음.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Descriptions,
  Modal,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { toApiError } from "@/lib/api/apiError";

const CONFIRM_ENABLE = "전체시장 자동선정 모드 시작";
const CONFIRM_DISABLE = "전체시장 자동선정 모드 중지";

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
  opsPayload?: unknown;
};

export function UpbitFullMarketControls({
  ubaId,
  strategyId,
  deploymentId,
  templateSymbol,
  opsPayload,
}: Props) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [enableOpen, setEnableOpen] = useState(false);

  const statusQuery = useQuery({
    queryKey: ["admin", "uba-full-market", ubaId],
    queryFn: () => adminApi.getAdminUbaFullMarketStatus(ubaId),
    enabled: ubaId > 0,
    refetchInterval: 15_000,
  });

  const fmFromOps = asRecord(asRecord(opsPayload).full_market);
  const fm = {
    ...fmFromOps,
    ...asRecord(statusQuery.data),
  };
  const mode = String(fm.mode ?? "FIXED_SYMBOL").toUpperCase();
  const enabled = mode === "FULL_MARKET_AUTO";
  const scanner = asRecord(asRecord(opsPayload).scanner);
  const cands = Array.isArray(scanner.candidates) ? scanner.candidates : [];

  const enableMut = useMutation({
    mutationFn: () =>
      adminApi.enableAdminUbaFullMarket(ubaId, {
        confirmation_text: CONFIRM_ENABLE,
        strategy_id: strategyId,
        deployment_id: deploymentId,
        template_symbol: templateSymbol,
        ai_live_gate_mode: "ENFORCE",
      }),
    onSuccess: async () => {
      message.success("FULL_MARKET_AUTO enabled (REAL 주문은 별도 신호 경로)");
      setEnableOpen(false);
      await queryClient.invalidateQueries({
        queryKey: ["admin", "uba-full-market", ubaId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["admin", "uba-ops-status", ubaId],
      });
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const disableMut = useMutation({
    mutationFn: () =>
      adminApi.disableAdminUbaFullMarket(ubaId, {
        confirmation_text: CONFIRM_DISABLE,
      }),
    onSuccess: async () => {
      message.success("FIXED_SYMBOL 복귀");
      await queryClient.invalidateQueries({
        queryKey: ["admin", "uba-full-market", ubaId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["admin", "uba-ops-status", ubaId],
      });
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const dryMut = useMutation({
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

  const riskLines = useMemo(
    () => [
      `UBA ${ubaId}`,
      strategyId ? `Strategy ${strategyId}` : "Strategy —",
      deploymentId ? `Deployment ${deploymentId}` : "Deployment —",
      `Template ${templateSymbol || String(fm.template_symbol || "—")}`,
      "Single active position",
      "AI LIVE Gate: ENFORCE",
      "Scanner interval: 기존 정책 유지",
      "Risk / max_order: DB SoT 이하",
      "24H Unattended: 기존 ACCOUNT-scoped 유지",
    ],
    [ubaId, strategyId, deploymentId, templateSymbol, fm.template_symbol],
  );

  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      <Typography.Text strong>Dynamic Selection (Full Market)</Typography.Text>
      <Alert
        type={enabled ? "warning" : "info"}
        showIcon
        message={
          enabled
            ? "FULL_MARKET_AUTO — Scanner 후보 자동 선정 활성"
            : "FIXED_SYMBOL — 현재 고정 심볼 모드 (기본·안전)"
        }
      />
      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="MODE">
          <Tag color={enabled ? "orange" : "default"}>
            {enabled ? "FULL MARKET" : "FIXED SYMBOL"}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="CURRENT TARGET">
          {String(fm.current_symbol ?? fm.template_symbol ?? "—")}
        </Descriptions.Item>
        <Descriptions.Item label="STATE">
          {String(fm.state ?? "IDLE")}
        </Descriptions.Item>
        <Descriptions.Item label="AI GATE">
          {String(fm.ai_live_gate_mode ?? "ENFORCE")}
        </Descriptions.Item>
        <Descriptions.Item label="SCANNER">
          {String(scanner.universe_count ?? "—")} →{" "}
          {String(scanner.liquidity_pass_count ?? "—")} →{" "}
          {String(scanner.top_n ?? "—")}
        </Descriptions.Item>
        <Descriptions.Item label="TOP">
          {cands.length
            ? cands
                .slice(0, 3)
                .map((c) => {
                  const r = asRecord(c);
                  return `${r.symbol}(${r.recommendation})`;
                })
                .join(" · ")
            : "—"}
        </Descriptions.Item>
        <Descriptions.Item label="COOLDOWN">
          {String(fm.cooldown_until ?? "—")}
        </Descriptions.Item>
      </Descriptions>

      <Space wrap>
        <Switch
          checked={enabled}
          checkedChildren="ON"
          unCheckedChildren="OFF"
          onChange={(checked) => {
            if (checked) {
              setEnableOpen(true);
              return;
            }
            modal.confirm({
              title: "전체시장 모드 중지",
              content: (
                <Typography.Paragraph>
                  FIXED_SYMBOL로 되돌립니다. 확인:{" "}
                  <Typography.Text code>{CONFIRM_DISABLE}</Typography.Text>
                </Typography.Paragraph>
              ),
              okText: "중지",
              okButtonProps: { danger: true },
              onOk: () => disableMut.mutateAsync(),
            });
          }}
        />
        <Button loading={dryMut.isPending} onClick={() => dryMut.mutate()}>
          Dry Select
        </Button>
      </Space>

      <Modal
        title="전체시장 자동선정 모드 시작"
        open={enableOpen}
        onCancel={() => setEnableOpen(false)}
        okText="Enable FULL MARKET"
        okButtonProps={{ danger: true, loading: enableMut.isPending }}
        onOk={() => enableMut.mutateAsync()}
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="명시 승인 후 Enable. REAL 테스트 주문은 강제하지 않습니다."
        />
        <Typography.Paragraph>
          확인 문구: <Typography.Text code>{CONFIRM_ENABLE}</Typography.Text>
        </Typography.Paragraph>
        <ul>
          {riskLines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </Modal>
    </Space>
  );
}
