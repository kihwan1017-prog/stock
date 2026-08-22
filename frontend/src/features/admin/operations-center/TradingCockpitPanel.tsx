"use client";

/**
 * 단일 운영자 Cockpit — KPI + Broker 카드 + AUTO 차트.
 * Mutation / LIVE·ARM 변경 없음. 기존 READ API만 사용.
 */

import { useQueries, useQuery } from "@tanstack/react-query";
import {
  Card,
  Col,
  Row,
  Space,
  Statistic,
  Tag,
  Timeline,
  Typography,
} from "antd";
import Link from "next/link";
import { useMemo, type ReactNode } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import {
  entryBlockReasonShortKo,
} from "@/features/admin/autotrading/entryBlockReasonKo";
import {
  slotStatusLabelKo,
} from "@/features/admin/autotrading/slotStatusLabels";
import {
  toneFromRuntime,
  toneToAntdColor,
} from "@/features/admin/autotrading/statusTone";
import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";
import { resolveOrderTradingKind } from "@/features/admin/autotrading/orderOwnership";

import { AutoPnlCharts } from "./AutoPnlCharts";
import { BrokerOpsCard, type BrokerCardModel } from "./BrokerOpsCard";

const DEFAULT_UPBIT_UBA = Number(
  process.env.NEXT_PUBLIC_DEFAULT_UPBIT_UBA_ID ?? "1380",
);
const DEFAULT_KIWOOM_UBA = Number(
  process.env.NEXT_PUBLIC_DEFAULT_KIWOOM_UBA_ID ?? "1381",
);

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

function pickBool(v: unknown): boolean | null {
  if (v === true || v === false) return v;
  if (v === "ON" || v === "true" || v === 1) return true;
  if (v === "OFF" || v === "false" || v === 0) return false;
  return null;
}

function krxPhaseLabelKo(phase: unknown, sessionType: unknown): string {
  const p = String(phase ?? "").toUpperCase();
  const s = String(sessionType ?? "").toUpperCase();
  if (p.includes("REGULAR") || p === "OPEN" || p === "CONTINUOUS") {
    return "장중";
  }
  if (p.includes("PRE") || p === "PREOPEN") return "장전";
  if (p.includes("CLOSE") || p.includes("AFTER") || p === "CLOSED") {
    return "장마감";
  }
  if (s === "HOLIDAY" || p === "HOLIDAY") return "휴장";
  return p || s || "확인 불가";
}

type Props = {
  refreshMs?: number;
  /** Operations Center 요약에서 Kill/Health 재사용 */
  systemHealth?: unknown;
  killActive?: boolean | null;
  criticalConflict?: number | null;
};

export function TradingCockpitPanel({
  refreshMs = 5000,
  systemHealth,
  killActive,
  criticalConflict,
}: Props) {
  const accountsQ = useQuery({
    queryKey: ["admin", "broker-accounts", "cockpit"],
    queryFn: () =>
      adminApi.listAdminBrokerAccounts({ include_inactive: false, limit: 100 }),
    refetchInterval: refreshMs,
  });

  const ubaIds = useMemo(() => {
    const root = rec(accountsQ.data);
    const items = Array.isArray(root.items)
      ? root.items
      : Array.isArray(accountsQ.data)
        ? (accountsQ.data as unknown[])
        : [];
    let upbit = DEFAULT_UPBIT_UBA;
    let kiwoom = DEFAULT_KIWOOM_UBA;
    for (const row of items) {
      const r = rec(row);
      const id = Number(r.user_broker_account_id ?? r.id ?? 0);
      const broker = String(r.broker_code ?? "").toUpperCase();
      if (!id) continue;
      if (broker === "UPBIT" && (id === DEFAULT_UPBIT_UBA || upbit === DEFAULT_UPBIT_UBA)) {
        upbit = id;
      }
      if (
        broker === "KIWOOM" &&
        (id === DEFAULT_KIWOOM_UBA || kiwoom === DEFAULT_KIWOOM_UBA)
      ) {
        kiwoom = id;
      }
    }
    return { upbit, kiwoom };
  }, [accountsQ.data]);

  const opsQueries = useQueries({
    queries: [
      {
        queryKey: ["admin", "uba-ops-status", ubaIds.upbit, "cockpit"],
        queryFn: () => adminApi.getAdminUbaOpsStatus(ubaIds.upbit),
        refetchInterval: refreshMs,
        enabled: ubaIds.upbit > 0,
      },
      {
        queryKey: ["admin", "uba-ops-status", ubaIds.kiwoom, "cockpit"],
        queryFn: () => adminApi.getAdminUbaOpsStatus(ubaIds.kiwoom),
        refetchInterval: refreshMs,
        enabled: ubaIds.kiwoom > 0,
      },
    ],
  });

  const readinessQueries = useQueries({
    queries: [
      {
        queryKey: ["admin", "autotrading-readiness", ubaIds.upbit],
        queryFn: () => adminApi.getAdminUbaAutotradingReadiness(ubaIds.upbit),
        refetchInterval: refreshMs * 2,
        enabled: ubaIds.upbit > 0,
      },
      {
        queryKey: ["admin", "autotrading-readiness", ubaIds.kiwoom],
        queryFn: () => adminApi.getAdminUbaAutotradingReadiness(ubaIds.kiwoom),
        refetchInterval: refreshMs * 2,
        enabled: ubaIds.kiwoom > 0,
      },
    ],
  });

  const portfolioQ = useQuery({
    queryKey: ["admin", "uba-portfolio", ubaIds.upbit, "cockpit"],
    queryFn: () => adminApi.getAdminUbaPortfolioStatus(ubaIds.upbit),
    refetchInterval: refreshMs,
    enabled: ubaIds.upbit > 0,
  });

  const ownershipQueries = useQueries({
    queries: [
      {
        queryKey: ["admin", "symbol-ownership", ubaIds.upbit, "UPBIT"],
        queryFn: () =>
          adminApi.listAdminSymbolOwnership(ubaIds.upbit, "UPBIT"),
        refetchInterval: refreshMs * 2,
        enabled: ubaIds.upbit > 0,
      },
      {
        queryKey: ["admin", "symbol-ownership", ubaIds.kiwoom, "KIWOOM"],
        queryFn: () =>
          adminApi.listAdminSymbolOwnership(ubaIds.kiwoom, "KIWOOM"),
        refetchInterval: refreshMs * 2,
        enabled: ubaIds.kiwoom > 0,
      },
    ],
  });

  const positionsQ = useQuery({
    queryKey: ["admin", "ops-positions", "cockpit"],
    queryFn: () => adminApi.getOpsDashboardPositions(),
    refetchInterval: refreshMs * 2,
  });

  const ordersQ = useQuery({
    queryKey: ["admin", "orders", "cockpit-today"],
    queryFn: () => adminApi.listOrders({ limit: 200 }),
    refetchInterval: refreshMs * 2,
  });

  const krxQ = useQuery({
    queryKey: ["admin", "market-calendar", "KRX", "cockpit"],
    queryFn: () => adminApi.getUserMarketCalendarStatus("KRX"),
    refetchInterval: 60_000,
  });

  const upbitOps = rec(opsQueries[0]?.data);
  const kiwoomOps = rec(opsQueries[1]?.data);
  const upbitReady = rec(readinessQueries[0]?.data);
  const kiwoomReady = rec(readinessQueries[1]?.data);
  const portfolio = rec(portfolioQ.data);
  const slots = Array.isArray(portfolio.slots) ? portfolio.slots : [];
  const summary = rec(portfolio.summary);

  const autoSymbolCount = useMemo(() => {
    let n = 0;
    for (const q of ownershipQueries) {
      const items = extractRows(rec(q.data).items ?? q.data);
      for (const row of items) {
        if (String(rec(row).owner).toUpperCase() === "AUTO") n += 1;
      }
    }
    return n;
  }, [ownershipQueries]);

  const orderStats = useMemo(() => {
    const rows = extractRows(ordersQ.data);
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    let autoOrders = 0;
    let autoFills = 0;
    for (const raw of rows) {
      const row = rec(raw);
      const created = Date.parse(
        String(row.created_at ?? row.requested_at ?? ""),
      );
      if (Number.isFinite(created) && created < start.getTime()) continue;
      const hint = resolveOrderTradingKind(row);
      if (hint.kind !== "AUTO") continue;
      autoOrders += 1;
      const st = String(row.status_code ?? "").toUpperCase();
      if (st.includes("FILL") || Number(row.filled_quantity ?? 0) > 0) {
        autoFills += 1;
      }
    }
    return { autoOrders, autoFills };
  }, [ordersQ.data]);

  const manualUnrealized = useMemo(() => {
    const ownUpbit = new Map<string, string>();
    const ownKiwoom = new Map<string, string>();
    const upItems = extractRows(
      rec(ownershipQueries[0]?.data).items ?? ownershipQueries[0]?.data,
    );
    const kwItems = extractRows(
      rec(ownershipQueries[1]?.data).items ?? ownershipQueries[1]?.data,
    );
    for (const r of upItems) {
      const o = rec(r);
      ownUpbit.set(String(o.symbol).toUpperCase(), String(o.owner).toUpperCase());
    }
    for (const r of kwItems) {
      const o = rec(r);
      ownKiwoom.set(
        String(o.symbol).toUpperCase(),
        String(o.owner).toUpperCase(),
      );
    }
    let manual = 0;
    let auto = 0;
    for (const raw of extractRows(rec(positionsQ.data).positions ?? positionsQ.data)) {
      const p = rec(raw);
      const broker = String(p.broker_code ?? "").toUpperCase();
      const sym = String(p.symbol ?? "").toUpperCase();
      const owner =
        broker === "UPBIT"
          ? ownUpbit.get(sym)
          : broker === "KIWOOM"
            ? ownKiwoom.get(sym)
            : undefined;
      const pnl = Number(p.unrealized_pnl ?? 0);
      if (!Number.isFinite(pnl)) continue;
      if (owner === "AUTO") auto += pnl;
      else if (owner === "MANUAL" || owner === "AUTO_EXCLUDED") manual += pnl;
    }
    return { manual, auto };
  }, [ownershipQueries, positionsQ.data]);

  const upbitCard: BrokerCardModel = {
    broker: "UPBIT",
    title: "업비트 (UPBIT)",
    href: adminRoutes.autotradingUpbit,
    liveOn: pickBool(upbitOps.live_on ?? upbitOps.live_order_enabled),
    armOn: pickBool(upbitOps.arm_on ?? upbitOps.live_armed),
    runtime: String(
      upbitOps.strategy_runtime ??
        rec(upbitOps.control).strategy_runtime ??
        "—",
    ),
    worker: String(upbitOps.outbox_worker ?? rec(upbitOps.control).outbox_worker ?? "—"),
    runner: String(
      upbitOps.execution_runner ??
        upbitOps.strategy_runtime ??
        rec(upbitOps.control).strategy_runtime ??
        "—",
    ),
    exitMonitor: String(
      upbitOps.exit_monitor ?? rec(upbitOps.control).exit_monitor ?? "—",
    ),
    feed: String(rec(upbitOps.market_feed).status ?? "—"),
    evaluator: String(summary.entry_state ?? "—"),
    unattended: String(
      rec(upbitOps.unattended).lease_status ??
        rec(upbitOps.unattended).status ??
        (rec(upbitOps.unattended).unattended_enabled ? "ACTIVE" : "OFF"),
    ),
    autoPositions: Number(summary.positions_open ?? 0),
    todayOrders: orderStats.autoOrders,
    autoPnlLabel: "시계열 API 없음",
    manualOpenOrders: (() => {
      const oo = rec(upbitOps.open_orders);
      const n = Number(oo.manual_open_orders);
      return Number.isFinite(n) ? n : null;
    })(),
    autoOpenOrders: (() => {
      const oo = rec(upbitOps.open_orders);
      const n = Number(oo.auto_open_orders);
      return Number.isFinite(n) ? n : null;
    })(),
    autoOpenOrderLimit: (() => {
      const oo = rec(upbitOps.open_orders);
      const n = Number(oo.auto_open_order_limit);
      return Number.isFinite(n) ? n : null;
    })(),
    blocker: String(
      upbitOps.primary_blocker ??
        (Array.isArray(upbitOps.blockers) ? upbitOps.blockers[0] : null) ??
        "",
    ) || null,
    readiness: String(
      upbitReady.readiness ??
        upbitReady.status ??
        upbitOps.auto_trading_state ??
        "—",
    ),
  };

  const krx = rec(krxQ.data);
  const kiwoomCard: BrokerCardModel = {
    broker: "KIWOOM",
    title: "키움 (KIWOOM)",
    href: adminRoutes.autotradingKiwoom,
    marketLabel: krxPhaseLabelKo(krx.phase, krx.session_type),
    marketTone: krx.is_trading_day === false ? "gray" : toneFromRuntime(
      String(krx.phase ?? "").includes("REGULAR") ? "RUNNING" : "WAITING_SIGNAL",
    ),
    liveOn: pickBool(kiwoomOps.live_on ?? kiwoomOps.live_order_enabled),
    armOn: pickBool(kiwoomOps.arm_on ?? kiwoomOps.live_armed),
    runtime: String(
      kiwoomOps.strategy_runtime ??
        rec(kiwoomOps.control).strategy_runtime ??
        "—",
    ),
    strategy: String(kiwoomOps.strategy_id ?? "—"),
    autoPositions: null,
    todayOrders: null,
    autoPnlLabel: "시계열 API 없음",
    manualOpenOrders: (() => {
      const oo = rec(kiwoomOps.open_orders);
      const n = Number(oo.manual_open_orders);
      return Number.isFinite(n) ? n : null;
    })(),
    autoOpenOrders: (() => {
      const oo = rec(kiwoomOps.open_orders);
      const n = Number(oo.auto_open_orders);
      return Number.isFinite(n) ? n : null;
    })(),
    autoOpenOrderLimit: (() => {
      const oo = rec(kiwoomOps.open_orders);
      const n = Number(oo.auto_open_order_limit);
      return Number.isFinite(n) ? n : null;
    })(),
    blocker: String(
      kiwoomOps.primary_blocker ??
        (Array.isArray(kiwoomOps.blockers) ? kiwoomOps.blockers[0] : null) ??
        "",
    ) || null,
    readiness: String(
      kiwoomReady.readiness ??
        kiwoomReady.status ??
        kiwoomOps.auto_trading_state ??
        "—",
    ),
  };

  const activityItems = useMemo(() => {
    const items: { color?: string; children: ReactNode }[] = [];
    for (const raw of slots) {
      const s = rec(raw);
      const sym = String(s.symbol ?? "—");
      const status = String(s.status ?? "");
      const block = s.last_entry_block_reason ?? s.entry_block_reason;
      items.push({
        color: status === "OPEN" ? "green" : status === "WAITING_SIGNAL" ? "blue" : "gray",
        children: (
          <span>
            <strong>{sym}</strong> · {slotStatusLabelKo(status)}
            {block
              ? ` · 차단: ${entryBlockReasonShortKo(String(block))}`
              : ""}
          </span>
        ),
      });
    }
    return items.slice(0, 8);
  }, [slots]);

  const healthTone = toneFromRuntime(String(systemHealth ?? ""));

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card size="small" title="운영 Cockpit KPI">
        <Row gutter={[12, 12]}>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic
              title="키움 자동매매"
              value={String(kiwoomCard.readiness ?? "—")}
              styles={{ content: { fontSize: 14 } }}
            />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic
              title="업비트 자동매매"
              value={String(upbitCard.readiness ?? "—")}
              styles={{ content: { fontSize: 14 } }}
            />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic title="AUTO 보유 종목" value={autoSymbolCount} />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic title="오늘 AUTO 주문" value={orderStats.autoOrders} />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic title="오늘 AUTO 체결" value={orderStats.autoFills} />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic
              title="오늘 AUTO 실현손익"
              value="—"
              suffix={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  API gap
                </Typography.Text>
              }
            />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic
              title="현재 AUTO 평가손익"
              value={manualUnrealized.auto}
              precision={0}
            />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic
              title="MANUAL 평가손익"
              value={manualUnrealized.manual}
              precision={0}
            />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic
              title="Kill Switch"
              value={killActive ? "활성" : "정상"}
              styles={{
                content: {
                  color: killActive ? "#cf1322" : undefined,
                },
              }}
            />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic
              title="Critical Conflict"
              value={criticalConflict ?? "—"}
            />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
            <div>
              <Typography.Text type="secondary">System Health</Typography.Text>
              <div>
                <Tag color={toneToAntdColor(healthTone)}>
                  {String(systemHealth ?? "—")}
                </Tag>
              </div>
            </div>
          </Col>
        </Row>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <BrokerOpsCard model={kiwoomCard} />
        </Col>
        <Col xs={24} lg={12}>
          <BrokerOpsCard model={upbitCard} />
        </Col>
      </Row>

      <AutoPnlCharts series={null} />

      <Card
        size="small"
        title="최근 자동매매 Activity"
        extra={
          <Link href={adminRoutes.autotradingUpbit}>업비트 워크스페이스</Link>
        }
      >
        {activityItems.length ? (
          <Timeline items={activityItems} />
        ) : (
          <Typography.Text type="secondary">
            표시할 AUTO 슬롯 이벤트가 없습니다. (시장분석/Shadow와 분리된 슬롯
            기반 요약)
          </Typography.Text>
        )}
      </Card>
    </Space>
  );
}
