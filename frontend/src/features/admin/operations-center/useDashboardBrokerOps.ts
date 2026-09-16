"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { extractRows } from "@/features/admin/utils/dataHelpers";

import type { BrokerCardModel } from "./BrokerOpsCard";
import {
  pickBool,
  rec,
} from "./dashboardBrokerOpsUtils";

const DEFAULT_UPBIT_UBA = Number(
  process.env.NEXT_PUBLIC_DEFAULT_UPBIT_UBA_ID ?? "1380",
);
const DEFAULT_KIWOOM_UBA = Number(
  process.env.NEXT_PUBLIC_DEFAULT_KIWOOM_UBA_ID ?? "1381",
);

type Options = {
  enabled: boolean;
  /** operations 탭에서만 portfolio/positions 등 확장 조회 */
  detailed?: boolean;
  refreshMs?: number;
};

export function useDashboardBrokerOps({
  enabled,
  detailed = false,
  refreshMs = 15_000,
}: Options) {
  const interval = enabled && refreshMs > 0 ? refreshMs : false;

  const accountsQ = useQueries({
    queries: [
      {
        queryKey: ["admin", "broker-accounts", "dashboard", "UPBIT"],
        queryFn: () =>
          adminApi.listAdminBrokerAccounts({
            broker_code: "UPBIT",
            include_inactive: false,
            include_test_accounts: false,
            enrich: false,
            limit: 20,
          }),
        enabled,
        staleTime: 20_000,
      },
      {
        queryKey: ["admin", "broker-accounts", "dashboard", "KIWOOM"],
        queryFn: () =>
          adminApi.listAdminBrokerAccounts({
            broker_code: "KIWOOM",
            include_inactive: false,
            include_test_accounts: false,
            enrich: false,
            limit: 20,
          }),
        enabled,
        staleTime: 20_000,
      },
    ],
  });

  const ubaIds = useMemo(() => {
    const items: unknown[] = [];
    for (const q of accountsQ) {
      const root = rec(q.data);
      if (Array.isArray(root.items)) items.push(...root.items);
    }
    let upbit = DEFAULT_UPBIT_UBA;
    let kiwoom = DEFAULT_KIWOOM_UBA;
    for (const row of items) {
      const r = rec(row);
      const id = Number(r.user_broker_account_id ?? r.id ?? 0);
      const broker = String(r.broker_code ?? "").toUpperCase();
      if (!id) continue;
      if (broker === "UPBIT") upbit = id;
      if (broker === "KIWOOM") kiwoom = id;
    }
    return { upbit, kiwoom };
  }, [accountsQ]);

  const opsQueries = useQueries({
    queries: [
      {
        queryKey: ["admin", "uba-ops-status", ubaIds.upbit],
        queryFn: () => adminApi.getAdminUbaOpsStatus(ubaIds.upbit),
        refetchInterval: interval,
        enabled: enabled && ubaIds.upbit > 0,
        staleTime: 10_000,
      },
      {
        queryKey: ["admin", "uba-ops-status", ubaIds.kiwoom],
        queryFn: () => adminApi.getAdminUbaOpsStatus(ubaIds.kiwoom),
        refetchInterval: interval,
        enabled: enabled && ubaIds.kiwoom > 0,
        staleTime: 10_000,
      },
    ],
  });

  const readinessQueries = useQueries({
    queries: [
      {
        queryKey: ["admin", "autotrading-readiness", ubaIds.upbit],
        queryFn: () => adminApi.getAdminUbaAutotradingReadiness(ubaIds.upbit),
        refetchInterval: enabled ? Math.max(refreshMs * 2, 30_000) : false,
        enabled: enabled && ubaIds.upbit > 0,
      },
      {
        queryKey: ["admin", "autotrading-readiness", ubaIds.kiwoom],
        queryFn: () => adminApi.getAdminUbaAutotradingReadiness(ubaIds.kiwoom),
        refetchInterval: enabled ? Math.max(refreshMs * 2, 30_000) : false,
        enabled: enabled && ubaIds.kiwoom > 0,
      },
    ],
  });

  const portfolioQ = useQuery({
    queryKey: ["admin", "uba-portfolio", ubaIds.upbit],
    queryFn: () => adminApi.getAdminUbaPortfolioStatus(ubaIds.upbit),
    refetchInterval: interval,
    enabled: enabled && detailed && ubaIds.upbit > 0,
  });

  const positionsQ = useQuery({
    queryKey: ["admin", "ops-positions", "dashboard"],
    queryFn: () => adminApi.getOpsDashboardPositions(),
    refetchInterval: enabled && detailed ? Math.max(refreshMs * 2, 30_000) : false,
    enabled: enabled && detailed,
  });

  const ownershipQueries = useQueries({
    queries: [
      {
        queryKey: ["admin", "symbol-ownership", ubaIds.upbit, "UPBIT"],
        queryFn: () =>
          adminApi.listAdminSymbolOwnership(ubaIds.upbit, "UPBIT"),
        enabled: enabled && detailed && ubaIds.upbit > 0,
      },
      {
        queryKey: ["admin", "symbol-ownership", ubaIds.kiwoom, "KIWOOM"],
        queryFn: () =>
          adminApi.listAdminSymbolOwnership(ubaIds.kiwoom, "KIWOOM"),
        enabled: enabled && detailed && ubaIds.kiwoom > 0,
      },
    ],
  });

  const upbitOps = rec(opsQueries[0]?.data);
  const kiwoomOps = rec(opsQueries[1]?.data);
  const upbitReady = rec(readinessQueries[0]?.data);
  const kiwoomReady = rec(readinessQueries[1]?.data);
  const portfolio = rec(portfolioQ.data);
  const slots = Array.isArray(portfolio.slots) ? portfolio.slots : [];
  const portfolioSummary = rec(portfolio.summary);

  const slotCapacity = Number(portfolioSummary.slot_capacity ?? portfolio.max_positions ?? 0);
  const slotsOccupied = Number(
    portfolioSummary.slots_occupied ?? slots.filter((s) => {
      const st = String(rec(s).status ?? "").toUpperCase();
      return st && st !== "EMPTY";
    }).length,
  );

  const blockers = useMemo(() => {
    const list: string[] = [];
    for (const [label, ops] of [
      ["UPBIT", upbitOps],
      ["KIWOOM", kiwoomOps],
    ] as const) {
      const b = String(
        ops.primary_blocker ??
          (Array.isArray(ops.blockers) ? ops.blockers[0] : null) ??
          "",
      ).trim();
      if (b) list.push(`${label}: ${b}`);
    }
    return list;
  }, [kiwoomOps, upbitOps]);

  const upbitUnattended = rec(upbitOps.unattended);
  const upbitUnattendedStatus = String(
    upbitUnattended.lease_status ??
      upbitUnattended.status ??
      (upbitUnattended.unattended_enabled ? "ACTIVE" : "OFF"),
  );
  const upbitAutoRenew = Boolean(upbitUnattended.auto_renew_enabled);
  const upbitUnattRem = Number(upbitUnattended.remaining_seconds ?? 0);
  const upbitLastHz = rec(upbitUnattended.last_horizon_auto_renew);
  const upbitRenewWarning =
    upbitAutoRenew &&
    upbitUnattendedStatus === "ACTIVE" &&
    (upbitLastHz.status === "BLOCKED" ||
      (upbitUnattRem > 0 && upbitUnattRem <= 3600));

  const upbitCard: BrokerCardModel = useMemo(
    () => ({
      broker: "UPBIT",
      title: "업비트",
      href: adminRoutes.autotradingUpbit,
      liveOn: pickBool(upbitOps.live ?? upbitOps.live_on ?? upbitOps.live_order_enabled),
      armOn: pickBool(upbitOps.arm ?? upbitOps.arm_on ?? upbitOps.live_armed),
      runtime: String(
        upbitOps.strategy_runtime ??
          rec(upbitOps.control).strategy_runtime ??
          "—",
      ),
      worker: String(
        upbitOps.outbox_worker ?? rec(upbitOps.control).outbox_worker ?? "—",
      ),
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
      evaluator: String(portfolioSummary.entry_state ?? "—"),
      unattended: upbitUnattendedStatus,
      unattendedAutoRenew: upbitAutoRenew,
      unattendedRemainingSeconds: upbitUnattRem,
      unattendedRenewWarning: upbitRenewWarning,
      autoPositions: Number(portfolioSummary.positions_open ?? 0),
      todayOrders: null,
      autoPnlLabel: "성과 API",
      blocker:
        String(
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
    }),
    [portfolioSummary, upbitAutoRenew, upbitOps, upbitReady, upbitRenewWarning, upbitUnattRem, upbitUnattendedStatus],
  );

  const kiwoomCard: BrokerCardModel = useMemo(
    () => ({
      broker: "KIWOOM",
      title: "키움",
      href: adminRoutes.autotradingKiwoom,
      liveOn: pickBool(kiwoomOps.live ?? kiwoomOps.live_on ?? kiwoomOps.live_order_enabled),
      armOn: pickBool(kiwoomOps.arm ?? kiwoomOps.arm_on ?? kiwoomOps.live_armed),
      runtime: String(
        kiwoomOps.strategy_runtime ??
          rec(kiwoomOps.control).strategy_runtime ??
          "—",
      ),
      strategy: String(kiwoomOps.strategy_id ?? "—"),
      autoPositions: null,
      todayOrders: null,
      autoPnlLabel: "성과 API",
      blocker:
        String(
          kiwoomOps.primary_blocker ??
            (Array.isArray(kiwoomOps.blockers)
              ? kiwoomOps.blockers[0]
              : null) ??
            "",
        ) || null,
      readiness: String(
        kiwoomReady.readiness ??
          kiwoomReady.status ??
          kiwoomOps.auto_trading_state ??
          "—",
      ),
    }),
    [kiwoomOps, kiwoomReady],
  );

  const autoOpenPositions = useMemo(() => {
    if (!detailed) return [];
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
    const rows: Record<string, unknown>[] = [];
    for (const raw of extractRows(
      rec(positionsQ.data).positions ?? positionsQ.data,
    )) {
      const p = rec(raw);
      const broker = String(p.broker_code ?? "").toUpperCase();
      const sym = String(p.symbol ?? "").toUpperCase();
      const owner =
        broker === "UPBIT"
          ? ownUpbit.get(sym)
          : broker === "KIWOOM"
            ? ownKiwoom.get(sym)
            : undefined;
      if (owner !== "AUTO") continue;
      rows.push({ ...p, broker_code: broker, symbol: sym });
    }
    return rows;
  }, [detailed, ownershipQueries, positionsQ.data]);

  const manualUnrealized = useMemo(() => {
    if (!detailed) return 0;
    let manual = 0;
    const ownUpbit = new Map<string, string>();
    const ownKiwoom = new Map<string, string>();
    for (const r of extractRows(
      rec(ownershipQueries[0]?.data).items ?? ownershipQueries[0]?.data,
    )) {
      const o = rec(r);
      ownUpbit.set(String(o.symbol).toUpperCase(), String(o.owner).toUpperCase());
    }
    for (const r of extractRows(
      rec(ownershipQueries[1]?.data).items ?? ownershipQueries[1]?.data,
    )) {
      const o = rec(r);
      ownKiwoom.set(
        String(o.symbol).toUpperCase(),
        String(o.owner).toUpperCase(),
      );
    }
    for (const raw of extractRows(
      rec(positionsQ.data).positions ?? positionsQ.data,
    )) {
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
      if (owner === "MANUAL" || owner === "AUTO_EXCLUDED") manual += pnl;
    }
    return manual;
  }, [detailed, ownershipQueries, positionsQ.data]);

  const overallStatus = useMemo(() => {
    if (blockers.length >= 2) return "stopped" as const;
    if (blockers.length === 1) return "partial" as const;
    const liveOff =
      upbitCard.liveOn === false && kiwoomCard.liveOn === false;
    if (liveOff) return "partial" as const;
    return "ok" as const;
  }, [blockers.length, kiwoomCard.liveOn, upbitCard.liveOn]);

  return {
    ubaIds,
    upbitCard,
    kiwoomCard,
    upbitOps,
    kiwoomOps,
    upbitReady,
    kiwoomReady,
    slots,
    slotCapacity,
    slotsOccupied,
    blockers,
    overallStatus,
    autoOpenPositions,
    manualUnrealized,
    isLoading: opsQueries.some((q) => q.isLoading),
  };
}
