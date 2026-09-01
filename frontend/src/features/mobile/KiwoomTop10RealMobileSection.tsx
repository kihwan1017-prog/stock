"use client";

/**
 * 모바일/PWA — Kiwoom TOP10 REAL 카드 (READ-ONLY, admin status API 재사용).
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import {
  kiwoomFreshCrossLabelKo,
  kiwoomModeTitleKo,
  kiwoomSignalStatusLabelKo,
  kiwoomWhyNoTradeLabelKo,
} from "@/features/admin/autotrading/kiwoomTop10Labels";
import { asRecord } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

import styles from "@/features/mobile/mobile.module.css";

const DEFAULT_KIWOOM_UBA = Number(
  process.env.NEXT_PUBLIC_DEFAULT_KIWOOM_UBA_ID ?? "1381",
);

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

function fmtNum(v: unknown): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
}

function fmtPct(v: unknown): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.row}>
      <span className={styles.rowLabel}>{label}</span>
      <span className={styles.rowValue}>{value}</span>
    </div>
  );
}

export function KiwoomTop10RealMobileSection({
  ubaId = DEFAULT_KIWOOM_UBA,
  liveOn,
  armOn,
  feedLabel,
  readyLabel,
  autoLabel,
}: {
  ubaId?: number;
  liveOn?: boolean;
  armOn?: boolean;
  feedLabel?: string;
  readyLabel?: string;
  autoLabel?: string;
}) {
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);

  const statusQ = useQuery({
    queryKey: queryKeys.admin.kiwoomMultiSymbolStatus(ubaId),
    queryFn: () => adminApi.getAdminKiwoomMultiSymbolStatus(ubaId),
    enabled: ubaId > 0,
    refetchInterval: 20_000,
  });

  const root = rec(statusQ.data);
  const universe = rec(root.universe);
  const feed = rec(root.feed);
  const why = rec(root.why_no_trade_summary);
  const blockers = rec(why.per_symbol_blockers);

  const mode = String(root.MULTI_SYMBOL_MODE ?? root.mode ?? "SHADOW");
  const realEnabled = Boolean(
    root.MULTI_SYMBOL_REAL_ENABLED ?? root.REAL_MULTI_SYMBOL_ENABLED,
  );
  const shadowObs = Boolean(root.MULTI_SYMBOL_SHADOW_OBSERVABILITY_ENABLED);
  const monitored = Number(universe.monitored_count ?? 0);
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

  const cards = useMemo(() => {
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
        symbol,
        name: String(r.name ?? "—"),
        rank: Number(r.rank ?? 0),
        price: fmtNum(r.price),
        changePct: fmtPct(r.change_pct),
        sma5: fmtNum(r.sma5),
        sma20: fmtNum(r.sma20),
        fresh: kiwoomFreshCrossLabelKo(r.cross_state),
        buy: kiwoomSignalStatusLabelKo(r.signal_status),
        why: block ? kiwoomWhyNoTradeLabelKo(block) : "매수조건 감시 중",
      };
    });
  }, [top10Raw, blockers]);

  return (
    <section className={`${styles.card} ${styles.spanFull}`}>
      <h2 className={styles.cardTitle}>
        {kiwoomModeTitleKo(mode, realEnabled)}
      </h2>

      <div className={styles.chipRow} aria-label="핵심 상태">
        <span className={styles.chip}>AUTO {autoLabel ?? "—"}</span>
        <span className={styles.chip}>
          LIVE {liveOn == null ? "—" : liveOn ? "ON" : "OFF"}
        </span>
        <span className={styles.chip}>
          ARM {armOn == null ? "—" : armOn ? "ON" : "OFF"}
        </span>
        <span className={styles.chip}>FEED {feedLabel ?? "—"}</span>
        <span className={styles.chip}>READY {readyLabel ?? "—"}</span>
        <span className={`${styles.chip} ${realEnabled ? styles.chipHot : ""}`}>
          {realEnabled ? "TOP10 REAL" : "TOP10 SHADOW"}
        </span>
      </div>

      {statusQ.isError ? (
        <div className={`${styles.banner} ${styles.bannerError}`}>
          {toApiError(statusQ.error).message}
        </div>
      ) : null}

      {statusQ.isLoading ? (
        <p className={styles.empty}>TOP10 상태 불러오는 중…</p>
      ) : (
        <>
          <Row label="운영 모드" value={realEnabled ? "REAL" : "SHADOW"} />
          <Row
            label="감시 / 구독"
            value={`${monitored} / ${subscribed}`}
          />
          <Row
            label="Physical WS"
            value={String(socketCount || (feed.connected ? 1 : 0))}
          />
          <Row
            label="Shadow 관측"
            value={shadowObs ? "활성" : "비활성"}
          />
          <Row
            label="TOP10 / 추가구독"
            value={`${monitored} + ${extraSubscribed.length}${
              extraSubscribed.length
                ? ` (${extraSubscribed.join(", ")})`
                : ""
            }`}
          />

          {cards.length === 0 ? (
            <p className={styles.empty}>감시 종목이 없습니다.</p>
          ) : (
            cards.map((c) => {
              const open = expandedSymbol === c.symbol;
              return (
                <div key={c.symbol} className={styles.listItem}>
                  <button
                    type="button"
                    className={styles.expandBtn}
                    onClick={() =>
                      setExpandedSymbol(open ? null : c.symbol)
                    }
                  >
                    <span className={styles.listMain}>
                      #{c.rank} {c.name} / {c.symbol}
                    </span>
                    <span className={styles.listSub}>
                      {c.price} · {c.changePct} · Fresh {c.fresh}
                    </span>
                  </button>
                  {open ? (
                    <div className={styles.expandBody}>
                      <Row label="SMA5" value={c.sma5} />
                      <Row label="SMA20" value={c.sma20} />
                      <Row label="Fresh Cross" value={c.fresh} />
                      <Row label="매수" value={c.buy} />
                      <Row label="왜 매수 안 함" value={c.why} />
                    </div>
                  ) : null}
                </div>
              );
            })
          )}
        </>
      )}
    </section>
  );
}
