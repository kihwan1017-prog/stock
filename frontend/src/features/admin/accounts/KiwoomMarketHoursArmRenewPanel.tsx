"use client";

/**
 * 키움 장중 ARM 자동연장 + 익일 자동 시작 lifecycle 최소 제어.
 * Upbit 24H 스택과 분리. REAL 주문 강제 생성 없음.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Space, Switch, Typography } from "antd";
import { useMemo, useState } from "react";

import {
  enableAdminUbaUnattended,
  getAdminUbaKiwoomLifecycle,
  getAdminUbaUnattended,
  setAdminUbaKiwoomNextDayAutoStart,
  setAdminUbaUnattendedAutoRenew,
} from "@/features/admin/api/adminApi";
import { toApiError } from "@/shared/api/http";

const CONFIRM_ENABLE = "ENABLE MARKET HOURS UNATTENDED";
const CONFIRM_NEXT_DAY_ON = "ENABLE KIWOOM NEXT DAY AUTO START";
const CONFIRM_NEXT_DAY_OFF = "DISABLE KIWOOM NEXT DAY AUTO START";

type Props = {
  ubaId: number;
};

function fmtKst(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("ko-KR", {
      timeZone: "Asia/Seoul",
      hour: "2-digit",
      minute: "2-digit",
      month: "2-digit",
      day: "2-digit",
    });
  } catch {
    return String(iso);
  }
}

export function KiwoomMarketHoursArmRenewPanel({ ubaId }: Props) {
  const qc = useQueryClient();
  const [err, setErr] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["admin", "uba-unattended", ubaId, "kiwoom-mh"],
    queryFn: () => getAdminUbaUnattended(ubaId),
    refetchInterval: 15_000,
  });

  const lifeQ = useQuery({
    queryKey: ["admin", "uba-kiwoom-lifecycle", ubaId],
    queryFn: () => getAdminUbaKiwoomLifecycle(ubaId),
    refetchInterval: 15_000,
  });

  const data = q.data as Record<string, unknown> | undefined;
  const life = lifeQ.data as Record<string, unknown> | undefined;
  const enabled = Boolean(data?.entry_lease_active || data?.unattended_enabled);
  const autoRenew = Boolean(data?.auto_renew_enabled);
  const mode = String(data?.authorization_mode || "MARKET_HOURS");
  const nextDay = Boolean(
    life?.next_trading_day_auto_start ?? data?.next_trading_day_auto_start,
  );
  const market = (life?.market || {}) as Record<string, unknown>;
  const lastPrecheck = (life?.last_precheck || {}) as Record<string, unknown>;

  const enableMut = useMutation({
    mutationFn: async () => {
      setErr(null);
      return enableAdminUbaUnattended(ubaId, {
        confirmation_text: CONFIRM_ENABLE,
        reason: "KIWOOM market-hours ARM auto-renew opt-in",
        source: "ADMIN_UI",
        authorization_mode: "MARKET_HOURS",
        next_trading_day_auto_start: true,
      });
    },
    onSuccess: async () => {
      await qc.invalidateQueries({
        queryKey: ["admin", "uba-unattended", ubaId],
      });
      await qc.invalidateQueries({
        queryKey: ["admin", "uba-kiwoom-lifecycle", ubaId],
      });
    },
    onError: (e: unknown) => setErr(toApiError(e).message),
  });

  const renewMut = useMutation({
    mutationFn: async (next: boolean) => {
      setErr(null);
      return setAdminUbaUnattendedAutoRenew(ubaId, { enabled: next });
    },
    onSuccess: async () => {
      await qc.invalidateQueries({
        queryKey: ["admin", "uba-unattended", ubaId],
      });
    },
    onError: (e: unknown) => setErr(toApiError(e).message),
  });

  const nextDayMut = useMutation({
    mutationFn: async (next: boolean) => {
      setErr(null);
      return setAdminUbaKiwoomNextDayAutoStart(ubaId, {
        enabled: next,
        confirmation_text: next ? CONFIRM_NEXT_DAY_ON : CONFIRM_NEXT_DAY_OFF,
        reason: next
          ? "KIWOOM next trading day auto-start opt-in"
          : "KIWOOM next trading day auto-start opt-out",
      });
    },
    onSuccess: async () => {
      await qc.invalidateQueries({
        queryKey: ["admin", "uba-kiwoom-lifecycle", ubaId],
      });
      await qc.invalidateQueries({
        queryKey: ["admin", "uba-unattended", ubaId],
      });
    },
    onError: (e: unknown) => setErr(toApiError(e).message),
  });

  const summary = useMemo(() => {
    const blockers = life?.lifecycle_blockers;
    const precheckBlockers = lastPrecheck.blockers;
    return {
      until: fmtKst(data?.authorized_until as string | undefined),
      nextRenew: fmtKst(data?.next_arm_renew_eligible_at as string | undefined),
      close: String(
        data?.market_hours_regular_close ||
          market.regular_close_at ||
          "15:30",
      ),
      lastRenew: fmtKst(data?.last_renewed_at as string | undefined),
      phase: String(life?.lifecycle_phase || "SAFE_IDLE"),
      session: String(life?.market_session || "—"),
      tradingDay: Boolean(life?.is_trading_day),
      calendarDate: String(market.calendar_date || "—"),
      nextOpen: fmtKst(life?.next_market_open_at as string | undefined),
      lastFail: (() => {
        if (Array.isArray(blockers) && blockers.length) {
          return blockers.map(String).join(", ");
        }
        if (Array.isArray(precheckBlockers) && precheckBlockers.length) {
          return precheckBlockers.map(String).join(", ");
        }
        return "—";
      })(),
      lastPrecheckOk:
        lastPrecheck.ok == null
          ? "—"
          : lastPrecheck.ok
            ? "통과"
            : "차단",
      live: Boolean(life?.live),
      arm: Boolean(life?.arm),
      armExp: fmtKst(life?.arm_expires_at as string | undefined),
      feed: Boolean(
        (life?.feed as Record<string, unknown> | undefined)?.connected,
      ),
      warmup: String(
        (life?.warmup as Record<string, unknown> | undefined)
          ?.warmup_status || "—",
      ),
    };
  }, [data, life, market.calendar_date, market.regular_close_at, lastPrecheck]);

  return (
    <Card size="small" title="키움 장 시작/장중 lifecycle">
      <Space orientation="vertical" size={8} style={{ width: "100%" }}>
        <Typography.Text>
          [익일 자동 시작: {nextDay ? "켜짐" : "꺼짐"}] · [장중 ARM 자동연장:{" "}
          {autoRenew && enabled ? "켜짐" : "꺼짐"}]
        </Typography.Text>
        <Typography.Text type="secondary">
          오늘 거래일: {summary.tradingDay ? "예" : "아니오"} (
          {summary.calendarDate}) · 시장: {summary.session} · lifecycle:{" "}
          {summary.phase}
        </Typography.Text>
        <Typography.Text type="secondary">
          LIVE {summary.live ? "켜짐" : "꺼짐"} · ARM{" "}
          {summary.arm ? "켜짐" : "꺼짐"} · ARM 만료: {summary.armExp}
        </Typography.Text>
        <Typography.Text type="secondary">
          시세(Feed) {summary.feed ? "연결" : "미연결"} · 지표(Warmup){" "}
          {summary.warmup} · 다음 장 시작: {summary.nextOpen}
        </Typography.Text>
        <Typography.Text type="secondary">
          승인 만료: {summary.until} · 정규장 종료: {summary.close} · 모드{" "}
          {mode}
        </Typography.Text>
        <Typography.Text type="secondary">
          마지막 precheck: {summary.lastPrecheckOk} · 차단 사유:{" "}
          {summary.lastFail}
        </Typography.Text>

        {!enabled && !nextDay ? (
          <Button
            type="primary"
            loading={enableMut.isPending}
            onClick={() => enableMut.mutate()}
          >
            장중 자동승인 켜기 (+익일 자동시작)
          </Button>
        ) : (
          <Space wrap>
            {enabled ? (
              <>
                <Typography.Text>자동연장</Typography.Text>
                <Switch
                  checked={autoRenew}
                  loading={renewMut.isPending}
                  onChange={(v) => renewMut.mutate(v)}
                />
              </>
            ) : null}
            <Typography.Text>익일 자동시작</Typography.Text>
            <Switch
              checked={nextDay}
              loading={nextDayMut.isPending}
              onChange={(v) => nextDayMut.mutate(v)}
            />
          </Space>
        )}

        {err ? <Alert type="error" showIcon title={err} /> : null}
      </Space>
    </Card>
  );
}
