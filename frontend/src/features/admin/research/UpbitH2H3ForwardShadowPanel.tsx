"use client";

/**
 * WRK-019 H2/H3 frozen forward-shadow — RESEARCH ONLY.
 * Historical(WRK-018) vs Forward Shadow 분리 표시.
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

import * as adminApi from "@/features/admin/api/adminApi";
import { formatNumResearch } from "@/features/admin/upbit/researchDetailFormat";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

function hzPf(row: Record<string, unknown> | null | undefined, key: string) {
  const hz = asRecord(row?.horizons);
  const h = asRecord(hz?.[key]);
  return formatNumResearch(h?.pf);
}

function hzNet(row: Record<string, unknown> | null | undefined, key: string) {
  const hz = asRecord(row?.horizons);
  const h = asRecord(hz?.[key]);
  return formatNumResearch(h?.total_net);
}

export function UpbitH2H3ForwardShadowPanel() {
  const q = useQuery({
    queryKey: queryKeys.admin.upbitResearchH2H3ForwardShadowSummary(),
    queryFn: () => adminApi.getAdminUpbitResearchH2H3ForwardShadowSummary(),
    refetchInterval: 60_000,
  });

  if (q.isLoading) {
    return (
      <Typography.Text type="secondary">
        Forward Shadow 불러오는 중…
      </Typography.Text>
    );
  }
  if (q.isError) {
    return (
      <Alert
        type="error"
        showIcon
        title="조회 실패"
        description={toApiError(q.error).message}
      />
    );
  }

  const data = asRecord(q.data);
  if (!data?.ok) {
    return (
      <Alert type="warning" showIcon title="요약 없음" description="API ok=false" />
    );
  }

  const hist = asRecord(data.historical);
  const fwd = asRecord(data.forward_shadow);
  const h2 = asRecord(fwd?.H2);
  const h3 = asRecord(fwd?.H3);
  const histH2 = asRecord(hist?.H2);
  const histH3 = asRecord(hist?.H3);
  const safety = asRecord(data.safety);

  const tableRows = [
    {
      key: "H2",
      strategy: "H2",
      rule: String(h2?.rule_hash ?? "—"),
      started: String(fwd?.started_at ?? "—"),
      pending: h2?.pending ?? 0,
      completed: h2?.complete ?? 0,
      oppDay: asRecord(h2?.summary_primary)?.opportunities_day,
      pf30: hzPf(h2, "30m"),
      pf60: hzPf(h2, "60m"),
      pf120: hzPf(h2, "120m"),
      net: formatNumResearch(asRecord(h2?.summary_primary)?.total_net),
      readiness: String(h2?.readiness ?? "—"),
    },
    {
      key: "H3",
      strategy: "H3",
      rule: String(h3?.rule_hash ?? "—"),
      started: String(fwd?.started_at ?? "—"),
      pending: h3?.pending ?? 0,
      completed: h3?.complete ?? 0,
      oppDay: asRecord(h3?.summary_primary)?.opportunities_day,
      pf30: hzPf(h3, "30m"),
      pf60: hzPf(h3, "60m"),
      pf120: hzPf(h3, "120m"),
      net: formatNumResearch(asRecord(h3?.summary_primary)?.total_net),
      readiness: String(h3?.readiness ?? "—"),
    },
  ];

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="Forward Shadow · REAL 미적용"
        description="H2/H3 규칙 freeze. Quantile 재계산 없음. StrategySignal/주문 경로 차단. Historical과 Forward를 합산하지 않습니다."
      />
      <Row gutter={[12, 12]}>
        <Col xs={24} md={8}>
          <Card size="small">
            <Statistic
              title="Started (UTC)"
              value={String(fwd?.started_at ?? "—")}
            />
          </Card>
        </Col>
        <Col xs={12} md={8}>
          <Card size="small">
            <Statistic
              title="Shadow orders"
              value={Number(safety?.real_order_created_by_shadow ?? 0)}
            />
          </Card>
        </Col>
        <Col xs={12} md={8}>
          <Card size="small">
            <Statistic
              title="Signal published"
              value={Number(safety?.strategy_signal_published ?? 0)}
            />
          </Card>
        </Col>
      </Row>

      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        Forward Shadow
      </Typography.Title>
      <Table
        size="small"
        pagination={false}
        rowKey="key"
        dataSource={tableRows}
        columns={[
          { title: "Strategy", dataIndex: "strategy", key: "s" },
          { title: "Rule", dataIndex: "rule", key: "r", ellipsis: true },
          { title: "Started", dataIndex: "started", key: "st", ellipsis: true },
          { title: "Pending", dataIndex: "pending", key: "p" },
          { title: "Completed", dataIndex: "completed", key: "c" },
          {
            title: "Opp/day",
            dataIndex: "oppDay",
            key: "o",
            render: (v) => formatNumResearch(v),
          },
          { title: "PF30", dataIndex: "pf30", key: "p30" },
          { title: "PF60", dataIndex: "pf60", key: "p60" },
          { title: "PF120", dataIndex: "pf120", key: "p120" },
          { title: "Net(primary)", dataIndex: "net", key: "n" },
          {
            title: "Readiness",
            dataIndex: "readiness",
            key: "rd",
            render: (v) => <Tag>{String(v)}</Tag>,
          },
        ]}
      />

      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        Historical Test (WRK-018) — reference only
      </Typography.Title>
      <Table
        size="small"
        pagination={false}
        rowKey="k"
        dataSource={[
          {
            k: "H2",
            strategy: "H2",
            source: "HISTORICAL",
            valN: asRecord(histH2?.validation)?.n,
            valPf: asRecord(histH2?.validation)?.pf,
            valNet: asRecord(histH2?.validation)?.total_net,
            testN: asRecord(histH2?.test)?.n,
            testPf: asRecord(histH2?.test)?.pf,
            testNet: asRecord(histH2?.test)?.total_net,
          },
          {
            k: "H3",
            strategy: "H3",
            source: "HISTORICAL",
            valN: asRecord(histH3?.validation)?.n,
            valPf: asRecord(histH3?.validation)?.pf,
            valNet: asRecord(histH3?.validation)?.total_net,
            testN: asRecord(histH3?.test)?.n,
            testPf: asRecord(histH3?.test)?.pf,
            testNet: asRecord(histH3?.test)?.total_net,
          },
        ]}
        columns={[
          { title: "Strategy", dataIndex: "strategy", key: "s" },
          { title: "Source", dataIndex: "source", key: "src" },
          {
            title: "VAL N/PF/NET",
            key: "val",
            render: (_, r) =>
              `${formatNumResearch(r.valN)} / ${formatNumResearch(r.valPf)} / ${formatNumResearch(r.valNet)}`,
          },
          {
            title: "TEST N/PF/NET",
            key: "test",
            render: (_, r) =>
              `${formatNumResearch(r.testN)} / ${formatNumResearch(r.testPf)} / ${formatNumResearch(r.testNet)}`,
          },
        ]}
      />
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Net30/60/120 diagnostics: H2 {hzNet(h2, "30m")} / {hzNet(h2, "60m")} /{" "}
        {hzNet(h2, "120m")} · H3 {hzNet(h3, "30m")} / {hzNet(h3, "60m")} /{" "}
        {hzNet(h3, "120m")} · Primary horizon={String(fwd?.primary_horizon_min ?? 60)}m
      </Typography.Paragraph>
    </Space>
  );
}
