"use client";

/**
 * 수익성 개선 Shadow Lab V1 — RESEARCH ONLY.
 * Candidate V2 / Exit V4 / Reentry Anti-Churn / MA-DC churn — REAL 매매 미적용.
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

type ChurnSymbolRow = {
  key: string;
  symbol: string;
  maDcExitN: number;
  reentryN: number;
  netPnl: number | null;
  c1Delta: number | null;
  c2Delta: number | null;
  c3Delta: number | null;
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
  const maDc = asRecord(data.MA_DC) ?? {};
  const churn = asRecord(data.MA_DC_REENTRY_CHURN) ?? asRecord(reentry.MA_DC_CHURN) ?? {};
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

  const lt60 = asRecord(churn.MA_DC_REENTRY_LT_60S) ?? {};
  const lt180 = asRecord(churn.MA_DC_REENTRY_LT_180S) ?? {};
  const lt300 = asRecord(churn.MA_DC_REENTRY_LT_300S) ?? {};
  const byC1 = asRecord(asRecord(lt300.BY_VARIANT)?.C1) ?? {};
  const byC2 = asRecord(asRecord(lt300.BY_VARIANT)?.C2) ?? {};
  const byC3 = asRecord(asRecord(lt300.BY_VARIANT)?.C3) ?? {};

  const symbolRows: ChurnSymbolRow[] = (
    Array.isArray(churn.SYMBOL_RANK) ? churn.SYMBOL_RANK : []
  ).map((raw, idx) => {
    const s = asRecord(raw) ?? {};
    return {
      key: String(s.symbol ?? idx),
      symbol: String(s.symbol ?? "—"),
      maDcExitN: Number(s.MA_DC_EXIT_N ?? 0),
      reentryN: Number(s.REENTRY_N ?? 0),
      netPnl: s.NET_PNL == null ? null : Number(s.NET_PNL),
      c1Delta: s.C1_DELTA == null ? null : Number(s.C1_DELTA),
      c2Delta: s.C2_DELTA == null ? null : Number(s.C2_DELTA),
      c3Delta: s.C3_DELTA == null ? null : Number(s.C3_DELTA),
    };
  });

  const churnColumns: ColumnsType<ChurnSymbolRow> = [
    { title: "종목", dataIndex: "symbol", key: "symbol" },
    { title: "MA DC Exit", dataIndex: "maDcExitN", key: "maDcExitN", width: 100 },
    { title: "재진입", dataIndex: "reentryN", key: "reentryN", width: 80 },
    {
      title: "REAL 손익",
      dataIndex: "netPnl",
      key: "netPnl",
      render: (v: number | null) => formatNumResearch(v),
    },
    {
      title: "C1 예상 차이",
      dataIndex: "c1Delta",
      key: "c1Delta",
      render: (v: number | null) => formatNumResearch(v),
    },
    {
      title: "C2 예상 차이",
      dataIndex: "c2Delta",
      key: "c2Delta",
      render: (v: number | null) => formatNumResearch(v),
    },
    {
      title: "C3 예상 차이",
      dataIndex: "c3Delta",
      key: "c3Delta",
      render: (v: number | null) => formatNumResearch(v),
    },
  ];

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="연구 전용 — 실제 주문 영향 없음"
        description="SHADOW_ONLY / FORWARD_ONLY. REAL candidate·entry·exit·reentry 정책은 변경되지 않습니다. 자동 승격 없음."
      />
      <Row gutter={[12, 12]}>
        <Col xs={24} md={6}>
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
        <Col xs={24} md={6}>
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
        <Col xs={24} md={6}>
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
        <Col xs={24} md={6}>
          <Card size="small" title="MA Dead Cross Lab">
            <Statistic
              title="Event N"
              value={Number(sampleN.MA_DC_EVENT_N ?? maDc.EVENT_N ?? 0)}
            />
            <Tag color={readinessColor(String(maDc.READINESS ?? sampleStatus.MA_DEAD_CROSS_OPTIMIZATION_SHADOW_LAB_V1 ?? ""))}>
              {String(maDc.HOOK_STATUS ?? maDc.READINESS ?? "SAMPLE_PENDING")}
            </Tag>
          </Card>
        </Col>
      </Row>

      <Card
        size="small"
        title="MA 데드크로스 재진입"
        extra={<Tag color="purple">연구 전용 · 실제 주문 영향 없음</Tag>}
      >
        <Row gutter={[12, 12]}>
          <Col xs={12} md={4}>
            <Statistic title="MA DC Exit" value={Number(churn.MA_DC_EXIT_COUNT ?? 0)} />
          </Col>
          <Col xs={12} md={4}>
            <Statistic title="재진입 전체" value={Number(churn.MA_DC_REENTRY_COUNT ?? 0)} />
          </Col>
          <Col xs={12} md={4}>
            <Statistic title="재진입 &lt;1분" value={Number(lt60.N ?? 0)} />
          </Col>
          <Col xs={12} md={4}>
            <Statistic title="재진입 &lt;3분" value={Number(lt180.N ?? 0)} />
          </Col>
          <Col xs={12} md={4}>
            <Statistic title="재진입 &lt;5분" value={Number(lt300.N ?? 0)} />
          </Col>
          <Col xs={12} md={4}>
            <Statistic
              title="REAL 손익(버킷)"
              value={formatNumResearch(
                lt300.baseline_real_net == null
                  ? null
                  : Number(lt300.baseline_real_net),
              )}
            />
          </Col>
        </Row>
        <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
          <Col xs={24} md={8}>
            <Statistic
              title="C1 예상 차이 (&lt;5분)"
              value={formatNumResearch(
                byC1.estimated_net_delta == null
                  ? null
                  : Number(byC1.estimated_net_delta),
              )}
            />
          </Col>
          <Col xs={24} md={8}>
            <Statistic
              title="C2 예상 차이 (&lt;5분)"
              value={formatNumResearch(
                byC2.estimated_net_delta == null
                  ? null
                  : Number(byC2.estimated_net_delta),
              )}
            />
          </Col>
          <Col xs={24} md={8}>
            <Statistic
              title="C3 예상 차이 (&lt;5분)"
              value={formatNumResearch(
                byC3.estimated_net_delta == null
                  ? null
                  : Number(byC3.estimated_net_delta),
              )}
            />
          </Col>
        </Row>
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 8 }}>
          종목별 churn 순위 · C2/C3 분화=
          {String(reentry.C2_C3_CONTEXT_DISTINGUISHABLE ?? false)} · C3 UNKNOWN context N=
          {String(reentry.C3_UNKNOWN_CONTEXT_N ?? 0)}
        </Typography.Paragraph>
        <Table<ChurnSymbolRow>
          size="small"
          rowKey="key"
          columns={churnColumns}
          dataSource={symbolRows}
          pagination={false}
          locale={{ emptyText: "MA_DEAD_CROSS 재진입 표본 대기" }}
        />
      </Card>

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
