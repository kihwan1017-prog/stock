"use client";

/**
 * Exit Optimization Shadow Lab V2 — RESEARCH ONLY.
 * REAL trailing / entry / risk 변경 버튼 없음. 승격 추천 문구 없음.
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
import { formatNumResearch } from "@/features/admin/upbit/researchDetailFormat";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type LabRow = {
  key: string;
  variant: string;
  label: string;
  n: number;
  net: number | null;
  deltaNet: number | null;
  pf: number | null;
  winRate: number | null;
  avgHold: number | null;
  fees: number | null;
  readiness: string;
};

const VARIANT_LABEL: Record<string, string> = {
  T0: "T0 REAL baseline",
  T5: "T5 min_hold 60s",
  T6: "T6 min_hold 30s",
  T7: "T7 min_hold 120s",
  T8: "T8 dd -1.0% +60s",
};

export function UpbitExitOptimizationLabPanel({
  ubaId = 1380,
}: {
  ubaId?: number;
}) {
  const labQ = useQuery({
    queryKey: queryKeys.admin.upbitExitOptimizationLabSummary(ubaId),
    queryFn: () => adminApi.getAdminUpbitExitOptimizationLabSummary(ubaId),
    refetchInterval: 60_000,
  });
  const reQ = useQuery({
    queryKey: queryKeys.admin.upbitExitOptimizationReentrySummary(ubaId),
    queryFn: () => adminApi.getAdminUpbitExitOptimizationReentrySummary(ubaId),
    refetchInterval: 60_000,
  });

  if (labQ.isLoading) {
    return (
      <Typography.Text type="secondary">
        Exit Optimization Lab 불러오는 중…
      </Typography.Text>
    );
  }
  if (labQ.isError) {
    return (
      <Alert
        type="error"
        showIcon
        title="조회 실패"
        description={toApiError(labQ.error).message}
      />
    );
  }

  const data = asRecord(labQ.data);
  const per = asRecord(data?.per_variant) ?? {};
  const rows: LabRow[] = ["T0", "T5", "T6", "T7", "T8"].map((vk) => {
    const v = asRecord(per[vk]) ?? {};
    return {
      key: vk,
      variant: vk,
      label: VARIANT_LABEL[vk] ?? vk,
      n: Number(v.VALID_PAIRED_N ?? 0),
      net: v.SHADOW_NET == null ? null : Number(v.SHADOW_NET),
      deltaNet: v.DELTA_NET == null ? null : Number(v.DELTA_NET),
      pf: v.SHADOW_PF == null ? null : Number(v.SHADOW_PF),
      winRate: v.SHADOW_WIN_RATE == null ? null : Number(v.SHADOW_WIN_RATE),
      avgHold: v.SHADOW_AVG_HOLD == null ? null : Number(v.SHADOW_AVG_HOLD),
      fees:
        v.SHADOW_ESTIMATED_FEES == null
          ? null
          : Number(v.SHADOW_ESTIMATED_FEES),
      readiness: String(v.readiness_label ?? "표본 수집 중"),
    };
  });

  const columns: ColumnsType<LabRow> = [
    { title: "Variant", dataIndex: "label", width: 160 },
    { title: "N", dataIndex: "n", width: 70 },
    {
      title: "Net",
      dataIndex: "net",
      render: (v) => formatNumResearch(v),
    },
    {
      title: "ΔNet",
      dataIndex: "deltaNet",
      render: (v) => formatNumResearch(v),
    },
    {
      title: "PF",
      dataIndex: "pf",
      render: (v) => formatNumResearch(v),
    },
    {
      title: "Win%",
      dataIndex: "winRate",
      render: (v) =>
        v == null ? "—" : `${(Number(v) * 100).toFixed(1)}%`,
    },
    {
      title: "Avg Hold(s)",
      dataIndex: "avgHold",
      render: (v) => formatNumResearch(v),
    },
    {
      title: "Fees",
      dataIndex: "fees",
      render: (v) => formatNumResearch(v),
    },
    {
      title: "상태",
      dataIndex: "readiness",
      render: (v: string) => {
        const color =
          v.includes("승격") ? "gold" : v.includes("1차") ? "blue" : "default";
        return <Tag color={color}>{v}</Tag>;
      },
    },
  ];

  const re = asRecord(reQ.data) ?? {};
  const reRows = ["R1", "R2", "R3"].map((k) => {
    const v = asRecord(re[k]) ?? {};
    return {
      key: k,
      variant: k,
      cooldown: Number(v.cooldown_seconds ?? 0),
      n: Number(v.N ?? 0),
      wouldBlock: Number(v.would_block_n ?? 0),
      impact: v.avoided_net_impact == null ? null : Number(v.avoided_net_impact),
    };
  });

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="Exit Optimization Shadow Lab V2 — RESEARCH ONLY"
        description="REAL trailing(arm +1.0% / drawdown -0.8%) 불변. 자동 승격/추천 문구 없음."
      />
      <Row gutter={12}>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="TOTAL rows"
              value={Number(data?.TOTAL_ROWS ?? 0)}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="ACTIVE" value={Number(data?.ACTIVE ?? 0)} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="T5 VALID_PAIRED_N"
              value={Number(data?.T5_VALID_PAIRED_N ?? 0)}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="AUTO_PROMOTION"
              value="FORBIDDEN"
              valueStyle={{ fontSize: 16 }}
            />
          </Card>
        </Col>
      </Row>
      <Table
        size="small"
        pagination={false}
        rowKey="key"
        columns={columns}
        dataSource={rows}
      />
      <Typography.Title level={5} style={{ margin: 0 }}>
        Re-entry Cooldown Shadow (R1/R2/R3)
      </Typography.Title>
      <Table
        size="small"
        pagination={false}
        rowKey="key"
        loading={reQ.isLoading}
        dataSource={reRows}
        columns={[
          { title: "Variant", dataIndex: "variant", width: 80 },
          { title: "Cooldown(s)", dataIndex: "cooldown", width: 100 },
          { title: "N", dataIndex: "n", width: 70 },
          { title: "Would-block", dataIndex: "wouldBlock", width: 110 },
          {
            title: "Avoided net impact",
            dataIndex: "impact",
            render: (v) => formatNumResearch(v),
          },
        ]}
      />
    </Space>
  );
}
