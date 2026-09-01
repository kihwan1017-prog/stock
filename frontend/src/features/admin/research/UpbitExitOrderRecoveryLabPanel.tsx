"use client";

/**
 * Exit Order Recovery Shadow Lab V1 — RESEARCH ONLY.
 * REAL cancel/reprice/market fallback 없음. 승격 버튼 없음.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type VariantRow = {
  key: string;
  label: string;
  enrolled: number;
  triggered: number;
  validPaired: number;
  realAvgTtf: number | null;
  realMedTtf: number | null;
  shadowAvgTtf: number | null;
  shadowMedTtf: number | null;
  long30: number;
  long60: number;
  realFillRate: number | null;
  shadowFillRate: number | null;
  reprice: number;
  marketFb: number;
};

const VARIANT_LABEL: Record<string, string> = {
  R0: "R0 REAL baseline",
  R1: "R1 30분 재가격 (best bid)",
  R2: "R2 60분 재가격 (best bid)",
  R3: "R3 60분 Market fallback",
};

function fmtSec(v: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  if (v >= 3600) return `${(v / 3600).toFixed(1)}h`;
  if (v >= 60) return `${(v / 60).toFixed(1)}m`;
  return `${v.toFixed(0)}s`;
}

function fmtRate(v: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

export function UpbitExitOrderRecoveryLabPanel({
  ubaId = 1380,
}: {
  ubaId?: number;
}) {
  const summaryQ = useQuery({
    queryKey: queryKeys.admin.upbitExitOrderRecoveryLabSummary(ubaId),
    queryFn: () => adminApi.getAdminUpbitExitOrderRecoveryLabSummary(ubaId),
    refetchInterval: 60_000,
  });
  const obsQ = useQuery({
    queryKey: queryKeys.admin.upbitExitOrderRecoveryLabObservations(ubaId),
    queryFn: () =>
      adminApi.getAdminUpbitExitOrderRecoveryLabObservations({
        uba_id: ubaId,
        limit: 50,
      }),
    refetchInterval: 60_000,
  });

  if (summaryQ.isLoading) {
    return (
      <Typography.Text type="secondary">
        Exit 주문 미체결 Lab 불러오는 중…
      </Typography.Text>
    );
  }
  if (summaryQ.isError) {
    return (
      <Alert
        type="error"
        showIcon
        title="조회 실패"
        description={toApiError(summaryQ.error).message}
      />
    );
  }

  const root = asRecord(summaryQ.data);
  const variants = asRecord(root.VARIANTS);
  const rows: VariantRow[] = ["R0", "R1", "R2", "R3"].map((v) => {
    const vr = asRecord(variants[v]);
    return {
      key: v,
      label: VARIANT_LABEL[v] ?? v,
      enrolled: Number(vr.TOTAL_ENROLLED ?? 0),
      triggered: Number(vr.TRIGGERED_COUNT ?? 0),
      validPaired: Number(vr.VALID_PAIRED_N ?? 0),
      realAvgTtf:
        vr.REAL_AVG_TIME_TO_FILL != null
          ? Number(vr.REAL_AVG_TIME_TO_FILL)
          : null,
      realMedTtf:
        vr.REAL_MEDIAN_TIME_TO_FILL != null
          ? Number(vr.REAL_MEDIAN_TIME_TO_FILL)
          : null,
      shadowAvgTtf:
        vr.SHADOW_AVG_TIME_TO_FILL != null
          ? Number(vr.SHADOW_AVG_TIME_TO_FILL)
          : null,
      shadowMedTtf:
        vr.SHADOW_MEDIAN_TIME_TO_FILL != null
          ? Number(vr.SHADOW_MEDIAN_TIME_TO_FILL)
          : null,
      long30: Number(vr.LONG_WAIT_GT_30M ?? 0),
      long60: Number(vr.LONG_WAIT_GT_60M ?? 0),
      realFillRate:
        vr.REAL_FILL_RATE != null ? Number(vr.REAL_FILL_RATE) : null,
      shadowFillRate:
        vr.SHADOW_EST_FILL_RATE != null
          ? Number(vr.SHADOW_EST_FILL_RATE)
          : null,
      reprice: Number(vr.REPRICE_COUNT ?? 0),
      marketFb: Number(vr.MARKET_FALLBACK_COUNT ?? 0),
    };
  });

  const columns: ColumnsType<VariantRow> = [
    { title: "Variant", dataIndex: "label", key: "label" },
    { title: "N", dataIndex: "enrolled", key: "enrolled" },
    { title: "Trigger", dataIndex: "triggered", key: "triggered" },
    { title: "Valid Paired", dataIndex: "validPaired", key: "validPaired" },
    {
      title: "Real avg/med TTF",
      key: "realTtf",
      render: (_: unknown, r) =>
        `${fmtSec(r.realAvgTtf)} / ${fmtSec(r.realMedTtf)}`,
    },
    {
      title: "Shadow avg/med TTF",
      key: "shadowTtf",
      render: (_: unknown, r) =>
        `${fmtSec(r.shadowAvgTtf)} / ${fmtSec(r.shadowMedTtf)}`,
    },
    {
      title: "Fill rate R/S",
      key: "fill",
      render: (_: unknown, r) =>
        `${fmtRate(r.realFillRate)} / ${fmtRate(r.shadowFillRate)}`,
    },
    { title: ">30m", dataIndex: "long30", key: "long30" },
    { title: ">60m", dataIndex: "long60", key: "long60" },
    { title: "Reprice", dataIndex: "reprice", key: "reprice" },
    { title: "Mkt FB", dataIndex: "marketFb", key: "marketFb" },
  ];

  const obsRoot = asRecord(obsQ.data);
  const obsItems = Array.isArray(obsRoot.items) ? obsRoot.items : [];
  const obsColumns: ColumnsType<Record<string, unknown>> = [
    { title: "Symbol", dataIndex: "symbol", key: "symbol" },
    { title: "Exit", dataIndex: "exit_reason", key: "exit_reason" },
    { title: "Order", dataIndex: "real_order_id", key: "real_order_id" },
    { title: "Variant", dataIndex: "variant", key: "variant" },
    { title: "Action", dataIndex: "shadow_action", key: "shadow_action" },
    {
      title: "Real fill",
      key: "real_fill",
      render: (_: unknown, r) =>
        `${String(r.real_terminal_state ?? "—")} @ ${String(r.real_fill_price ?? "—")}`,
    },
    {
      title: "Shadow est",
      key: "shadow_est",
      render: (_: unknown, r) =>
        `${String(r.shadow_fill_status ?? "—")} @ ${String(r.shadow_estimated_fill_price ?? "—")}`,
    },
    {
      title: "Evidence",
      dataIndex: "evidence_quality",
      key: "evidence_quality",
      render: (v: unknown) => (v ? <Tag>{String(v)}</Tag> : "—"),
    },
  ];

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="SHADOW ONLY · REAL POLICY UNCHANGED"
        description="AUTO_EXIT_SELL 장기 미체결 recovery 후보를 forward-only shadow로 비교합니다. REAL cancel/reprice/market 전환 없음."
      />
      <Row gutter={[12, 12]}>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic
              title="START_AT"
              value={String(root.FORWARD_START_AT ?? "—")}
              styles={{ content: { fontSize: 13 } }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic
              title="Readiness"
              value={String(root.READINESS ?? "SAMPLE_PENDING")}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic
              title="VALID_PAIRED_N (max)"
              value={Number(root.VALID_PAIRED_N_MAX ?? 0)}
            />
          </Card>
        </Col>
      </Row>
      <Table
        size="small"
        rowKey="key"
        pagination={false}
        columns={columns}
        dataSource={rows}
        scroll={{ x: true }}
      />
      <Typography.Title level={5} style={{ margin: 0 }}>
        Observations
      </Typography.Title>
      <Table
        size="small"
        rowKey={(r) => String(r.observation_id ?? `${r.variant}-${r.real_order_id}`)}
        loading={obsQ.isLoading}
        columns={obsColumns}
        dataSource={obsItems as Record<string, unknown>[]}
        pagination={{ pageSize: 20 }}
        scroll={{ x: true }}
      />
    </Space>
  );
}
