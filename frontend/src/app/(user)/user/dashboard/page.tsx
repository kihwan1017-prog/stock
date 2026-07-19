"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Flex,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useMemo } from "react";

import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { pickFocusSymbol } from "@/features/user/dashboard/pickFocusSymbol";
import { useMyPaperAccountId } from "@/features/user/hooks/useMyPaperAccountId";
import * as userApi from "@/features/user/api/userApi";
import { userRoutes } from "@/config/routes";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";

const DEFAULT_EXCHANGE = "KRX";

function formatNumber(value: unknown, suffix = ""): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const num = Number(value);
  if (Number.isFinite(num)) {
    return `${num.toLocaleString("ko-KR")}${suffix}`;
  }
  return `${cell(value)}${suffix}`;
}

function formatPct(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const num = Number(value);
  if (Number.isFinite(num)) {
    return `${num.toFixed(4)}%`;
  }
  return cell(value);
}

function pnlColor(value: unknown): string | undefined {
  const num = Number(value);
  if (!Number.isFinite(num) || num === 0) return undefined;
  return num < 0 ? "#cf1322" : "#3f8600";
}

function tableRowKey(row: Record<string, unknown>, fields: string[]): string {
  for (const field of fields) {
    const value = row[field];
    if (value !== null && value !== undefined && value !== "") {
      return String(value);
    }
  }
  try {
    return JSON.stringify(row);
  } catch {
    return "unknown-row";
  }
}

export default function UserDashboardPage() {
  const { accountId } = useMyPaperAccountId();

  const kpisQuery = useQuery({
    queryKey: queryKeys.user.investmentKpis(accountId ?? 0),
    queryFn: () =>
      userApi.getInvestmentKpis({
        account_id: accountId as number,
        market_code: DEFAULT_EXCHANGE,
        mode_code: "PAPER",
        recent_limit: 10,
      }),
    enabled: accountId != null,
    refetchInterval: 30_000,
  });

  const positionsQuery = useQuery({
    queryKey: queryKeys.user.paperPositions(accountId ?? 0),
    queryFn: () => userApi.getPaperPositions(accountId as number),
    enabled: accountId != null,
    refetchInterval: 30_000,
  });

  const paperOrdersQuery = useQuery({
    queryKey: queryKeys.user.paperOrders(),
    queryFn: () => userApi.listPaperOrders(),
  });

  const ordersQuery = useQuery({
    queryKey: [...queryKeys.user.orders(), { limit: 10 }],
    queryFn: () => userApi.listOrders({ limit: 10, offset: 0 }),
  });

  const executionsQuery = useQuery({
    queryKey: [...queryKeys.user.executions(), { limit: 10 }],
    queryFn: () => userApi.listExecutions({ limit: 10 }),
  });

  const aiQuery = useQuery({
    queryKey: queryKeys.user.topCandidates(DEFAULT_EXCHANGE),
    queryFn: () => userApi.getTopCandidates(DEFAULT_EXCHANGE),
  });

  const strategyQuery = useQuery({
    queryKey: queryKeys.user.activeDeployment(DEFAULT_EXCHANGE),
    queryFn: () =>
      userApi.getActiveStrategyDeployment({
        market_code: DEFAULT_EXCHANGE,
        mode: "PAPER",
      }),
  });

  const killQuery = useQuery({
    queryKey: queryKeys.user.killSwitch(),
    queryFn: userApi.getKillSwitch,
    refetchInterval: 30_000,
  });

  const summary = asRecord(kpisQuery.data);
  const kpis = asRecord(summary?.kpis);
  const activeStrategies = extractRows(summary?.active_strategies);
  const kill = asRecord(killQuery.data);

  const positionRows = useMemo(() => {
    const fromExtract = extractRows(positionsQuery.data);
    if (fromExtract.length) return fromExtract;
    if (Array.isArray(positionsQuery.data)) {
      return positionsQuery.data as Record<string, unknown>[];
    }
    return [];
  }, [positionsQuery.data]);

  const aiRows = useMemo(
    () => extractRows(aiQuery.data).slice(0, 8),
    [aiQuery.data],
  );

  const focusSymbol = useMemo(
    () => pickFocusSymbol(aiRows, positionRows),
    [aiRows, positionRows],
  );

  const newsQuery = useQuery({
    queryKey: queryKeys.user.news(DEFAULT_EXCHANGE, focusSymbol),
    queryFn: () => userApi.getNewsContext(DEFAULT_EXCHANGE, focusSymbol),
  });

  const disclosuresQuery = useQuery({
    queryKey: queryKeys.user.dartDisclosures(focusSymbol),
    queryFn: () =>
      userApi.listDartDisclosures({
        stock_code: focusSymbol,
        limit: 10,
      }),
  });

  const paperOrderRows = extractRows(paperOrdersQuery.data);
  const tradingOrderRows = extractRows(ordersQuery.data);
  // Paper 계좌 컨텍스트이므로 paper-orders 우선
  const orderRows = (paperOrderRows.length ? paperOrderRows : tradingOrderRows).slice(
    0,
    10,
  );
  const orderSource = paperOrderRows.length ? "paper-orders" : "orders";

  const executionRows = extractRows(executionsQuery.data).slice(0, 10);
  const newsRows = extractRows(newsQuery.data).slice(0, 8);
  const disclosureRows = extractRows(disclosuresQuery.data).slice(0, 8);

  const strategyFromActive = (() => {
    const rows = extractRows(strategyQuery.data);
    if (rows.length) return rows;
    const one = asRecord(strategyQuery.data);
    return one ? [one] : [];
  })();
  const strategyRows =
    strategyFromActive.length > 0 ? strategyFromActive : activeStrategies;

  const unrealized = Number(kpis?.unrealized_pnl ?? NaN);
  const realized = Number(kpis?.realized_pnl ?? NaN);
  const todayPnl = Number(kpis?.today_pnl ?? NaN);

  const killActive = Boolean(
    kill?.active ?? kill?.enabled ?? kill?.is_active ?? kill?.kill_switch_enabled,
  );
  const killStatus = String(kill?.status ?? (killActive ? "ACTIVE" : "INACTIVE"));

  const kpiError = kpisQuery.error ? toApiError(kpisQuery.error) : null;

  return (
    <UserPageShell
      title="Dashboard"
      description={`투자 요약 · Paper #${accountId ?? "…"} · ${DEFAULT_EXCHANGE} · STEP42`}
      extra={
        <Space wrap>
          <Button size="small">
            <Link href={userRoutes.portfolio}>포트폴리오</Link>
          </Button>
          <Button size="small">
            <Link href={userRoutes.trading}>매매</Link>
          </Button>
          <Button size="small">
            <Link href={userRoutes.ai}>AI</Link>
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Flex wrap gap={8} align="center">
          <Tag color={killStatus.toUpperCase() === "ACTIVE" ? "error" : "success"}>
            Kill Switch: {killStatus.toUpperCase() || "…"}
          </Tag>
          <Tag>Mode: PAPER</Tag>
          <Tag>Account: #{accountId ?? "…"}</Tag>
          <Tag>평가: {cell(kpis?.valuation_mode ?? "…")}</Tag>
          <Tag>포커스: {focusSymbol}</Tag>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            회원 전용 Dashboard API 없음 — admin-summary / Paper·공용 API 사용
          </Typography.Text>
        </Flex>

        {kpiError ? (
          <Alert
            type="error"
            showIcon
            title="KPI 조회 실패"
            description={kpiError.message}
          />
        ) : null}

        {/* KPI — Admin Dashboard와 동일 라벨 */}
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} lg={6}>
            <Card size="small" loading={kpisQuery.isLoading}>
              <Statistic
                title="총 자산"
                value={formatNumber(kpis?.total_equity)}
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                현금 {formatNumber(kpis?.available_cash)}
              </Typography.Text>
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card size="small" loading={kpisQuery.isLoading}>
              <Statistic
                title="평가 손익"
                value={formatNumber(kpis?.unrealized_pnl)}
                styles={{ content: { color: pnlColor(unrealized) } }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card size="small" loading={kpisQuery.isLoading}>
              <Statistic
                title="실현 손익"
                value={formatNumber(kpis?.realized_pnl)}
                styles={{ content: { color: pnlColor(realized) } }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card size="small" loading={kpisQuery.isLoading}>
              <Statistic
                title="일일 수익률"
                value={formatPct(kpis?.today_return_rate)}
                styles={{ content: { color: pnlColor(todayPnl) } }}
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                오늘 PnL {formatNumber(kpis?.today_pnl)}
              </Typography.Text>
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          {/* 보유 종목 요약 */}
          <Col xs={24} lg={12}>
            <Card
              title="보유 종목 요약"
              size="small"
              loading={positionsQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /paper-accounts/{accountId}/positions
                </Typography.Text>
              }
            >
              {positionsQuery.error ? (
                <Alert
                  type="error"
                  showIcon
                  title={toApiError(positionsQuery.error).message}
                />
              ) : (
                <Table
                  size="small"
                  pagination={false}
                  rowKey={(row) =>
                    tableRowKey(row, [
                      "symbol",
                      "paper_position_id",
                      "exchange_code",
                    ])
                  }
                  dataSource={positionRows.slice(0, 10)}
                  locale={{ emptyText: "보유 종목 없음" }}
                  columns={[
                    { title: "심볼", dataIndex: "symbol", render: cell },
                    {
                      title: "거래소",
                      dataIndex: "exchange_code",
                      width: 80,
                      render: cell,
                    },
                    {
                      title: "수량",
                      dataIndex: "quantity",
                      render: (v) => formatNumber(v),
                    },
                    {
                      title: "평단",
                      dataIndex: "average_entry_price",
                      render: (v) => formatNumber(v),
                    },
                  ]}
                />
              )}
            </Card>
          </Col>

          {/* 실행 중 전략 */}
          <Col xs={24} lg={12}>
            <Card
              title="실행 중 전략"
              size="small"
              loading={strategyQuery.isLoading || kpisQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /strategy-deployments/active
                </Typography.Text>
              }
            >
              {strategyQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title={toApiError(strategyQuery.error).message}
                />
              ) : null}
              <Table
                size="small"
                pagination={false}
                rowKey={(row) =>
                  tableRowKey(row, [
                    "strategy_deployment_id",
                    "strategy_code",
                    "symbol",
                  ])
                }
                dataSource={strategyRows.slice(0, 10)}
                locale={{ emptyText: "ACTIVE 전략 없음" }}
                columns={[
                  {
                    title: "전략",
                    dataIndex: "strategy_code",
                    render: cell,
                  },
                  { title: "심볼", dataIndex: "symbol", render: cell },
                  {
                    title: "모드",
                    dataIndex: "mode_code",
                    width: 80,
                    render: (v) => cell(v ?? "PAPER"),
                  },
                  {
                    title: "상태",
                    dataIndex: "status_code",
                    width: 90,
                    render: (v) => (
                      <Tag color="success">{cell(v ?? "ACTIVE")}</Tag>
                    ),
                  },
                ]}
              />
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          {/* 최근 주문 */}
          <Col xs={24} lg={12}>
            <Card
              title="최근 주문"
              size="small"
              loading={paperOrdersQuery.isLoading || ordersQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /{orderSource}
                </Typography.Text>
              }
            >
              {paperOrdersQuery.error && ordersQuery.error ? (
                <Alert
                  type="error"
                  showIcon
                  title={toApiError(paperOrdersQuery.error).message}
                />
              ) : (
                <Table
                  size="small"
                  pagination={false}
                  rowKey={(row) =>
                    tableRowKey(row, [
                      "paper_order_id",
                      "order_id",
                      "symbol",
                    ])
                  }
                  dataSource={orderRows}
                  locale={{ emptyText: "주문 없음" }}
                  columns={[
                    {
                      title: "ID",
                      width: 70,
                      render: (_v, row) =>
                        cell(row.paper_order_id ?? row.order_id),
                    },
                    { title: "심볼", dataIndex: "symbol", render: cell },
                    {
                      title: "측",
                      dataIndex: "side",
                      width: 70,
                      render: (v, row) => cell(v ?? row.side_code),
                    },
                    {
                      title: "상태",
                      dataIndex: "status_code",
                      width: 100,
                      render: (v) => <Tag>{cell(v)}</Tag>,
                    },
                  ]}
                />
              )}
            </Card>
          </Col>

          {/* 최근 체결 */}
          <Col xs={24} lg={12}>
            <Card
              title="최근 체결"
              size="small"
              loading={executionsQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /executions
                </Typography.Text>
              }
            >
              {executionsQuery.error ? (
                <Alert
                  type="error"
                  showIcon
                  title={toApiError(executionsQuery.error).message}
                />
              ) : (
                <Table
                  size="small"
                  pagination={false}
                  rowKey={(row) =>
                    tableRowKey(row, [
                      "execution_id",
                      "trading_execution_id",
                      "order_id",
                      "symbol",
                    ])
                  }
                  dataSource={executionRows}
                  locale={{ emptyText: "체결 없음" }}
                  columns={[
                    {
                      title: "주문",
                      dataIndex: "order_id",
                      width: 70,
                      render: cell,
                    },
                    { title: "심볼", dataIndex: "symbol", render: cell },
                    {
                      title: "수량",
                      dataIndex: "quantity",
                      render: (v) => formatNumber(v),
                    },
                    {
                      title: "가격",
                      dataIndex: "price",
                      render: (v) => formatNumber(v),
                    },
                  ]}
                />
              )}
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          {/* AI 추천 종목 */}
          <Col xs={24} lg={8}>
            <Card
              title="AI 추천 종목"
              size="small"
              loading={aiQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /candidates/top/{DEFAULT_EXCHANGE}
                </Typography.Text>
              }
            >
              {aiQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title={toApiError(aiQuery.error).message}
                />
              ) : (
                <Table
                  size="small"
                  pagination={false}
                  rowKey={(row) =>
                    tableRowKey(row, ["symbol", "total_score", "score"])
                  }
                  dataSource={aiRows}
                  locale={{ emptyText: "추천 없음" }}
                  columns={[
                    {
                      title: "#",
                      width: 40,
                      render: (_v, _row, index) => cell(index + 1),
                    },
                    { title: "심볼", dataIndex: "symbol", render: cell },
                    {
                      title: "점수",
                      dataIndex: "total_score",
                      render: (v, row) =>
                        formatNumber(v ?? row.score ?? row.rank_score),
                    },
                  ]}
                />
              )}
            </Card>
          </Col>

          {/* 주요 뉴스 */}
          <Col xs={24} lg={8}>
            <Card
              title={`주요 뉴스 · ${focusSymbol}`}
              size="small"
              loading={newsQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /news/{DEFAULT_EXCHANGE}/{focusSymbol}
                </Typography.Text>
              }
            >
              {newsQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title={toApiError(newsQuery.error).message}
                />
              ) : (
                <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                  {newsRows.length === 0 ? (
                    <Typography.Text type="secondary">뉴스 없음</Typography.Text>
                  ) : (
                    newsRows.map((row, index) => (
                      <div
                        key={
                          tableRowKey(row, ["original_link", "title"]) + index
                        }
                      >
                        <Typography.Text
                          strong
                          style={{ fontSize: 12, display: "block" }}
                        >
                          {cell(row.title ?? row.headline)}
                        </Typography.Text>
                        <Typography.Text
                          type="secondary"
                          style={{ fontSize: 11 }}
                        >
                          {cell(row.summary ?? row.published_at)}
                        </Typography.Text>
                      </div>
                    ))
                  )}
                </Space>
              )}
            </Card>
          </Col>

          {/* 주요 공시 */}
          <Col xs={24} lg={8}>
            <Card
              title={`주요 공시 · ${focusSymbol}`}
              size="small"
              loading={disclosuresQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /dart/disclosures
                </Typography.Text>
              }
            >
              {disclosuresQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title={toApiError(disclosuresQuery.error).message}
                />
              ) : (
                <Table
                  size="small"
                  pagination={false}
                  rowKey={(row) =>
                    tableRowKey(row, [
                      "disclosure_id",
                      "receipt_no",
                      "report_name",
                    ])
                  }
                  dataSource={disclosureRows}
                  locale={{ emptyText: "공시 없음" }}
                  columns={[
                    {
                      title: "보고서",
                      dataIndex: "report_name",
                      ellipsis: true,
                      render: cell,
                    },
                    {
                      title: "일자",
                      dataIndex: "receipt_date",
                      width: 100,
                      render: cell,
                    },
                  ]}
                />
              )}
            </Card>
          </Col>
        </Row>

        {/* 관심종목 — API 없음 */}
        <Card title="관심종목" size="small">
          {/* TODO: GET /api/v1/user/watchlist — 회원 관심종목 API 신규 필요 */}
          <UnimplementedNotice
            feature="관심종목"
            reason="Backend에 회원 관심종목(watchlist) API가 없습니다. 추가 후 Dashboard에 연결합니다."
            relatedApis={[
              "TODO: GET /api/v1/user/watchlist",
              "TODO: POST /api/v1/user/watchlist",
              "TODO: DELETE /api/v1/user/watchlist/{symbol}",
            ]}
          />
        </Card>
      </Space>
    </UserPageShell>
  );
}
