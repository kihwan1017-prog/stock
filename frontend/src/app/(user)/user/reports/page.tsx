"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Space, Table, Tag, Typography } from "antd";

import { cell, extractRows } from "@/shared/utils/dataHelpers";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { PortfolioAssetHistorySection } from "@/features/user/portfolio/PortfolioAssetHistorySection";
import { useMyPaperAccountId } from "@/features/user/hooks/useMyPaperAccountId";
import * as userApi from "@/features/user/api/userApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";

function formatNumber(value: unknown): string {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  return num.toLocaleString("ko-KR");
}

function settlementTagColor(status: string): string {
  if (status === "SUCCEEDED" || status === "SUCCEEDED_WITH_WARNINGS") {
    return "success";
  }
  if (status === "RUNNING" || status === "PENDING") return "processing";
  if (status === "RETRY_PENDING") return "warning";
  if (status === "MANUAL_REVIEW_REQUIRED" || status === "FAILED") {
    return "error";
  }
  return "default";
}

export default function UserReportsPage() {
  const { accountId } = useMyPaperAccountId();

  const settlementsQuery = useQuery({
    queryKey: [...queryKeys.user.executions(), "settlements"],
    queryFn: () => userApi.listMySettlements({ limit: 20 }),
  });

  const snapshotStatusQuery = useQuery({
    queryKey: [...queryKeys.user.executions(), "broker-snapshots"],
    queryFn: () => userApi.listMyBrokerSnapshotStatus(),
  });

  const executionsQuery = useQuery({
    queryKey: [...queryKeys.user.executions(), "reports", { account_id: accountId }],
    queryFn: () =>
      userApi.listExecutions({ limit: 50, account_id: accountId as number }),
    enabled: accountId != null,
  });

  const paperOrdersQuery = useQuery({
    queryKey: [...queryKeys.user.paperOrders(), "reports", { account_id: accountId }],
    queryFn: () => userApi.listPaperOrders({ account_id: accountId as number }),
    enabled: accountId != null,
  });

  const executionRows = extractRows(executionsQuery.data);
  const paperOrderRows = extractRows(paperOrdersQuery.data);
  const settlementItems = settlementsQuery.data?.items ?? [];
  const latestSettlement = settlementItems[0];

  return (
    <UserPageShell
      title="내 리포트"
      description="자산 변화 · 손익 · 정산 · 최근 거래 내역 — 본인 계좌 기준"
    >
      {accountId == null ? (
        <Alert
          type="info"
          showIcon
          title="Paper 계좌를 불러오는 중입니다."
        />
      ) : null}

      <Card
        title="Broker Snapshot 상태"
        size="small"
        loading={snapshotStatusQuery.isLoading}
        style={{ marginBottom: 16 }}
      >
        {snapshotStatusQuery.error ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(snapshotStatusQuery.error).message}
          />
        ) : (snapshotStatusQuery.data?.items?.length ?? 0) > 0 ? (
          <Space wrap>
            {(snapshotStatusQuery.data?.items ?? []).map((item) => (
              <Tag
                key={item.broker_code}
                color={item.is_fresh ? "success" : "warning"}
              >
                {item.broker_code}: {item.status_label}
              </Tag>
            ))}
          </Space>
        ) : (
          <Typography.Text type="secondary">
            연결된 LIVE 계좌 Snapshot이 없습니다.
          </Typography.Text>
        )}
      </Card>

      <Card
        title="일일 정산 상태"
        size="small"
        loading={settlementsQuery.isLoading}
        style={{ marginBottom: 16 }}
      >
        {settlementsQuery.error ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(settlementsQuery.error).message}
          />
        ) : latestSettlement ? (
          <>
            <Alert
              type={
                latestSettlement.needs_manual_review
                  ? "warning"
                  : latestSettlement.status_code.startsWith("SUCCEEDED")
                    ? "success"
                    : "info"
              }
              showIcon
              title={latestSettlement.status_label}
              description={
                latestSettlement.has_mismatch
                  ? "잔고·포지션 불일치가 감지되어 관리자 확인이 필요할 수 있습니다."
                  : "손익 값은 서버 정산 결과입니다 (프론트 재계산 없음)."
              }
              style={{ marginBottom: 12 }}
            />
            <Table
              size="small"
              pagination={{ pageSize: 5 }}
              rowKey={(row) => String(row.settlement_id)}
              dataSource={settlementItems}
              columns={[
                { title: "날짜", dataIndex: "market_date", render: cell },
                { title: "거래소/증권사", dataIndex: "broker_code", render: cell },
                {
                  title: "상태",
                  dataIndex: "status_code",
                  render: (v: string, row) => (
                    <Tag color={settlementTagColor(v)}>
                      {row.status_label}
                    </Tag>
                  ),
                },
                { title: "실현손익", dataIndex: "realized_pnl", render: cell },
                { title: "미실현", dataIndex: "unrealized_pnl", render: cell },
                { title: "수수료", dataIndex: "fees", render: cell },
                { title: "순손익", dataIndex: "net_pnl", render: cell },
                {
                  title: "평가금액",
                  dataIndex: "closing_equity",
                  render: cell,
                },
              ]}
            />
          </>
        ) : (
          <Typography.Text type="secondary">
            아직 정산 이력이 없습니다.
          </Typography.Text>
        )}
      </Card>

      <PortfolioAssetHistorySection accountId={accountId} />

      <Card
        title="일일 거래 리포트 — 최근 체결"
        size="small"
        style={{ marginTop: 16 }}
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
            pagination={{ pageSize: 10 }}
            rowKey={(row) =>
              String(
                row.execution_id ?? row.trading_execution_id ?? row.order_id,
              )
            }
            dataSource={executionRows}
            locale={{ emptyText: "체결 내역 없음" }}
            columns={[
              { title: "주문", dataIndex: "order_id", render: cell },
              { title: "심볼", dataIndex: "symbol", render: cell },
              {
                title: "수량",
                dataIndex: "quantity",
                render: (v, row) => formatNumber(v ?? row.execution_quantity),
              },
              {
                title: "가격",
                dataIndex: "price",
                render: (v) => formatNumber(v),
              },
              {
                title: "시각",
                dataIndex: "executed_at",
                render: (v, row) => cell(v ?? row.created_at),
              },
            ]}
          />
        )}
      </Card>

      <Card
        title="Paper 주문 이력"
        size="small"
        style={{ marginTop: 16 }}
        loading={paperOrdersQuery.isLoading}
      >
        {paperOrdersQuery.error ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(paperOrdersQuery.error).message}
          />
        ) : (
          <Table
            size="small"
            pagination={{ pageSize: 10 }}
            rowKey={(row) => String(row.paper_order_id)}
            dataSource={paperOrderRows}
            locale={{ emptyText: "주문 이력 없음" }}
            columns={[
              { title: "ID", dataIndex: "paper_order_id", render: cell },
              { title: "심볼", dataIndex: "symbol", render: cell },
              { title: "측", dataIndex: "side", render: cell },
              {
                title: "수량",
                dataIndex: "requested_quantity",
                render: (v, row) => formatNumber(v ?? row.quantity),
              },
              {
                title: "상태",
                dataIndex: "status_code",
                render: (v, row) => <Tag>{cell(v ?? row.status)}</Tag>,
              },
            ]}
          />
        )}
      </Card>

      <Card title="전략 성과 리포트" size="small" style={{ marginTop: 16 }}>
        <UnimplementedNotice
          feature="계좌별 전략 성과 리포트"
          reason="paper_order/paper_trade 테이블에 strategy_code 연결 컬럼이 없어 계좌 단위로 '어떤 전략이 이 손익을 냈는지' 집계할 수 없습니다. 전략 성과(strategy_performance)는 백테스트/시뮬레이션 실행 단위로만 저장되어 있어 실거래 계좌와 연결되어 있지 않습니다."
          relatedApis={[
            "GET /api/v1/user/strategies/performance/runs/{id} (백테스트 실행 단위, 계좌 연결 없음)",
          ]}
        />
      </Card>
    </UserPageShell>
  );
}
