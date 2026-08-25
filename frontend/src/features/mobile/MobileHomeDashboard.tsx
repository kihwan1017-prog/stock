"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  alertEmoji,
  boolOnOff,
  formatClock,
  formatKrwSigned,
  overallEmoji,
  pnlClass,
  sideKo,
  statusKo,
} from "@/features/mobile/mobileFormat";
import { useMobileOverview } from "@/features/mobile/useMobileOverview";
import { toApiError } from "@/lib/api/apiError";

import styles from "./mobile.module.css";

function Row({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className={styles.row}>
      <span className={styles.rowLabel}>{label}</span>
      <span className={`${styles.rowValue} ${valueClass || ""}`}>{value}</span>
    </div>
  );
}

export function MobileHomeDashboard() {
  const q = useMobileOverview(15_000);
  const [online, setOnline] = useState(() =>
    typeof navigator !== "undefined" ? navigator.onLine : true,
  );

  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

  const data = q.data;
  const overall = data?.overall;
  const system = data?.system ?? {};
  const upbit = data?.upbit ?? {};
  const kiwoom = data?.kiwoom ?? {};
  const today = data?.today ?? {};
  const byBroker =
    (today.by_broker as Record<string, Record<string, unknown>> | undefined) ??
    {};
  const positions = data?.positions?.items ?? [];
  const orders = data?.recent_orders ?? [];
  const events = data?.recent_events ?? [];
  const ai = data?.ai ?? {};

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>자동매매</h1>
          <p className={styles.overall}>
            {overallEmoji(overall?.status)} {overall?.label_hint || "확인 중"}
          </p>
          <p className={styles.meta}>
            마지막 갱신: {formatClock(data?.updated_at)}
          </p>
        </div>
        <button
          type="button"
          className={styles.refreshBtn}
          onClick={() => void q.refetch()}
          disabled={q.isFetching}
        >
          {q.isFetching ? "갱신 중" : "새로고침"}
        </button>
      </header>

      {!online ? (
        <div className={`${styles.banner} ${styles.bannerOffline}`}>
          서버와 연결되지 않았습니다. 마지막 확인:{" "}
          {formatClock(data?.updated_at)}
        </div>
      ) : null}

      {q.isError ? (
        <div className={`${styles.banner} ${styles.bannerError}`}>
          {toApiError(q.error).message}
        </div>
      ) : null}

      <div className={styles.grid}>
        <section className={styles.card}>
          <h2 className={styles.cardTitle}>오늘 손익</h2>
          <Row
            label="실현손익"
            value={formatKrwSigned(today.realized_pnl)}
            valueClass={styles[pnlClass(today.realized_pnl)]}
          />
          <Row
            label="미실현손익"
            value={formatKrwSigned(today.unrealized_pnl)}
            valueClass={styles[pnlClass(today.unrealized_pnl)]}
          />
          <Row
            label="합계"
            value={formatKrwSigned(today.total_pnl)}
            valueClass={styles[pnlClass(today.total_pnl)]}
          />
          <Row
            label="UPBIT"
            value={formatKrwSigned(byBroker.UPBIT?.realized_pnl)}
            valueClass={styles[pnlClass(byBroker.UPBIT?.realized_pnl)]}
          />
          <Row
            label="KIWOOM"
            value={formatKrwSigned(byBroker.KIWOOM?.realized_pnl)}
            valueClass={styles[pnlClass(byBroker.KIWOOM?.realized_pnl)]}
          />
        </section>

        <section className={styles.card}>
          <h2 className={styles.cardTitle}>UPBIT</h2>
          <Row
            label="자동매매"
            value={statusKo(upbit.auto_trading_state)}
          />
          <Row label="LIVE" value={boolOnOff(upbit.live)} />
          <Row label="ARM" value={boolOnOff(upbit.arm)} />
          <Row label="Scanner" value={statusKo(upbit.scanner)} />
          <Row label="Feed" value={statusKo(upbit.feed)} />
          <Row
            label="오늘"
            value={`매수 ${Number(upbit.today_buy_count || 0)} · 매도 ${Number(upbit.today_sell_count || 0)}`}
          />
          <Row
            label="Readiness"
            value={upbit.can_auto_trade ? "자동매매 가능" : "준비 안 됨"}
          />
        </section>

        <section className={styles.card}>
          <h2 className={styles.cardTitle}>KIWOOM</h2>
          <Row
            label="시장"
            value={statusKo(kiwoom.market_status || "UNKNOWN")}
          />
          <Row
            label="자동매매"
            value={statusKo(kiwoom.auto_trading_state)}
          />
          <Row label="LIVE" value={boolOnOff(kiwoom.live)} />
          <Row label="ARM" value={boolOnOff(kiwoom.arm)} />
          <Row label="Runtime" value={statusKo(kiwoom.runtime)} />
          <Row label="Runner" value={statusKo(kiwoom.runner)} />
          <Row label="Feed" value={statusKo(kiwoom.feed)} />
          <Row
            label="오늘"
            value={`매수 ${Number(kiwoom.today_buy_count || 0)} · 매도 ${Number(kiwoom.today_sell_count || 0)}`}
          />
          <Row
            label="Readiness"
            value={kiwoom.can_auto_trade ? "자동매매 가능" : "준비 안 됨"}
          />
        </section>

        <section className={`${styles.card} ${styles.spanFull}`}>
          <h2 className={styles.cardTitle}>시스템</h2>
          <Row label="상태" value={statusKo(system.status)} />
          <Row label="Backend" value={statusKo(system.backend)} />
          <Row label="Database" value={statusKo(system.database)} />
          <Row label="Worker" value={statusKo(system.worker)} />
          <Row label="Scheduler" value={statusKo(system.scheduler)} />
          <Row
            label="Kill Switch"
            value={system.kill_switch ? "활성" : "비활성"}
          />
        </section>

        <section className={styles.card}>
          <h2 className={styles.cardTitle}>보유 포지션</h2>
          {positions.length === 0 ? (
            <p className={styles.empty}>
              현재 자동매매 보유 포지션이 없습니다.
            </p>
          ) : (
            positions.map((p, idx) => (
              <div
                className={styles.listItem}
                key={`${String(p.symbol)}-${idx}`}
              >
                <div className={styles.listMain}>
                  {String(p.market || "")} · {String(p.symbol || "")}
                </div>
                <div className={styles.listSub}>
                  수량 {String(p.quantity ?? "—")} · 진입{" "}
                  {String(p.entry ?? "—")} · 현재 {String(p.current ?? "—")}
                </div>
                <div className={styles.listSub}>
                  PnL{" "}
                  <span className={styles[pnlClass(p.pnl)]}>
                    {formatKrwSigned(p.pnl)}
                  </span>
                </div>
              </div>
            ))
          )}
          <Link href="/mobile/positions" className={styles.moreLink}>
            더보기
          </Link>
        </section>

        <section className={styles.card}>
          <h2 className={styles.cardTitle}>최근 주문/체결</h2>
          {orders.length === 0 ? (
            <p className={styles.empty}>최근 주문이 없습니다.</p>
          ) : (
            orders.map((o, idx) => (
              <div
                className={styles.listItem}
                key={`${String(o.order_id)}-${idx}`}
              >
                <div className={styles.listMain}>
                  {formatClock(String(o.created_at || ""))} ·{" "}
                  {String(o.broker_code || "")} · {String(o.symbol || "")}
                </div>
                <div className={styles.listSub}>
                  {sideKo(o.side)} · {statusKo(o.status)} · 가격{" "}
                  {String(o.price ?? "—")} · 수량 {String(o.quantity ?? "—")}
                </div>
              </div>
            ))
          )}
          <Link href="/mobile/orders" className={styles.moreLink}>
            더보기
          </Link>
        </section>

        <section className={styles.card}>
          <h2 className={styles.cardTitle}>최근 알림</h2>
          {events.length === 0 ? (
            <p className={styles.empty}>표시할 알림이 없습니다.</p>
          ) : (
            events.map((e, idx) => (
              <div
                className={styles.listItem}
                key={`${String(e.code)}-${idx}`}
              >
                <div className={styles.listMain}>
                  {alertEmoji(e.severity)} {String(e.title || e.code || "알림")}
                </div>
                <div className={styles.listSub}>
                  {String(e.message || "").slice(0, 120)}
                </div>
              </div>
            ))
          )}
          <Link href="/mobile/alerts" className={styles.moreLink}>
            더보기
          </Link>
        </section>

        <section className={styles.card}>
          <h2 className={styles.cardTitle}>AI 연구</h2>
          <Row label="Analysis" value={String(ai.analysis_model || "—")} />
          <Row
            label="Trading"
            value={`${String(ai.trading_model || "—")} · ${String(ai.trading_mode || "SHADOW")}`}
          />
          <Row label="Teacher" value={String(ai.teacher_model || "—")} />
          <Row
            label="CLEAN"
            value={`${ai.clean_count ?? "—"} / ${ai.clean_target ?? 500}`}
          />
          <Row label="RAG" value={String(ai.rag_label || "—")} />
        </section>
      </div>
    </div>
  );
}
