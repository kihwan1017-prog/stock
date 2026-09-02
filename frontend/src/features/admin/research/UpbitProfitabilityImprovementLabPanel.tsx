"use client";

/**
 * 수익성 개선 Shadow Lab V1 — RESEARCH ONLY.
 * Candidate V2 / Exit V4 / Reentry Anti-Churn — REAL 매매 미적용.
 */

import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Col, Row, Space, Statistic, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import * as adminApi from "@/features/admin/api/adminApi";
import { formatNumResearch } from "@/features/admin/upbit/researchDetailFormat";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type VariantRow = {
  key: string;
  lab: string;
  variant: string;
  label: string;
  n: number;
  metric: number | null;
  delta: number | null;
  readiness: string;
};

function readinessColor(r: string): string {
  if (r === "PROMOTION_REVIEW_ELIGIBLE") return "green";
  if (r === "PRIMARY_REVIEW") return "blue";
  if (r === "EARLY_REVIEW") return "gold";
  return "default";
}

export function UpbitProfitabilityImprovementLabPanel({
  ubaId = 1380,
}: {
  ubaId?: number;
}) {
  const labQ = useQuery({
    queryKey: queryKeys.admin.upbitProfitabilityLabSummary(ubaId),
    queryFn: () => adminApi.getAdminUpbitProfitabilityLabSummary(ubaId),
    refetchInterval: 60_000,
  });

  if (labQ.isLoading) {
    return (
      <Typography.Text type="secondary">
        수익성 개선 Shadow Lab 불러오는 중…
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

  const data = asRecord(labQ.data) ?? {};
  const sampleN = asRecord(data.SAMPLE_N) ?? {};
  const sampleStatus = asRecord(data.SAMPLE_STATUS) ?? {};
  const cand = asRecord(data.CANDIDATES) ?? {};
  const exits = asRecord(data.EXITS) ?? {};
  const reentry = asRecord(data.REENTRY) ?? {};
  const candVars = asRecord(cand.VARIANTS) ?? {};
  const exitVars = asRecord(exits.VARIANTS) ?? {};
  const reVars = asRecord(reentry.VARIANTS) ?? {};

  const rows: VariantRow[] = [];
  for (const [vk, raw] of Object.entries(candVars)) {
    const v = asRecord(raw) ?? {};
    rows.push({
      key: `A-${vk}`,
      lab: "후보선정",
      variant: vk,
      label: String(v.LABEL ?? vk),
      n: Number(v.OBSERVATION_N ?? 0),
      metric: v.AVG_RETURN_30M == null ? null : Number(v.AVG_RETURN_30M),
      delta: v.DELTA_AVG_RETURN_30M == null ? null : Number(v.DELTA_AVG_RETURN_30M),
      readiness: String(v.READINESS ?? sampleStatus.CANDIDATE_SELECTION_V2 ?? "SAMPLE_PENDING"),
    });
  }
  for (const [vk, raw] of Object.entries(exitVars)) {
    const v = asRecord(raw) ?? {};
    rows.push({
      key: `B-${vk}`,
      lab: "Exit",
      variant: vk,
      label: String(v.LABEL ?? vk),
      n: Number(v.N ?? 0),
      metric: v.SHADOW_NET == null ? null : Number(v.SHADOW_NET),
      delta: v.DELTA_NET == null ? null : Number(v.DELTA_NET),
      readiness: String(v.READINESS ?? sampleStatus.EXIT_OPTIMIZATION_V4 ?? "SAMPLE_PENDING"),
    });
  }
  for (const [vk, raw] of Object.entries(reVars)) {
    const v = asRecord(raw) ?? {};
    rows.push({
      key: `C-${vk}`,
      lab: "재진입",
      variant: vk,
      label: String(v.LABEL ?? vk),
      n: Number(v.N ?? 0),
      metric: v.NET_ESTIMATED_DELTA == null ? null : Number(v.NET_ESTIMATED_DELTA),
      delta: v.BLOCKED_N == null ? null : Number(v.BLOCKED_N),
      readiness: String(v.READINESS ?? sampleStatus.REENTRY_ANTI_CHURN_V1 ?? "SAMPLE_PENDING"),
    });
  }

  const columns: ColumnsType<VariantRow> = [
    { title: "Lab", dataIndex: "lab", key: "lab", width: 90 },
    { title: "Variant", dataIndex: "variant", key: "variant", width: 70 },
    { title: "Label", dataIndex: "label", key: "label" },
    { title: "N", dataIndex: "n", key: "n", width: 70 },
    {
      title: "Metric",
      dataIndex: "metric",
      key: "metric",
      render: (v: number | null) => formatNumResearch(v),
    },
    {
      title: "Delta",
      dataIndex: "delta",
      key: "delta",
      render: (v: number | null) => formatNumResearch(v),
    },
    {
      title: "Status",
      dataIndex: "readiness",
      key: "readiness",
      render: (v: string) => <Tag color={readinessColor(v)}>{v || "—"}</Tag>,
    },
  ];

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="연구 전용 — 실제 매매 미적용"
        description="SHADOW_ONLY / FORWARD_ONLY. REAL candidate·entry·exit·reentry 정책은 변경되지 않습니다. 자동 승격 없음."
      />
      <Row gutter={[12, 12]}>
        <Col xs={24} md={8}>
          <Card size="small" title="후보선정 V2">
            <Statistic
              title="Refresh N"
              value={Number(sampleN.CANDIDATE_REFRESH_N ?? 0)}
            />
            <Tag color={readinessColor(String(sampleStatus.CANDIDATE_SELECTION_V2 ?? ""))}>
              {String(sampleStatus.CANDIDATE_SELECTION_V2 ?? "SAMPLE_PENDING")}
            </Tag>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small" title="Exit V4">
            <Statistic
              title="Enrollment N"
              value={Number(sampleN.EXIT_ENROLLMENT_N ?? 0)}
            />
            <Tag color={readinessColor(String(sampleStatus.EXIT_OPTIMIZATION_V4 ?? ""))}>
              {String(sampleStatus.EXIT_OPTIMIZATION_V4 ?? "SAMPLE_PENDING")}
            </Tag>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small" title="재진입 Anti-Churn">
            <Statistic
              title="Event N"
              value={Number(sampleN.REENTRY_EVENT_N ?? 0)}
            />
            <Tag color={readinessColor(String(sampleStatus.REENTRY_ANTI_CHURN_V1 ?? ""))}>
              {String(sampleStatus.REENTRY_ANTI_CHURN_V1 ?? "SAMPLE_PENDING")}
            </Tag>
          </Card>
        </Col>
      </Row>
      <Typography.Text type="secondary">
        ACTIVATED_AT={String(data.ACTIVATED_AT ?? "—")} · REAL_POLICY_CHANGED=
        {String(data.REAL_POLICY_CHANGED ?? false)} · COMBINED=
        {String(data.COMBINED_ESTIMATE ?? "INSUFFICIENT_DATA")}
      </Typography.Text>
      <Table<VariantRow>
        size="small"
        rowKey="key"
        columns={columns}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: "표본 수집 대기 (N=0 정상)" }}
      />
    </Space>
  );
}
