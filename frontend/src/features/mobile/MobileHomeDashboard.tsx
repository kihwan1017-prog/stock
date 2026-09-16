"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  alertEmoji,
  boolOnOff,
  formatClock,
  formatHoldDuration,
  formatKrwPlain,
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

function formatWinRate(v: unknown): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${n.toFixed(1)}%`;
}

export function MobileHomeDashboard() {
  const q = useMobileOverview(15_000);
  const [online, setOnline] = useState(() =>
    typeof navigator !== "undefined" ? navigator.onLine : true,
  );
  const [bootTimedOut, setBootTimedOut] = useState(false);

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

  // 무한 splash 방지 — 초기 로딩이 길면 사용자용 안내 전환
  useEffect(() => {
    if (q.data || q.isError) {
      setBootTimedOut(false);
      return;
    }
    const timer = window.setTimeout(() => setBootTimedOut(true), 12_000);
    return () => window.clearTimeout(timer);
  }, [q.data, q.isError, q.isFetching]);

  const data = q.data;
  const overall = data?.overall;
  const system = data?.system ?? {};
  const upbit = data?.upbit ?? {};
  const kiwoom = data?.kiwoom ?? {};
  const today = data?.today ?? {};
  const why = data?.why_no_trade;
  const byBroker =
    (today.by_broker as Record<string, Record<string, unknown>> | undefined) ??
    {};
  const positions = data?.positions?.items ?? [];
  const orders = data?.recent_orders ?? [];
  const events = data?.recent_events ?? [];
  const ai = data?.ai ?? {};

  const buyCount = Number(today.buy_count ?? today.auto_buy_count ?? 0);
  const sellCount = Number(today.sell_count ?? today.auto_sell_count ?? 0);
  const filledCount = Number(today.filled_count ?? today.fill_count ?? 0);
  const openCount = Number(today.open_count ?? 0);
  const cancelledCount = Number(today.cancelled_count ?? 0);

  const autoLabel = (() => {
    if (system.kill_switch) return "차단";
    if (why?.trade_running && why?.trade_ready) return "운영 중";
    if (String(upbit.auto_trading_state || "").toUpperCase() === "RUNNING") {
      return why?.trade_ready ? "운영 중" : "대기";
    }
    if (upbit.system_blocked || String(upbit.operational_tier || "") === "SYSTEM_BLOCKED") {
      return "차단";
    }
    return "대기";
  })();

  const showBootGate =
    !data && (q.isLoading || q.isFetching) && !q.isError && !bootTimedOut;
  const showFailureGate = !data && (q.isError || bootTimedOut || !online);

  if (showBootGate) {
    return (
      <div className={styles.page}>
        <header className={styles.header}>
          <div>
            <h1 className={styles.title}>KIKI AI Trading</h1>
            <p className={styles.overall}>서버에 연결하는 중…</p>
          </div>
        </header>
        <div className={`${styles.banner} ${styles.bannerOffline}`}>
          앱을 준비하고 있습니다. 잠시만 기다려 주세요.
        </div>
      </div>
    );
  }

  if (showFailureGate) {
    const apiMsg = q.isError ? toApiError(q.error).message : "";
    let title = "앱을 불러오지 못했습니다";
    let hint =
      "서버 연결을 확인한 뒤 다시 시도해 주세요. Tailscale이 켜져 있는지 확인하세요.";
    if (!online) {
      title = "네트워크 연결 없음";
      hint =
        "휴대폰 인터넷 또는 Tailscale 연결을 확인한 뒤 다시 시도해 주세요.";
    } else if (/401|403|인증|세션|unauthorized/i.test(apiMsg)) {
      title = "인증 세션이 만료되었습니다";
      hint = "다시 로그인한 뒤 홈 화면 아이콘으로 진입해 주세요.";
    } else if (bootTimedOut && !q.isError) {
      title = "서버 준비 중이거나 응답이 없습니다";
      hint =
        "PC에서 stock 프론트엔드가 실행 중인지, Tailscale Serve가 복구됐는지 확인해 주세요.";
    } else if (/failed to fetch|network|ECONN|timeout/i.test(apiMsg)) {
      title = "서버 연결 실패";
      hint =
        "stock.tail3bf7b2.ts.net 접속과 Tailscale 상태를 확인한 뒤 재시도하세요.";
    }
    return (
      <div className={styles.page}>
        <header className={styles.header}>
          <div>
            <h1 className={styles.title}>KIKI AI Trading</h1>
            <p className={styles.overall}>{title}</p>
          </div>
          <button
            type="button"
            className={styles.refreshBtn}
            onClick={() => {
              setBootTimedOut(false);
              void q.refetch();
            }}
          >
            다시 시도
          </button>
        </header>
        <div className={`${styles.banner} ${styles.bannerError}`}>
          {hint}
          {apiMsg ? ` (${apiMsg})` : ""}
        </div>
        <p className={styles.meta}>
          앱이 오래되면 홈 화면 아이콘을 제거하고 다시 추가하거나, 브라우저에서
          사이트를 새로고침해 주세요.
        </p>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>KIKI AI Trading</h1>
          <p className={styles.overall}>
            {overallEmoji(overall?.status)} {overall?.label_hint || "확인 중"}
            {online ? " · 연결됨" : " · 오프라인"}
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
          <button
            type="button"
            className={styles.refreshBtn}
            style={{ marginLeft: 8 }}
            onClick={() => void q.refetch()}
          >
            다시 시도
          </button>
        </div>
      ) : null}

      <div className={styles.grid}>
        <section className={`${styles.card} ${styles.spanFull}`}>
          <h2 className={styles.cardTitle}>자동매매 상태</h2>
          <Row label="운영" value={autoLabel} />
          <Row label="LIVE" value={boolOnOff(upbit.live)} />
          <Row label="ARM" value={boolOnOff(upbit.arm)} />
          <Row
            label="매매 준비"
            value={why?.trade_ready ? "준비 완료" : "준비 안 됨"}
          />
          <Row
            label="엔진"
            value={
              String(upbit.runtime || "") === "RUNNING" &&
              String(upbit.runner || "") === "RUNNING"
                ? "자동매매 엔진 정상"
                : "엔진 확인 필요"
            }
          />
          <Row
            label="시세"
            value={
              String(upbit.feed || "") === "REAL_FRESH"
                ? "실시간 시세 정상"
                : statusKo(upbit.feed)
            }
          />
        </section>

        <section className={`${styles.card} ${styles.spanFull}`}>
          <h2 className={styles.cardTitle}>지금 거래가 없는 이유</h2>
          <p className={styles.meta} style={{ marginBottom: 8 }}>
            {why?.no_trade_reason_text ||
              "상태를 확인하는 중입니다. 잠시 후 다시 확인해 주세요."}
          </p>
          <Row
            label="마지막 주문"
            value={formatClock(why?.last_order_at ?? undefined)}
          />
        </section>

        <section className={`${styles.card} ${styles.spanFull}`}>
          <h2 className={styles.cardTitle}>오늘 거래현황</h2>
          <Row
            label="거래 종목수"
            value={String(Number(today.symbol_count ?? 0))}
          />
          <Row
            label="완료된 매매"
            value={String(Number(today.closed_trade_count ?? 0))}
          />
          <Row label="오늘 매수/매도" value={`${buyCount} / ${sellCount}`} />
          <Row
            label="오늘 체결/미체결"
            value={`${filledCount} / ${openCount}`}
          />
          <Row label="오늘 취소" value={String(cancelledCount)} />
          <Row
            label="평균 보유시간"
            value={formatHoldDuration(today.avg_hold_sec)}
          />
          <Row
            label="오늘 손익"
            value={formatKrwSigned(today.realized_pnl)}
            valueClass={styles[pnlClass(today.realized_pnl)]}
          />
          <Row
            label="손익 / 손실"
            value={`${formatKrwSigned(today.profit_amount)} / ${formatKrwSigned(today.loss_amount)}`}
          />
          <Row label="수수료" value={formatKrwPlain(today.fees)} />
          <Row
            label="총 매수/매도금액"
            value={`${formatKrwPlain(today.buy_amount)} / ${formatKrwPlain(today.sell_amount)}`}
          />
          <Row label="승률" value={formatWinRate(today.win_rate_pct)} />
          <Row
            label="총손익"
            value={formatKrwSigned(today.cumulative_realized_pnl)}
            valueClass={styles[pnlClass(today.cumulative_realized_pnl)]}
          />
          <Row
            label="미실현"
            value={formatKrwSigned(today.unrealized_pnl)}
            valueClass={styles[pnlClass(today.unrealized_pnl)]}
          />
          <Row
            label="UPBIT 오늘"
            value={formatKrwSigned(byBroker.UPBIT?.realized_pnl)}
            valueClass={styles[pnlClass(byBroker.UPBIT?.realized_pnl)]}
          />
          <Row
            label="KIWOOM 오늘"
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
