"use client";

/**
 * WRK-016 Positive-edge entry discovery — RESEARCH ONLY.
 * WRK-015 turnover tab과 동일 연구 워크스페이스에 통합.
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

export function UpbitPositiveEdgeEntryResearchPanel() {
  const q = useQuery({
    queryKey: queryKeys.admin.upbitResearchPositiveEdgeEntrySummary(),
    queryFn: () => adminApi.getAdminUpbitResearchPositiveEdgeEntrySummary(),
  });

  if (q.isLoading) {
    return (
      <Typography.Text type="secondary">
        Entry 전략 비교 불러오는 중…
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
      <Alert
        type="warning"
        showIcon
        title="증거 파일 없음"
        description={String(data?.message ?? "WRK-016 evidence missing")}
      />
    );
  }

  const rec = asRecord(data.recommendation);
  const families = Array.isArray(data.families) ? data.families : [];
  const regime = asRecord(data.regime);
  const wf = asRecord(data.walk_forward);
  const classification = String(data.classification ?? rec?.CLASSIFICATION ?? "—");

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="연구용 · REAL 미적용"
        description="Market-wide opportunity · cost-aware · walk-forward. LIVE/ARM/Entry production 변경 없음."
      />
      <Row gutter={[12, 12]}>
        <Col xs={24} md={8}>
          <Card size="small">
            <Statistic title="분류" value={classification} />
          </Card>
        </Col>
        <Col xs={12} md={8}>
          <Card size="small">
            <Statistic
              title="WF best (VAL→TEST)"
              value={String(wf?.BEST_TEST_STRATEGY ?? "—")}
            />
          </Card>
        </Col>
        <Col xs={12} md={8}>
          <Card size="small">
            <Statistic
              title="TEST PF / Net"
              value={`${formatNumResearch(wf?.TEST_PF)} / ${formatNumResearch(wf?.TEST_NET)}`}
            />
          </Card>
        </Col>
      </Row>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Regime counts:{" "}
        <Tag>BULL {String(regime?.BULL ?? 0)}</Tag>
        <Tag>BEAR {String(regime?.BEAR ?? 0)}</Tag>
        <Tag>SIDE {String(regime?.SIDEWAYS ?? 0)}</Tag>
        <Tag>HIGH_VOL {String(regime?.HIGH_VOL ?? 0)}</Tag>
      </Typography.Paragraph>
      <Table
        size="small"
        pagination={false}
        rowKey={(r) => String(asRecord(r)?.family ?? Math.random())}
        dataSource={families.map((p) => asRecord(p) ?? {})}
        columns={[
          { title: "전략", dataIndex: "family", key: "f" },
          {
            title: "N",
            dataIndex: "n",
            key: "n",
            render: (v) => formatNumResearch(v),
          },
          {
            title: "거래/일",
            dataIndex: "trades_day",
            key: "td",
            render: (v) => formatNumResearch(v),
          },
          {
            title: "승률%",
            dataIndex: "win_rate",
            key: "wr",
            render: (v) => formatNumResearch(v),
          },
          {
            title: "PF",
            dataIndex: "pf",
            key: "pf",
            render: (v) => formatNumResearch(v),
          },
          {
            title: "평균순익",
            dataIndex: "avg_net_trade",
            key: "avg",
            render: (v) => formatNumResearch(v),
          },
          {
            title: "총순익",
            dataIndex: "total_net",
            key: "net",
            render: (v) => formatNumResearch(v),
          },
          {
            title: "MDD",
            dataIndex: "mdd",
            key: "mdd",
            render: (v) => formatNumResearch(v),
          },
          { title: "적합시장", dataIndex: "best_regime", key: "br" },
          { title: "Conf", dataIndex: "confidence", key: "c" },
        ]}
      />
    </Space>
  );
}
