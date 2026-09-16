"use client";

import {
  formatClock,
  formatKrwSigned,
  pnlClass,
} from "@/features/mobile/mobileFormat";
import { useMobileOverview } from "@/features/mobile/useMobileOverview";
import { toApiError } from "@/lib/api/apiError";

import styles from "@/features/mobile/mobile.module.css";

export default function MobilePositionsPage() {
  const q = useMobileOverview(20_000);
  const items = q.data?.positions?.items ?? [];

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>보유 포지션</h1>
      <p className={styles.meta}>마지막 갱신: {formatClock(q.data?.updated_at)}</p>
      {q.isError ? (
        <div className={`${styles.banner} ${styles.bannerError}`}>
          {toApiError(q.error).message}
        </div>
      ) : null}
      <section className={styles.card}>
        {items.length === 0 ? (
          <p className={styles.empty}>
            현재 자동매매 보유 포지션이 없습니다.
          </p>
        ) : (
          items.map((p, idx) => (
            <div className={styles.listItem} key={`${String(p.symbol)}-${idx}`}>
              <div className={styles.listMain}>
                {String(p.market || "")} · {String(p.symbol || "")}
              </div>
              <div className={styles.listSub}>
                수량 {String(p.quantity ?? "—")} · 진입 {String(p.entry ?? "—")} ·
                현재 {String(p.current ?? "—")}
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
      </section>
    </div>
  );
}
