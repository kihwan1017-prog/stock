/**
 * 오늘 거래현황 패널 — AUTO performance API 재사용 (조회 전용).
 */

"use client";

import {
  Alert,
  Card,
  Col,
  Empty,
  Row,
  Space,
  Statistic,
  theme,
  Tooltip,
  Typography,
} from "antd";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

import {
  durationLabel,
  formatKrw,
  formatPct,
  parsePerformanceSummary,
  type BrokerFilter,
} from "./autoTradingPerformanceHelpers";
import { useAutotradingPerformanceQuery } from "./useAutotradingPerformanceQuery";

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

type Props = {
  broker: BrokerFilter;
  enabled?: boolean;
  refreshMs?: number;
};

export function TodayTradingStatusPanel({
  broker,
  enabled = true,
  refreshMs = 20_000,
}: Props) {
  const { token } = theme.useToken();
  const todayQ = useAutotradingPerformanceQuery({
    broker,
    period: "TODAY",
    enabled,
    refreshMs,
  });

  const data = rec(todayQ.data);
  const summaryRaw = rec(data.summary);
  const summary = parsePerformanceSummary(summaryRaw);
  const activity = rec(data.today_order_activity);

  const buyCount = Number(activity.buy_count ?? 0);
  const sellCount = Number(activity.sell_count ?? 0);
  const filledCount = Number(activity.filled_count ?? 0);
  const openCount = Number(activity.open_count ?? 0);
  const cancelledCount = Number(activity.cancelled_count ?? 0);
  const buyAmount = num(activity.buy_amount);
  const sellAmount = num(activity.sell_amount);

  const profitAmount = num(summaryRaw.today_profit_amount);
  const lossAmount = num(summaryRaw.today_loss_amount);
  const netPnl = num(summaryRaw.today_net_pnl ?? summaryRaw.today_realized_pnl);
  const todayWins = Number(summaryRaw.today_wins ?? 0);
  const todayLosses = Number(summaryRaw.today_losses ?? 0);
  const todayWinRate = num(summaryRaw.today_win_rate_pct ?? summary.winRatePct);
  const symbolCount = Number(summaryRaw.today_symbol_count ?? 0);
  const closedCount = Number(
    summaryRaw.today_closed_trade_count ?? summary.closedTradeCount,
  );
  const fees = num(summaryRaw.today_fees);
  const avgHold = durationLabel(num(summaryRaw.today_avg_hold_sec) ?? undefined);
  const bestSymbol = summaryRaw.today_best_symbol
    ? String(summaryRaw.today_best_symbol).replace("KRW-", "")
    : null;
  const bestPnl = num(summaryRaw.today_best_pnl);
  const worstSymbol = summaryRaw.today_worst_symbol
    ? String(summaryRaw.today_worst_symbol).replace("KRW-", "")
    : null;
  const worstPnl = num(summaryRaw.today_worst_pnl);

  const hourly = extractRows(data.today_hourly_pnl).map((row) => {
    const r = rec(row);
    return {
      label: String(r.label ?? ""),
      realized: Number(r.realized_pnl ?? 0),
      cumulative: Number(r.cumulative_realized_pnl ?? 0),
    };
  });
  const hasHourlyActivity = hourly.some(
    (h) => h.realized !== 0 || h.cumulative !== 0,
  );
  const hasAnyActivity =
    buyCount + sellCount + filledCount + closedCount > 0 || hasHourlyActivity;

  const pnlTone = (v: number | null) => {
    if (v == null || v === 0) return undefined;
    return v > 0 ? token.colorSuccess : token.colorError;
  };

  return (
    <Card
      size="small"
      title="오늘 거래현황"
      extra={
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          KST 00:00 ~ 현재 · AUTO
        </Typography.Text>
      }
      loading={todayQ.isLoading && !todayQ.data}
    >
      {todayQ.isError ? (
        <Alert
          type="error"
          showIcon
          title="오늘 거래현황을 불러오지 못했습니다."
          description={toApiError(todayQ.error).message}
        />
      ) : !hasAnyActivity ? (
        <Empty description="오늘 체결된 거래가 없습니다." />
      ) : (
        <Space orientation="vertical" size={16} style={{ width: "100%" }}>
          <Row gutter={[12, 12]}>
            <Col xs={12} sm={8} md={4} lg={4}>
              <Statistic title="오늘 매수" value={buyCount} />
            </Col>
            <Col xs={12} sm={8} md={4} lg={4}>
              <Statistic title="오늘 매도" value={sellCount} />
            </Col>
            <Col xs={12} sm={8} md={4} lg={4}>
              <Statistic title="오늘 체결" value={filledCount} />
            </Col>
            <Col xs={12} sm={8} md={4} lg={4}>
              <Statistic title="오늘 미체결" value={openCount} />
            </Col>
            <Col xs={12} sm={8} md={4} lg={4}>
              <Statistic title="오늘 취소" value={cancelledCount} />
            </Col>
            <Col xs={12} sm={8} md={4} lg={4}>
              <Tooltip title="수수료를 포함한 실현 손익입니다.">
                <Statistic
                  title="오늘 순손익"
                  value={netPnl ?? 0}
                  precision={0}
                  suffix="원"
                  styles={{ content: { color: pnlTone(netPnl) } }}
                  formatter={(v) =>
                    Number(v).toLocaleString("ko-KR", { maximumFractionDigits: 0 })
                  }
                />
              </Tooltip>
            </Col>
            <Col xs={12} sm={8} md={4} lg={4}>
              <Tooltip title="선택 기간의 매수·매도 거래 수수료 합계입니다.">
                <Statistic
                  title="수수료"
                  value={fees ?? 0}
                  precision={0}
                  suffix="원"
                  formatter={(v) =>
                    Number(v).toLocaleString("ko-KR", { maximumFractionDigits: 0 })
                  }
                />
              </Tooltip>
            </Col>
          </Row>

          <Row gutter={[12, 12]}>
            <Col xs={12} sm={8} md={6}>
              <Statistic
                title="오늘 수익금액"
                value={profitAmount ?? 0}
                precision={0}
                prefix="+"
                suffix="원"
                styles={{ content: { color: token.colorSuccess } }}
                formatter={(v) =>
                  Number(v).toLocaleString("ko-KR", { maximumFractionDigits: 0 })
                }
              />
            </Col>
            <Col xs={12} sm={8} md={6}>
              <Statistic
                title="오늘 손실금액"
                value={lossAmount ?? 0}
                precision={0}
                suffix="원"
                styles={{ content: { color: token.colorError } }}
                formatter={(v) =>
                  Number(v).toLocaleString("ko-KR", { maximumFractionDigits: 0 })
                }
              />
            </Col>
            <Col xs={12} sm={8} md={6}>
              <Statistic title="승/패" value={`${todayWins}/${todayLosses}`} />
            </Col>
            <Col xs={12} sm={8} md={6}>
              <Statistic title="승률" value={formatPct(todayWinRate)} />
            </Col>
          </Row>

          <Row gutter={[12, 12]}>
            <Col xs={12} sm={8} md={6} lg={4}>
              <Statistic title="거래 종목 수" value={symbolCount} />
            </Col>
            <Col xs={12} sm={8} md={6} lg={4}>
              <Statistic title="완료된 매매" value={closedCount} />
            </Col>
            <Col xs={12} sm={8} md={6} lg={4}>
              <Statistic
                title="총 매수금액"
                value={buyAmount ?? 0}
                precision={0}
                suffix="원"
                formatter={(v) =>
                  Number(v).toLocaleString("ko-KR", { maximumFractionDigits: 0 })
                }
              />
            </Col>
            <Col xs={12} sm={8} md={6} lg={4}>
              <Statistic
                title="총 매도금액"
                value={sellAmount ?? 0}
                precision={0}
                suffix="원"
                formatter={(v) =>
                  Number(v).toLocaleString("ko-KR", { maximumFractionDigits: 0 })
                }
              />
            </Col>
            <Col xs={12} sm={8} md={6} lg={4}>
              <Statistic
                title="총 수수료"
                value={fees ?? 0}
                precision={0}
                suffix="원"
                formatter={(v) =>
                  Number(v).toLocaleString("ko-KR", { maximumFractionDigits: 0 })
                }
              />
            </Col>
            <Col xs={12} sm={8} md={6} lg={4}>
              <Typography.Text type="secondary" style={{ display: "block", fontSize: 12 }}>
                평균 보유시간
              </Typography.Text>
              <Typography.Text strong>{avgHold}</Typography.Text>
            </Col>
          </Row>

          {(bestSymbol || worstSymbol) && (
            <Row gutter={[12, 12]}>
              <Col xs={24} sm={12}>
                <Typography.Text type="secondary">최대 수익 종목 · </Typography.Text>
                <Typography.Text>
                  {bestSymbol ?? "—"}
                  {bestPnl != null ? ` (${formatKrw(bestPnl)})` : ""}
                </Typography.Text>
              </Col>
              <Col xs={24} sm={12}>
                <Typography.Text type="secondary">최대 손실 종목 · </Typography.Text>
                <Typography.Text>
                  {worstSymbol ?? "—"}
                  {worstPnl != null ? ` (${formatKrw(worstPnl)})` : ""}
                </Typography.Text>
              </Col>
            </Row>
          )}

          <div style={{ width: "100%", height: 220 }}>
            {hasHourlyActivity ? (
              <ResponsiveContainer>
                <ComposedChart data={hourly}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} interval={2} />
                  <YAxis
                    yAxisId="left"
                    width={56}
                    tickFormatter={(v) =>
                      Number(v).toLocaleString("ko-KR", {
                        notation: "compact",
                        maximumFractionDigits: 1,
                      })
                    }
                  />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    width={56}
                    tickFormatter={(v) =>
                      Number(v).toLocaleString("ko-KR", {
                        notation: "compact",
                        maximumFractionDigits: 1,
                      })
                    }
                  />
                  <Tooltip
                    formatter={(value, name) => [
                      formatKrw(Number(value)),
                      name === "realized" ? "실현손익" : "누적손익",
                    ]}
                  />
                  <Legend
                    formatter={(value) =>
                      value === "realized" ? "실현손익" : "누적손익"
                    }
                  />
                  <Bar
                    yAxisId="left"
                    dataKey="realized"
                    name="realized"
                    fill={token.colorPrimary}
                    opacity={0.75}
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="cumulative"
                    name="cumulative"
                    stroke={token.colorInfo}
                    dot={false}
                    strokeWidth={2}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="오늘 청산된 거래의 시간별 손익이 없습니다."
              />
            )}
          </div>
        </Space>
      )}
    </Card>
  );
}
