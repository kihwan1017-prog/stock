"use client";

/**
 * WRK-015 Upbit short-term turnover strategy comparison — RESEARCH ONLY.
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
import { dash, formatNumResearch } from "@/features/admin/upbit/researchDetailFormat";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export function UpbitShortTermTurnoverResearchPanel() {
  const q = useQuery({
    queryKey: queryKeys.admin.upbitResearchShortTermTurnoverSummary(),
    queryFn: () => adminApi.getAdminUpbitResearchShortTermTurnoverSummary(),
  });

  if (q.isLoading) {
    return (
      <Typography.Text type="secondary">
        단기 회전 전략 비교 불러오는 중…
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
        description={String(data?.message ?? "WRK-015 research evidence missing")}
      />
    );
  }

  const rec = asRecord(data.recommendation);
  const base = asRecord(data.baseline);
  const profiles = Array.isArray(data.profiles) ? data.profiles : [];
  const bottlenecks = Array.isArray(data.bottlenecks) ? data.bottlenecks : [];

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="연구용 · REAL 미적용"
        description="비용(수수료+슬리피지) 포함 shadow 비교입니다. LIVE/ARM/주문 정책은 변경되지 않습니다."
      />
      <Row gutter={[12, 12]}>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="권장 프로필"
              value={String(rec?.RECOMMENDED_PROFILE ?? "—")}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="기대 거래/일"
              value={formatNumResearch(rec?.EXPECTED_TRADES_PER_DAY)}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="기대 순손익(샘플)"
              value={formatNumResearch(rec?.EXPECTED_NET)}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="신뢰도" value={String(rec?.CONFIDENCE ?? "—")} />
          </Card>
        </Col>
      </Row>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        현재 baseline 거래/일≈{dash(base?.TRADES_PER_DAY)} · 평균보유(h)≈
        {dash(base?.AVG_HOLDING_HOURS)} · 병목:{" "}
        {bottlenecks.slice(0, 5).map((b, i) => (
          <Tag key={`${b}-${i}`}>{String(b)}</Tag>
        ))}
      </Typography.Paragraph>
      <Table
        size="small"
        rowKey={(r) => String(asRecord(r)?.profile ?? Math.random())}
        pagination={false}
        dataSource={profiles.map((p) => asRecord(p) ?? {})}
        columns={[
          { title: "전략", dataIndex: "profile", key: "profile" },
          {
            title: "거래/일",
            dataIndex: "trades_per_day",
            key: "tpd",
            render: (v) => formatNumResearch(v),
          },
          {
            title: "0거래일%",
            dataIndex: "zero_trade_days_pct",
            key: "z",
            render: (v) => formatNumResearch(v),
          },
          {
            title: "보유(분)",
            dataIndex: "median_holding_minutes",
            key: "h",
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
            dataIndex: "profit_factor",
            key: "pf",
            render: (v) => formatNumResearch(v),
          },
          {
            title: "순손익",
            dataIndex: "net_pnl",
            key: "net",
            render: (v) => formatNumResearch(v),
          },
          {
            title: "수수료",
            dataIndex: "fees",
            key: "fee",
            render: (v) => formatNumResearch(v),
          },
          {
            title: "MDD",
            dataIndex: "max_drawdown",
            key: "mdd",
            render: (v) => formatNumResearch(v),
          },
        ]}
      />
    </Space>
  );
}
