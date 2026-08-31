"use client";

/**
 * Waiting Lifecycle Forward Shadow Lab V1 — RESEARCH ONLY.
 * REAL waiting release/expiry 변경 버튼 없음. 승격/정책변경 권장 문구 금지.
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
  variant: string;
  label: string;
  forwardN: number;
  active: number;
  expired: number;
  replaced: number;
  wouldAdmit: number;
  fullSlot: number;
  realBuy: number;
  expiredLaterBuy: number;
  medianWait: number | null;
  p90Wait: number | null;
  avgScore: number | null;
  readiness: string;
};

const VARIANT_LABEL: Record<string, string> = {
  R0: "R0 Current (REAL baseline)",
  R1: "R1 30m stale / 90m absolute",
  R2: "R2 20m stale / 60m absolute",
  R3: "R3 30m/90m + score replace(+10)",
};

export function UpbitWaitingLifecycleLabPanel({
  ubaId = 1380,
}: {
  ubaId?: number;
}) {
  const summaryQ = useQuery({
    queryKey: queryKeys.admin.upbitWaitingLifecycleLabSummary(ubaId),
    queryFn: () => adminApi.getAdminUpbitWaitingLifecycleLabSummary(ubaId),
    refetchInterval: 60_000,
  });
  const compareQ = useQuery({
    queryKey: queryKeys.admin.upbitWaitingLifecycleLabComparison(ubaId),
    queryFn: () => adminApi.getAdminUpbitWaitingLifecycleLabComparison(ubaId),
    refetchInterval: 60_000,
  });

  if (summaryQ.isLoading) {
    return (
      <Typography.Text type="secondary">
        Waiting Lifecycle Lab 불러오는 중…
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
  const variants = asRecord(root.variants);
  const rows: VariantRow[] = ["R0", "R1", "R2", "R3"].map((v) => {
    const vr = asRecord(variants[v]);
    return {
      key: v,
      variant: v,
      label: VARIANT_LABEL[v] ?? v,
      forwardN: Number(vr.forward_n ?? 0),
      active: Number(vr.active ?? 0),
      expired: Number(vr.expired ?? 0),
      replaced: Number(vr.replaced ?? 0),
      wouldAdmit: Number(vr.would_admit ?? 0),
      fullSlot: Number(vr.full_slot_block ?? 0),
      realBuy: Number(vr.real_buy_filled ?? 0),
      expiredLaterBuy: Number(
        vr.shadow_expired_but_real_later_bought ?? 0,
      ),
      medianWait:
        vr.median_waiting_age_min != null
          ? Number(vr.median_waiting_age_min)
          : null,
      p90Wait:
        vr.p90_waiting_age_min != null
          ? Number(vr.p90_waiting_age_min)
          : null,
      avgScore:
        vr.average_admitted_score != null
          ? Number(vr.average_admitted_score)
          : null,
      readiness: String(vr.readiness ?? "표본 수집 중"),
    };
  });

  const columns: ColumnsType<VariantRow> = [
    { title: "Variant", dataIndex: "label", key: "label" },
    { title: "Forward N", dataIndex: "forwardN", key: "forwardN" },
    { title: "Active", dataIndex: "active", key: "active" },
    { title: "Expired", dataIndex: "expired", key: "expired" },
    { title: "Replaced", dataIndex: "replaced", key: "replaced" },
    { title: "Would Admit", dataIndex: "wouldAdmit", key: "wouldAdmit" },
    { title: "Full Slot Block", dataIndex: "fullSlot", key: "fullSlot" },
    { title: "Real Buy", dataIndex: "realBuy", key: "realBuy" },
    {
      title: "Expired→Later Buy",
      dataIndex: "expiredLaterBuy",
      key: "expiredLaterBuy",
    },
    {
      title: "Median Wait(m)",
      dataIndex: "medianWait",
      key: "medianWait",
      render: (v: number | null) => (v == null ? "—" : v),
    },
    {
      title: "P90 Wait(m)",
      dataIndex: "p90Wait",
      key: "p90Wait",
      render: (v: number | null) => (v == null ? "—" : v),
    },
    {
      title: "Avg Score",
      dataIndex: "avgScore",
      key: "avgScore",
      render: (v: number | null) => (v == null ? "—" : v),
    },
    {
      title: "Review",
      dataIndex: "readiness",
      key: "readiness",
      render: (v: string) => <Tag>{v}</Tag>,
    },
  ];

  const early = root.early_review_ready === true;
  const strong = root.strong_review_ready === true;

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="REAL POLICY UNCHANGED"
        description={String(
          root.real_policy_note ??
            "Shadow R1/R2/R3는 research-only. REAL waiting release/expiry/replacement 불변.",
        )}
      />
      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Card size="small">
            <Statistic
              title="Primary Forward Start"
              value={String(root.primary_forward_start ?? "—")}
              valueStyle={{ fontSize: 14 }}
            />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small">
            <Statistic
              title="Preexisting Cohort N"
              value={Number(root.preexisting_cohort_n ?? 0)}
            />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small">
            <Statistic
              title="Review readiness"
              value={
                strong
                  ? "Strong Review Ready"
                  : early
                    ? "Early Review Ready"
                    : "표본 수집 중"
              }
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
      {compareQ.data != null ? (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          Comparison deltas are observational only. No promote / policy-change
          recommendation is generated.
        </Typography.Paragraph>
      ) : null}
    </Space>
  );
}
