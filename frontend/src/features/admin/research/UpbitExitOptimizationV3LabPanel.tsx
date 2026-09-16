"use client";

/**
 * Exit Optimization Shadow Lab V3 — RESEARCH ONLY.
 * REAL exit 정책 변경/승격 버튼 없음.
 */

import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Col, Row, Space, Statistic, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import * as adminApi from "@/features/admin/api/adminApi";
import { formatNumResearch } from "@/features/admin/upbit/researchDetailFormat";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type V3Row = {
  key: string;
  variant: string;
  label: string;
  n: number;
  baselineNet: number | null;
  shadowNet: number | null;
  deltaNet: number | null;
  pf: number | null;
  mdd: number | null;
  fees: number | null;
  lt30Count: number;
  lt30Net: number | null;
  deferred: number;
  readiness: string;
};

const VARIANT_ORDER = ["R0", "E1", "E2", "E3", "E4"];

export function UpbitExitOptimizationV3LabPanel({
  ubaId = 1380,
}: {
  ubaId?: number;
}) {
  const labQ = useQuery({
    queryKey: queryKeys.admin.upbitExitOptimizationV3Summary(ubaId),
    queryFn: () => adminApi.getAdminUpbitExitOptimizationV3Summary(ubaId),
    refetchInterval: 60_000,
  });

  if (labQ.isLoading) {
    return (
      <Typography.Text type="secondary">
        Exit Optimization V3 불러오는 중…
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
  const variants = asRecord(data?.VARIANTS) ?? {};
  const labels = asRecord(data?.VARIANT_LABELS) ?? {};

  const rows: V3Row[] = VARIANT_ORDER.map((vk) => {
    const v = asRecord(variants[vk]) ?? {};
    return {
      key: vk,
      variant: vk,
      label: String(labels[vk] ?? vk),
      n: Number(v.VALID_PAIRED_N ?? 0),
      baselineNet: v.BASELINE_NET == null ? null : Number(v.BASELINE_NET),
      shadowNet: v.SHADOW_NET == null ? null : Number(v.SHADOW_NET),
      deltaNet: v.DELTA_NET == null ? null : Number(v.DELTA_NET),
      pf: v.SHADOW_PF == null ? null : Number(v.SHADOW_PF),
      mdd: v.SHADOW_MDD == null ? null : Number(v.SHADOW_MDD),
      fees:
        v.SHADOW_ESTIMATED_FEES == null
          ? null
          : Number(v.SHADOW_ESTIMATED_FEES),
      lt30Count: Number(v.LT30S_SHADOW_COUNT ?? 0),
      lt30Net:
        v.LT30S_SHADOW_NET == null ? null : Number(v.LT30S_SHADOW_NET),
      deferred: Number(v.DEFERRED_TRAILING_COUNT ?? 0),
      readiness: String(v.READINESS ?? "SAMPLE_PENDING"),
    };
  });

  const columns: ColumnsType<V3Row> = [
    { title: "Variant", dataIndex: "label", ellipsis: true },
    { title: "N", dataIndex: "n", width: 56 },
    {
      title: "Base Net",
      dataIndex: "baselineNet",
      render: (v) => formatNumResearch(v),
    },
    {
      title: "Shadow Net",
      dataIndex: "shadowNet",
      render: (v) => formatNumResearch(v),
    },
    {
      title: "ΔNet",
      dataIndex: "deltaNet",
      render: (v) => formatNumResearch(v),
    },
    { title: "PF", dataIndex: "pf", render: (v) => formatNumResearch(v) },
    { title: "MDD", dataIndex: "mdd", render: (v) => formatNumResearch(v) },
    { title: "Fees", dataIndex: "fees", render: (v) => formatNumResearch(v) },
    { title: "<30s", dataIndex: "lt30Count", width: 56 },
    {
      title: "<30s Net",
      dataIndex: "lt30Net",
      render: (v) => formatNumResearch(v),
    },
    { title: "Defer", dataIndex: "deferred", width: 56 },
    {
      title: "Readiness",
      dataIndex: "readiness",
      render: (v: string) => {
        const color =
          v === "PROMOTION_REVIEW_ELIGIBLE"
            ? "gold"
            : v === "PRIMARY_REVIEW"
              ? "blue"
              : v === "EARLY_REVIEW"
                ? "cyan"
                : "default";
        return <Tag color={color}>{v}</Tag>;
      },
    },
  ];

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="Exit Optimization Shadow Lab V3 — RESEARCH ONLY"
        description="TRAILING/churn 연구 전용. REAL exit 정책 불변. AUTO_PROMOTION=false."
      />
      <Row gutter={[12, 12]}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="FORWARD_START"
              value={String(data?.FORWARD_START_AT ?? "—").slice(0, 10)}
              styles={{ content: { fontSize: 14 } }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="VALID_PAIRED_N_MAX"
              value={Number(data?.VALID_PAIRED_N_MAX ?? 0)}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="READINESS" value={String(data?.READINESS ?? "—")} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="AUTO_PROMOTION"
              value="FORBIDDEN"
              styles={{ content: { fontSize: 16 } }}
            />
          </Card>
        </Col>
      </Row>
      <div style={{ overflowX: "auto" }}>
        <Table
          size="small"
          pagination={false}
          rowKey="key"
          columns={columns}
          dataSource={rows}
          scroll={{ x: 960 }}
        />
      </div>
    </Space>
  );
}
