"use client";

import {
  formatClock,
  sideKo,
  statusKo,
} from "@/features/mobile/mobileFormat";
import { useMobileOverview } from "@/features/mobile/useMobileOverview";
import { toApiError } from "@/lib/api/apiError";

import styles from "@/features/mobile/mobile.module.css";

export default function MobileOrdersPage() {
  const q = useMobileOverview(15_000);
  const orders = q.data?.recent_orders ?? [];

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>최근 주문</h1>
      <p className={styles.meta}>마지막 갱신: {formatClock(q.data?.updated_at)}</p>
      {q.isError ? (
        <div className={`${styles.banner} ${styles.bannerError}`}>
          {toApiError(q.error).message}
        </div>
      ) : null}
      <section className={styles.card}>
        {orders.length === 0 ? (
          <p className={styles.empty}>최근 주문이 없습니다.</p>
        ) : (
          orders.map((o, idx) => (
            <div className={styles.listItem} key={`${String(o.order_id)}-${idx}`}>
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
      </section>
    </div>
  );
}
