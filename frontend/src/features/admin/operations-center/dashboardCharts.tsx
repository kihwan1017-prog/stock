"use client";

import { Empty, Typography } from "antd";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

import { entryBlockReasonShortKo } from "@/features/admin/autotrading/entryBlockReasonKo";
import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";

import { formatKrw, formatPct } from "./autoTradingPerformanceHelpers";
import type { PerformanceChartType } from "./dashboardTabState";

const CHART_HEIGHT = 280;

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

export function ChartEmpty({ message }: { message?: string }) {
  return (
    <Empty
      image={Empty.PRESENTED_IMAGE_SIMPLE}
      description={message ?? "해당 기간의 AUTO 거래 실적이 없습니다."}
    />
  );
}

type ChartProps = {
  chart: PerformanceChartType;
  data: Record<string, unknown>;
  broker: string;
  height?: number;
};

export function DashboardPerformanceChart({
  chart,
  data,
  broker,
  height = CHART_HEIGHT,
}: ChartProps) {
  const daily = extractRows(data.daily_returns).map((r) => {
    const row = rec(r);
    return {
      date: String(row.trading_date ?? "").slice(5),
      pnl: Number(row.realized_pnl ?? 0),
      pct: Number(row.daily_return_pct ?? 0),
      trades: Number(row.trade_count ?? 0),
    };
  });

  const cumulative = extractRows(data.cumulative_returns).map((r) => {
    const row = rec(r);
    return {
      date: String(row.trading_date ?? "").slice(5),
      pnl: Number(row.cumulative_realized_pnl ?? 0),
      pct: Number(row.cumulative_return_pct ?? 0),
    };
  });

  const cumByBroker = extractRows(data.cumulative_by_broker);

  const symbols = extractRows(data.symbol_performance).map((r) => {
    const row = rec(r);
    return {
      symbol: String(row.symbol ?? "").replace("KRW-", ""),
      pnl: Number(row.realized_pnl ?? 0),
      pct: Number(row.return_pct ?? 0),
    };
  });

  const exits = extractRows(data.exit_reason_performance).map((r) => {
    const row = rec(r);
    return {
      name: String(row.exit_reason_label_ko ?? row.exit_reason_category),
      count: Number(row.trade_count ?? 0),
      pnl: Number(row.total_realized_pnl ?? 0),
    };
  });

  const winLoss = rec(data.win_loss);
  const winLossPie = [
    { name: "WIN", value: Number(winLoss.wins ?? 0) },
    { name: "LOSS", value: Number(winLoss.losses ?? 0) },
    { name: "FLAT", value: Number(winLoss.flats ?? 0) },
  ].filter((x) => x.value > 0);

  const roundTrips = extractRows(data.round_trips ?? data.recent_closed_trades).map(
    (r, i) => {
      const row = rec(r);
      return {
        id: String(row.binding_id ?? i),
        label: String(row.symbol ?? "").replace("KRW-", ""),
        pnl: Number(row.net_pnl ?? 0),
      };
    },
  );

  const holding = extractRows(data.holding_return).map((r) => {
    const row = rec(r);
    const hours = Number(row.duration_sec ?? 0) / 3600;
    return {
      x: hours,
      y: Number(row.return_pct ?? 0),
      symbol: String(row.symbol ?? "").replace("KRW-", ""),
      broker: String(row.broker_code ?? ""),
    };
  });

  const brokerCmp = extractRows(data.broker_comparison);

  const hasTrades = Number(data.closed_trade_count ?? 0) > 0;

  if (!hasTrades && chart !== "broker_compare") {
    return <ChartEmpty />;
  }

  if (chart === "cumulative_pnl") {
    if (broker === "ALL" && cumByBroker.length > 0) {
      const dates = [...new Set(cumByBroker.map((r) => String(rec(r).trading_date).slice(5)))];
      const merged = dates.map((date) => {
        const point: Record<string, string | number> = { date };
        for (const code of ["UPBIT", "KIWOOM"]) {
          const rows = cumByBroker.filter(
            (r) =>
              String(rec(r).trading_date).slice(5) === date &&
              rec(r).broker_code === code,
          );
          const last = rows[rows.length - 1];
          point[code] = last
            ? Number(rec(last).cumulative_realized_pnl ?? 0)
            : 0;
        }
        point.TOTAL = Number(
          cumulative.find((c) => c.date === date)?.pnl ?? 0,
        );
        return point;
      });
      return (
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={merged}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip formatter={(v: number) => formatKrw(v)} />
            <Legend />
            <Line dataKey="TOTAL" name="전체" stroke="#595959" dot={false} />
            <Line dataKey="UPBIT" name="UPBIT" stroke="#13c2c2" dot={false} />
            <Line dataKey="KIWOOM" name="KIWOOM" stroke="#722ed1" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      );
    }
    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={cumulative}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip formatter={(v: number) => formatKrw(v)} />
          <Line dataKey="pnl" name="누적손익" stroke="#1677ff" dot />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (chart === "daily_pnl") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={daily}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip formatter={(v: number) => formatKrw(v)} />
          <Bar dataKey="pnl" name="일별손익">
            {daily.map((entry, i) => (
              <Cell key={i} fill={entry.pnl >= 0 ? "#3f8600" : "#cf1322"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chart === "cumulative_return") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={cumulative}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis unit="%" />
          <Tooltip formatter={(v: number) => `${v}%`} />
          <Line dataKey="pct" name="누적 수익률" stroke="#1677ff" dot />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (chart === "symbol_pnl") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={symbols} layout="vertical">
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" />
          <YAxis type="category" dataKey="symbol" width={80} />
          <Tooltip formatter={(v: number) => formatKrw(v)} />
          <Bar dataKey="pnl" name="실현손익" fill="#1677ff" />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chart === "symbol_return") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={symbols}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="symbol" />
          <YAxis unit="%" />
          <Tooltip />
          <Bar dataKey="pct" name="수익률(%)" fill="#722ed1" />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chart === "win_loss") {
    if (!winLossPie.length) return <ChartEmpty />;
    return (
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Pie data={winLossPie} dataKey="value" nameKey="name" label />
          <Tooltip />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (chart === "exit_reason") {
    if (!exits.length) return <ChartEmpty />;
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={exits}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" />
          <YAxis />
          <Tooltip />
          <Bar dataKey="count" name="거래수" fill="#1677ff" />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chart === "trade_pnl") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={roundTrips}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="label" />
          <YAxis />
          <Tooltip formatter={(v: number) => formatKrw(v)} />
          <Bar dataKey="pnl" name="순손익">
            {roundTrips.map((entry, i) => (
              <Cell key={i} fill={entry.pnl >= 0 ? "#3f8600" : "#cf1322"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chart === "holding_return") {
    if (!holding.length) return <ChartEmpty />;
    return (
      <ResponsiveContainer width="100%" height={height}>
        <ScatterChart>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" dataKey="x" name="보유(시간)" unit="h" />
          <YAxis type="number" dataKey="y" name="수익률" unit="%" />
          <ZAxis range={[60, 60]} />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            formatter={(v: number, name: string) =>
              name === "y" ? formatPct(v) : `${v.toFixed(1)}h`
            }
          />
          <Scatter data={holding} fill="#1677ff" />
        </ScatterChart>
      </ResponsiveContainer>
    );
  }

  if (chart === "broker_compare") {
    const metrics = [
      { key: "realized_pnl", label: "누적손익", fmt: (v: number) => formatKrw(v) },
      { key: "trade_count", label: "거래수", fmt: (v: number) => String(v) },
      {
        key: "win_rate_pct",
        label: "승률(%)",
        fmt: (v: number) => (v != null ? `${v}%` : "—"),
      },
    ];
    const chartData = metrics.flatMap((m) =>
      brokerCmp.map((raw) => {
        const row = rec(raw);
        const code = String(row.broker_code);
        const val = row[m.key];
        return {
          metric: m.label,
          broker: code,
          value: val == null ? 0 : Number(val),
          display: row.has_trades === false ? "거래 없음" : m.fmt(Number(val)),
        };
      }),
    );
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="metric" />
          <YAxis />
          <Tooltip />
          <Legend />
          <Bar dataKey="value" name="값" fill="#1677ff" />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  return <Typography.Text type="secondary">지원하지 않는 차트</Typography.Text>;
}

export function EntryBlockerChart({
  blockers,
}: {
  blockers: Record<string, unknown>[];
}) {
  if (!blockers.length) {
    return <ChartEmpty message="Entry blocker 데이터 없음" />;
  }
  const rows = blockers.map((r) => {
    const row = rec(r);
    const code = String(row.reason_code ?? "");
    return {
      reason: entryBlockReasonShortKo(code),
      count: Number(row.count ?? 0),
      pct: Number(row.pct ?? 0),
    };
  });
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={rows} layout="vertical">
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis type="number" unit="%" />
        <YAxis type="category" dataKey="reason" width={160} />
        <Tooltip
          formatter={(v: number, name: string) =>
            name === "pct" ? `${v}%` : v
          }
        />
        <Bar dataKey="pct" name="비율(%)" fill="#fa8c16" />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function SummaryCumulativeChart({
  data,
  broker,
  height = 220,
}: {
  data: Record<string, unknown>;
  broker: string;
  height?: number;
}) {
  return (
    <DashboardPerformanceChart
      chart="cumulative_pnl"
      data={data}
      broker={broker}
      height={height}
    />
  );
}

export function SummaryDailyChart({
  data,
  height = 220,
}: {
  data: Record<string, unknown>;
  height?: number;
}) {
  return (
    <DashboardPerformanceChart
      chart="daily_pnl"
      data={data}
      broker="ALL"
      height={height}
    />
  );
}
