"use client";

/**
 * Drawer용 PORTFOLIO 요약 + 전체 설정 링크.
 * 상세 폼은 /admin/upbit/autotrading 워크스페이스로 이동.
 * REAL 주문 / 자동 Enable 없음.
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
import Link from "next/link";
import { useState } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { formatUpbitAutotradingModeLabel } from "@/features/admin/upbit/upbitAutotradingSettingsConfig";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

const CONFIRM_ENABLE = "전체시장 포트폴리오 모드 시작";
const CONFIRM_DISABLE = "전체시장 포트폴리오 모드 중지";

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

  const statusQuery = useQuery({
    queryKey: ["admin", "uba-portfolio", ubaId],
    queryFn: () => adminApi.getAdminUbaPortfolioStatus(ubaId),
    enabled: ubaId > 0,
    refetchInterval: 20_000,
  });

  const data = asRecord(statusQuery.data);
  const policy = asRecord(data.policy);
  const summary = asRecord(data.summary);
  const mode = String(data.mode ?? "FIXED_SYMBOL").toUpperCase();
  const modeLabel = formatUpbitAutotradingModeLabel(mode);
  const portfolioOn = modeLabel === "PORTFOLIO";
  const settingsHref = `${adminRoutes.upbitAutotrading}?ubaId=${ubaId}`;

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
      message.success("PORTFOLIO mode enabled (주문 강제 없음 · 설정은 워크스페이스)");
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

  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      <Typography.Text strong>UPBIT 포트폴리오 (요약)</Typography.Text>
      <Alert
        type={portfolioOn ? "warning" : "info"}
        showIcon
        title={
          portfolioOn
            ? "FULL_MARKET_PORTFOLIO — 상세 설정은 워크스페이스에서"
            : "PORTFOLIO default OFF — 자금/진입/AI/안전 설정은 워크스페이스"
        }
      />

      <Descriptions size="small" column={2} bordered>
        <Descriptions.Item label="MODE">
          <Tag color={portfolioOn ? "orange" : "default"}>{modeLabel}</Tag>
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
        <Descriptions.Item label="CASH RESERVE">
          {(Number(summary.min_cash_reserve_pct ?? 0.6) * 100).toFixed(0)}%
        </Descriptions.Item>
        <Descriptions.Item label="SLOTS">
          {Array.isArray(data.slots) ? data.slots.length : 0}
        </Descriptions.Item>
      </Descriptions>

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
        <Link href={settingsHref}>
          <Button type="link" style={{ paddingInline: 0 }}>
            업비트 자동매매 설정 열기
          </Button>
        </Link>
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
          title="명시 Enable만. REAL 주문 없음. 세부 정책은 설정 워크스페이스에서 편집하세요."
        />
        <Typography.Paragraph>
          확인 문구: <Typography.Text code>{CONFIRM_ENABLE}</Typography.Text>
        </Typography.Paragraph>
        <ul>
          <li>UBA {ubaId} · UPBIT</li>
          <li>Max Positions {String(policy.max_positions ?? 3)}</li>
          <li>
            설정:{" "}
            <Link href={settingsHref}>/admin/upbit/autotrading?ubaId={ubaId}</Link>
          </li>
        </ul>
      </Modal>
    </Space>
  );
}
