"use client";

/**
 * 시장 분석 — 사용자 관점 Summary 대시보드.
 * REAL trading gate / policy 아님 (projection only).
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  Collapse,
  Descriptions,
  Progress,
  Row,
  Space,
  Statistic,
  Typography,
} from "antd";
import Link from "next/link";
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { cell } from "@/features/admin/utils/dataHelpers";
import { adminRoutes } from "@/config/routes";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { withMarketQuery } from "@/features/admin/strategy-analysis/marketScope";
import { friendlyReasonKo } from "@/features/admin/market-analysis/userFriendlyReasons";

const COLORS = ["#16a34a", "#dc2626", "#94a3b8"];

function asRec(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
}

function asChartRows(v: unknown): { name: string; value: number }[] {
  if (!Array.isArray(v)) return [];
  return v
    .map((row) => {
      const r = asRec(row);
      return {
        name: String(r.name ?? ""),
        value: Number(r.value ?? 0),
      };
    })
    .filter((r) => r.name);
}

function DataSourceFooter({
  source,
}: {
  source: Record<string, unknown> | undefined;
}) {
  if (!source) return null;
  return (
    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
      데이터 기준: {cell(source.basis)} · 최종 수집: {cell(source.last_collect)} ·
      품질: {cell(source.quality)}
    </Typography.Text>
  );
}

function MiniPie({ rows }: { rows: { name: string; value: number }[] }) {
  if (!rows.length) {
    return <Typography.Text type="secondary">차트 데이터 부족</Typography.Text>;
  }
  return (
    <ResponsiveContainer width="100%" height={160}>
      <PieChart>
        <Pie data={rows} dataKey="value" nameKey="name" outerRadius={62} label>
          {rows.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip />
      </PieChart>
    </ResponsiveContainer>
  );
}

export function MarketAnalysisDashboardView() {
  const summaryQ = useQuery({
    queryKey: queryKeys.admin.marketAnalysisSummary(),
    queryFn: adminApi.getMarketAnalysisSummary,
    refetchInterval: 60_000,
  });

  const data = asRec(summaryQ.data);
  const kiwoom = asRec(data.kiwoom);
  const upbit = asRec(data.upbit);
  const entry = asRec(data.autotrading_projection);
  const trust = asRec(data.data_trust);
  const atx = asRec(data.autotrading_context);
  const upbitAtx = asRec(atx.UPBIT);
  const kiwoomAtx = asRec(atx.KIWOOM);
  const kiwoomCharts = asChartRows(asRec(kiwoom.breadth).charts);
  const upbitCharts = asChartRows(asRec(upbit.charts).breadth);

  return (
    <AdminPageShell
      title="시장 분석"
      description="지금 시장 상황과 자동매매 관점 요약 (설명용 · REAL 게이트 아님)"
    >
      <Space orientation="vertical" size={10} style={{ width: "100%" }}>
        {summaryQ.error ? (
          <Alert type="error" showIcon title={toApiError(summaryQ.error).message} />
        ) : null}

        {trust.stale_warning ? (
          <Alert
            type="warning"
            showIcon
            title={String(trust.stale_warning)}
            description="실시간 자동매매 장애가 아니라 일봉 historical 보정 상태입니다."
          />
        ) : null}

        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 0 }}
          title={cell(data.disclaimer) || "사용자 설명용 projection"}
        />

        <Row gutter={[10, 10]}>
          <Col xs={24} md={8}>
            <Card size="small" title="키움증권" loading={summaryQ.isLoading}>
              <Typography.Title level={4} style={{ marginTop: 0, marginBottom: 4 }}>
                {cell(kiwoom.session_label)}
              </Typography.Title>
              <Typography.Paragraph style={{ marginBottom: 4 }}>
                📈 {cell(kiwoom.direction)}
              </Typography.Paragraph>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 6 }}>
                거래 분위기: {cell(kiwoom.trade_mood)} · 변동성:{" "}
                {cell(kiwoom.volatility)}
              </Typography.Paragraph>
              <Typography.Paragraph style={{ marginBottom: 6 }}>
                {cell(kiwoom.narrative)}
              </Typography.Paragraph>
              <DataSourceFooter source={asRec(kiwoom.data_source)} />
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card size="small" title="업비트" loading={summaryQ.isLoading}>
              <Typography.Title level={4} style={{ marginTop: 0, marginBottom: 4 }}>
                {cell(upbit.user_status_label)}
              </Typography.Title>
              <Typography.Paragraph style={{ marginBottom: 4 }}>
                {cell(upbit.direction)}
              </Typography.Paragraph>
              <Space wrap size={16} style={{ marginBottom: 6 }}>
                <Statistic
                  title="Fear & Greed"
                  value={
                    upbit.fear_greed == null ? "—" : Number(upbit.fear_greed)
                  }
                />
                <Statistic
                  title="상승 종목"
                  value={
                    upbit.up_ratio_pct == null
                      ? "—"
                      : Number(upbit.up_ratio_pct)
                  }
                  suffix={upbit.up_ratio_pct == null ? undefined : "%"}
                />
              </Space>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 6 }}>
                거래대금: {cell(upbit.turnover)} · 변동성: {cell(upbit.volatility)} ·{" "}
                {cell(upbit.btc_eth_direction)}
              </Typography.Paragraph>
              <Typography.Paragraph style={{ marginBottom: 6 }}>
                {cell(upbit.narrative)}
              </Typography.Paragraph>
              <DataSourceFooter source={asRec(upbit.data_source)} />
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card size="small" title="자동매매 관점" loading={summaryQ.isLoading}>
              <Typography.Text type="secondary">현재 진입환경</Typography.Text>
              <Typography.Title level={3} style={{ marginTop: 4, marginBottom: 4 }}>
                {cell(entry.entry_environment_label)}
              </Typography.Title>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
                {cell(entry.note)}
              </Typography.Paragraph>
              <Progress
                percent={
                  entry.entry_environment === "GOOD"
                    ? 85
                    : entry.entry_environment === "NEUTRAL"
                      ? 55
                      : 30
                }
                status={
                  entry.entry_environment === "CAUTION" ? "exception" : "active"
                }
                showInfo={false}
              />
            </Card>
          </Col>
        </Row>

        <Row gutter={[10, 10]}>
          <Col xs={24} md={12}>
            <Card size="small" title="키움 상승/하락/보합">
              <MiniPie rows={kiwoomCharts} />
            </Card>
          </Col>
          <Col xs={24} md={12}>
            <Card size="small" title="업비트 상승/하락 비율">
              <MiniPie rows={upbitCharts} />
            </Card>
          </Col>
        </Row>

        <Card size="small" title="현재 자동매매 상태 (요약)">
          <Row gutter={[12, 12]}>
            <Col xs={24} md={12}>
              <Typography.Text strong>UPBIT</Typography.Text>
              <Descriptions size="small" column={1} style={{ marginTop: 4 }}>
                <Descriptions.Item label="후보">
                  {cell(upbitAtx.candidates)}
                </Descriptions.Item>
                <Descriptions.Item label="WAITING">
                  {cell(upbitAtx.waiting)}
                </Descriptions.Item>
                <Descriptions.Item label="OPEN">
                  {cell(upbitAtx.open)}
                </Descriptions.Item>
                <Descriptions.Item label="FIRST_ZERO">
                  {cell(upbitAtx.first_zero)}
                </Descriptions.Item>
                <Descriptions.Item label="사유">
                  {cell(upbitAtx.no_trade_reason) ||
                    friendlyReasonKo(
                      upbitAtx.no_trade_reason_code
                        ? String(upbitAtx.no_trade_reason_code)
                        : null,
                    )}
                </Descriptions.Item>
              </Descriptions>
              <Collapse
                size="small"
                items={[
                  {
                    key: "raw-upbit",
                    label: "원본 code (상세)",
                    children: (
                      <Typography.Text code>
                        {cell(upbitAtx.no_trade_reason_code) || "—"}
                      </Typography.Text>
                    ),
                  },
                ]}
              />
            </Col>
            <Col xs={24} md={12}>
              <Typography.Text strong>KIWOOM</Typography.Text>
              <Descriptions size="small" column={1} style={{ marginTop: 4 }}>
                <Descriptions.Item label="Universe">
                  {cell(kiwoomAtx.universe)}
                </Descriptions.Item>
                <Descriptions.Item label="Scanner">
                  {cell(kiwoomAtx.scanner)}
                </Descriptions.Item>
                <Descriptions.Item label="Candidate">
                  {cell(kiwoomAtx.candidates)}
                </Descriptions.Item>
                <Descriptions.Item label="Signal">
                  {cell(kiwoomAtx.signal)}
                </Descriptions.Item>
                <Descriptions.Item label="FIRST_ZERO">
                  {cell(kiwoomAtx.first_zero)}
                </Descriptions.Item>
                <Descriptions.Item label="사유">
                  {cell(kiwoomAtx.no_trade_reason) ||
                    friendlyReasonKo(
                      kiwoomAtx.no_trade_reason_code
                        ? String(kiwoomAtx.no_trade_reason_code)
                        : null,
                    )}
                </Descriptions.Item>
              </Descriptions>
              <Collapse
                size="small"
                items={[
                  {
                    key: "raw-kiwoom",
                    label: "원본 code (상세)",
                    children: (
                      <Typography.Text code>
                        {cell(kiwoomAtx.no_trade_reason_code) || "—"}
                      </Typography.Text>
                    ),
                  },
                ]}
              />
            </Col>
          </Row>
          <div style={{ marginTop: 8 }}>
            <Link href={adminRoutes.autotradingProcess}>프로세스 보기</Link>
            {" · "}
            <Link href={adminRoutes.marketData}>시장 데이터</Link>
          </div>
        </Card>

        <Card size="small" title="데이터 신뢰 (계층 분리)">
          <Row gutter={16}>
            <Col xs={12} md={6}>
              <Typography.Text type="secondary">UPBIT 실시간</Typography.Text>
              <div>{cell(asRec(trust.realtime).UPBIT)}</div>
            </Col>
            <Col xs={12} md={6}>
              <Typography.Text type="secondary">UPBIT 일봉</Typography.Text>
              <div>{cell(asRec(trust.historical_daily).UPBIT)}</div>
            </Col>
            <Col xs={12} md={6}>
              <Typography.Text type="secondary">KIWOOM 실시간</Typography.Text>
              <div>{cell(asRec(trust.realtime).KIWOOM)}</div>
            </Col>
            <Col xs={12} md={6}>
              <Typography.Text type="secondary">KIWOOM 일봉</Typography.Text>
              <div>{cell(asRec(trust.historical_daily).KIWOOM)}</div>
            </Col>
          </Row>
        </Card>

        <Collapse
          items={[
            {
              key: "tech",
              label: "상세 분석 / 운영 도구",
              children: (
                <Space orientation="vertical" size={4}>
                  <Link href={withMarketQuery(adminRoutes.indicators, "KIWOOM")}>
                    기술지표 관리
                  </Link>
                  <Link
                    href={withMarketQuery(adminRoutes.aiMarketAnalyses, "KIWOOM")}
                  >
                    AI 시장·차트 분석
                  </Link>
                  <Link href={withMarketQuery(adminRoutes.upbitMarkets, "UPBIT")}>
                    업비트 시세·종목
                  </Link>
                  <Link href={withMarketQuery(adminRoutes.researchData, "UPBIT")}>
                    연구 데이터
                  </Link>
                  <Link href={adminRoutes.marketData}>시장 데이터 Explorer</Link>
                </Space>
              ),
            },
          ]}
        />
      </Space>
    </AdminPageShell>
  );
}
