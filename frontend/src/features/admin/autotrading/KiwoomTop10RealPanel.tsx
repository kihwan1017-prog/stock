"use client";

/**
 * Kiwoom TOP10 REAL Multi-Symbol — READ-ONLY 운영 패널.
 * Trading logic / LIVE·ARM WRITE 없음. 기존 multi-symbol status API 재사용.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  Empty,
  Grid,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import {
  kiwoomCrossStateLabelKo,
  kiwoomFreshCrossLabelKo,
  kiwoomModeTitleKo,
  kiwoomSignalStatusLabelKo,
  kiwoomWhyNoTradeLabelKo,
} from "@/features/admin/autotrading/kiwoomTop10Labels";
import { asRecord } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type Top10Row = {
  key: string;
  rank: number;
  symbol: string;
  name: string;
  price: string;
  changePct: string;
  tradingValue: string;
  sma5: string;
  sma20: string;
  crossLabel: string;
  freshLabel: string;
  watchLabel: string;
  whyLabel: string;
  evaluatedAt: string;
};

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

function fmtNum(v: unknown, digits = 0): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString("ko-KR", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits > 0 ? Math.min(digits, 2) : 0,
  });
}

function fmtPct(v: unknown): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function fmtTime(v: unknown): string {
  if (v == null || v === "") return "—";
  const d = new Date(String(v));
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleString("ko-KR", { hour12: false });
}

export function KiwoomTop10RealPanel({ ubaId }: { ubaId: number }) {
  const screens = Grid.useBreakpoint();
  const isCompact = !screens.md;

  const statusQ = useQuery({
    queryKey: queryKeys.admin.kiwoomMultiSymbolStatus(ubaId),
    queryFn: () => adminApi.getAdminKiwoomMultiSymbolStatus(ubaId),
    enabled: ubaId > 0,
    refetchInterval: 20_000,
  });

  const root = rec(statusQ.data);
  const universe = rec(root.universe);
  const feed = rec(root.feed);
  const counts = rec(root.counts);
  const why = rec(root.why_no_trade_summary);
  const blockers = rec(why.per_symbol_blockers);

  const mode = String(root.MULTI_SYMBOL_MODE ?? root.mode ?? "SHADOW");
  const realEnabled = Boolean(
    root.MULTI_SYMBOL_REAL_ENABLED ?? root.REAL_MULTI_SYMBOL_ENABLED,
  );
  const shadowObs = Boolean(root.MULTI_SYMBOL_SHADOW_OBSERVABILITY_ENABLED);
  const monitored = Number(universe.monitored_count ?? 0);
  const monitorTarget = Number(universe.monitor_target ?? 10);
  const subscribed = Number(feed.subscribed_symbol_count ?? 0);
  const socketCount = Number(feed.physical_socket_count ?? 0);
  const subscribedSymbols = Array.isArray(feed.subscribed_symbols)
    ? feed.subscribed_symbols.map((s) => String(s).toUpperCase())
    : [];

  const top10Raw = Array.isArray(root.top10) ? root.top10 : [];
  const top10Symbols = new Set(
    top10Raw
      .map((r) => String(rec(r).symbol ?? "").toUpperCase())
      .filter(Boolean),
  );
  const extraSubscribed = subscribedSymbols.filter((s) => !top10Symbols.has(s));
  const legacyExtraCount = extraSubscribed.length;
  const lastUniverseAt = top10Raw.reduce<string | null>((acc, row) => {
    const t = String(rec(row).selected_at ?? "");
    if (!t) return acc;
    if (!acc || t > acc) return t;
    return acc;
  }, null);

  const rows: Top10Row[] = useMemo(() => {
    return top10Raw.map((raw) => {
      const r = rec(raw);
      const symbol = String(r.symbol ?? "").toUpperCase();
      const block =
        r.block_reason ??
        blockers[symbol] ??
        (String(r.cross_state ?? "")
          .toUpperCase()
          .includes("FRESH")
          ? null
          : "NO_FRESH_GOLDEN_CROSS");
      return {
        key: `${r.rank}-${symbol}`,
        rank: Number(r.rank ?? 0),
        symbol,
        name: String(r.name ?? "—"),
        price: fmtNum(r.price, 0),
        changePct: fmtPct(r.change_pct),
        tradingValue: fmtNum(r.trading_value, 0),
        sma5: fmtNum(r.sma5, 0),
        sma20: fmtNum(r.sma20, 0),
        crossLabel: kiwoomCrossStateLabelKo(r.cross_state),
        freshLabel: kiwoomFreshCrossLabelKo(r.cross_state),
        watchLabel: kiwoomSignalStatusLabelKo(r.signal_status),
        whyLabel: block ? kiwoomWhyNoTradeLabelKo(block) : "매수조건 감시 중",
        evaluatedAt: fmtTime(r.selected_at),
      };
    });
  }, [top10Raw, blockers]);

  const columns: ColumnsType<Top10Row> = [
    { title: "순위", dataIndex: "rank", width: 56 },
    { title: "종목코드", dataIndex: "symbol", width: 88 },
    { title: "종목명", dataIndex: "name", ellipsis: true },
    { title: "현재가", dataIndex: "price", width: 100 },
    { title: "등락률", dataIndex: "changePct", width: 88 },
    { title: "거래대금", dataIndex: "tradingValue", width: 120 },
    { title: "SMA5", dataIndex: "sma5", width: 100 },
    { title: "SMA20", dataIndex: "sma20", width: 100 },
    { title: "골든크로스", dataIndex: "crossLabel", width: 150 },
    {
      title: "Fresh Cross",
      dataIndex: "freshLabel",
      width: 90,
      render: (v: string) => (
        <Tag color={v === "감지" ? "green" : "default"}>{v}</Tag>
      ),
    },
    { title: "감시/주문", dataIndex: "watchLabel", width: 120 },
    { title: "왜 매수 안 함", dataIndex: "whyLabel", ellipsis: true },
    { title: "최근 평가", dataIndex: "evaluatedAt", width: 150 },
  ];

  if (statusQ.isLoading) {
    return (
      <Card size="small" title="TOP10 REAL 자동매매" loading>
        <Typography.Text type="secondary">불러오는 중…</Typography.Text>
      </Card>
    );
  }

  if (statusQ.isError) {
    return (
      <Alert
        type="error"
        showIcon
        title="TOP10 REAL 상태 조회 실패"
        description={toApiError(statusQ.error).message}
      />
    );
  }

  if (!root.ok && top10Raw.length === 0) {
    return (
      <Card size="small" title="TOP10 REAL 자동매매">
        <Empty description="TOP10 감시 데이터가 없습니다." />
      </Card>
    );
  }

  return (
    <Card
      size="small"
      title={
        <Space wrap>
          <span>{kiwoomModeTitleKo(mode, realEnabled)}</span>
          <Tag color={realEnabled ? "red" : "blue"}>
            {realEnabled ? "REAL" : "SHADOW"}
          </Tag>
          {shadowObs ? <Tag color="geekblue">Shadow 관측 활성</Tag> : null}
        </Space>
      }
      extra={
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          마지막 Universe 갱신: {fmtTime(lastUniverseAt)}
        </Typography.Text>
      }
    >
      <Space orientation="vertical" size={12} style={{ width: "100%" }}>
        <Alert
          type={realEnabled ? "warning" : "info"}
          showIcon
          title={
            realEnabled
              ? "TOP10 REAL 자동매매 운영 중 (조회 전용)"
              : "TOP10 SHADOW 관측 모드 (REAL 미승격)"
          }
          description="Golden Cross·Risk·주문 정책은 변경하지 않습니다. LIVE/ARM 변경은 계좌 현황에서만 가능합니다."
        />

        <Row gutter={[12, 12]}>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="감시 종목(TOP10)"
              value={monitored}
              suffix={`/ ${monitorTarget}`}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic title="실제 구독" value={subscribed} />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="Physical WebSocket"
              value={socketCount || (feed.connected ? 1 : 0)}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="Fresh Cross"
              value={Number(counts.fresh_cross_monitored ?? 0)}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="Shadow 신호"
              value={Number(counts.shadow_signals_total ?? 0)}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="REAL 신호"
              value={Number(counts.real_signals_total ?? 0)}
            />
          </Col>
        </Row>

        <Typography.Paragraph style={{ marginBottom: 0 }}>
          TOP10 자동선정 종목: <strong>{monitored}</strong>
          {" · "}
          기존 전략 추가구독: <strong>{legacyExtraCount}</strong>
          {legacyExtraCount > 0
            ? ` (${extraSubscribed.join(", ") || "034310"})`
            : ""}
          {" · "}
          총 구독종목: <strong>{subscribed}</strong>
          （중복 카운트 없음）
        </Typography.Paragraph>

        {why.user_friendly ? (
          <Typography.Text type="secondary">
            요약: {String(why.user_friendly)}
          </Typography.Text>
        ) : null}

        {isCompact ? (
          <Space orientation="vertical" size={8} style={{ width: "100%" }}>
            {rows.length === 0 ? (
              <Empty description="감시 종목 없음" />
            ) : (
              rows.map((row) => (
                <Card key={row.key} size="small" type="inner">
                  <Space
                    orientation="vertical"
                    size={4}
                    style={{ width: "100%" }}
                  >
                    <Typography.Text strong>
                      #{row.rank} {row.name}{" "}
                      <Typography.Text type="secondary">
                        ({row.symbol})
                      </Typography.Text>
                    </Typography.Text>
                    <Typography.Text>
                      현재가 {row.price} · 등락률 {row.changePct}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      SMA5 {row.sma5} · SMA20 {row.sma20}
                    </Typography.Text>
                    <Space wrap size={4}>
                      <Tag color={row.freshLabel === "감지" ? "green" : "default"}>
                        Fresh Cross: {row.freshLabel}
                      </Tag>
                      <Tag>매수: {row.watchLabel}</Tag>
                    </Space>
                    <Typography.Text type="secondary">
                      왜 매수 안 함: {row.whyLabel}
                    </Typography.Text>
                  </Space>
                </Card>
              ))
            )}
          </Space>
        ) : (
          <Table<Top10Row>
            size="small"
            pagination={false}
            rowKey="key"
            columns={columns}
            dataSource={rows}
            scroll={{ x: 1100 }}
            locale={{ emptyText: <Empty description="감시 종목 없음" /> }}
          />
        )}
      </Space>
    </Card>
  );
}
