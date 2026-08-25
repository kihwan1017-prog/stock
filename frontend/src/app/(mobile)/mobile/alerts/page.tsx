"use client";

import { alertEmoji, formatClock } from "@/features/mobile/mobileFormat";
import { useMobileOverview } from "@/features/mobile/useMobileOverview";
import { toApiError } from "@/lib/api/apiError";

import styles from "@/features/mobile/mobile.module.css";

export default function MobileAlertsPage() {
  const q = useMobileOverview(30_000);
  const events = q.data?.recent_events ?? [];

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>알림</h1>
      <p className={styles.meta}>마지막 갱신: {formatClock(q.data?.updated_at)}</p>
      {q.isError ? (
        <div className={`${styles.banner} ${styles.bannerError}`}>
          {toApiError(q.error).message}
        </div>
      ) : null}
      <section className={styles.card}>
        {events.length === 0 ? (
          <p className={styles.empty}>표시할 알림이 없습니다.</p>
        ) : (
          events.map((e, idx) => (
            <div className={styles.listItem} key={`${String(e.code)}-${idx}`}>
              <div className={styles.listMain}>
                {alertEmoji(e.severity)} {String(e.title || e.code || "알림")}
              </div>
              <div className={styles.listSub}>
                {String(e.message || "").slice(0, 160)}
              </div>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
