"use client";

/**
 * 모바일 자동매매 탭 — UPBIT/KIWOOM 상태 요약 (READ-ONLY).
 * 홈은 오늘 손익·알림 중심, 이 화면은 시장별 가동 상태 중심.
 */

import Link from "next/link";

import { KiwoomTop10RealMobileSection } from "@/features/mobile/KiwoomTop10RealMobileSection";
import {
  boolOnOff,
  formatClock,
  formatLiveArmLabel,
  statusKo,
} from "@/features/mobile/mobileFormat";
import { useMobileOverview } from "@/features/mobile/useMobileOverview";
import { toApiError } from "@/lib/api/apiError";

import styles from "@/features/mobile/mobile.module.css";

function Row({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className={styles.row}>
      <span className={styles.rowLabel}>{label}</span>
      <span className={styles.rowValue}>{value}</span>
    </div>
  );
}

export default function MobileAutotradingPage() {
  const q = useMobileOverview(15_000);
  const data = q.data;
  const upbit = data?.upbit ?? {};
  const kiwoom = data?.kiwoom ?? {};

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>자동매매</h1>
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

      {q.isError ? (
        <div className={`${styles.banner} ${styles.bannerError}`}>
          {toApiError(q.error).message}
        </div>
      ) : null}

      <div className={styles.grid}>
        <section className={styles.card}>
          <h2 className={styles.cardTitle}>업비트</h2>
          <Row
            label="상태"
            value={statusKo(upbit.auto_trading_state)}
          />
          <Row
            label="거래 가능"
            value={formatLiveArmLabel(upbit.live, upbit.arm)}
          />
          <Row label="LIVE" value={boolOnOff(upbit.live)} />
          <Row label="ARM" value={boolOnOff(upbit.arm)} />
          <Row label="시세" value={statusKo(upbit.feed)} />
          <Row
            label="오늘"
            value={`매수 ${Number(upbit.today_buy_count || 0)} · 매도 ${Number(upbit.today_sell_count || 0)}`}
          />
          <Row
            label="준비"
            value={
              upbit.entry_restricted
                ? "청산 체결 대기"
                : upbit.can_auto_trade
                  ? "자동매매 가능"
                  : upbit.system_blocked
                    ? "자동매매 차단"
                    : "준비 안 됨"
            }
          />
          <Link href="/admin/autotrading/upbit" className={styles.moreLink}>
            데스크톱 상세 →
          </Link>
        </section>

        <section className={styles.card}>
          <h2 className={styles.cardTitle}>키움</h2>
          <Row
            label="시장"
            value={statusKo(kiwoom.market_status || "UNKNOWN")}
          />
          <Row
            label="상태"
            value={statusKo(kiwoom.auto_trading_state)}
          />
          <Row
            label="거래 가능"
            value={formatLiveArmLabel(kiwoom.live, kiwoom.arm)}
          />
          <Row label="LIVE" value={boolOnOff(kiwoom.live)} />
          <Row label="ARM" value={boolOnOff(kiwoom.arm)} />
          <Row label="시세" value={statusKo(kiwoom.feed)} />
          <Row
            label="오늘"
            value={`매수 ${Number(kiwoom.today_buy_count || 0)} · 매도 ${Number(kiwoom.today_sell_count || 0)}`}
          />
          <Row
            label="준비"
            value={kiwoom.can_auto_trade ? "자동매매 가능" : "준비 안 됨"}
          />
          <Link href="/admin/autotrading/kiwoom" className={styles.moreLink}>
            데스크톱 상세 →
          </Link>
        </section>

        <KiwoomTop10RealMobileSection
          liveOn={Boolean(kiwoom.live)}
          armOn={Boolean(kiwoom.arm)}
          feedLabel={statusKo(kiwoom.feed)}
          readyLabel={
            kiwoom.can_auto_trade ? "자동매매 가능" : "준비 안 됨"
          }
          autoLabel={statusKo(kiwoom.auto_trading_state)}
        />

        <section className={`${styles.card} ${styles.spanFull}`}>
          <p className={styles.empty}>
            주문·포지션·알림은 하단 메뉴에서 바로 확인할 수 있습니다. LIVE/ARM
            변경은 데스크톱 계좌·안전 제어에서만 수행하세요.
          </p>
          <Link href="/mobile" className={styles.moreLink}>
            홈(오늘 손익) →
          </Link>
        </section>
      </div>
    </div>
  );
}
