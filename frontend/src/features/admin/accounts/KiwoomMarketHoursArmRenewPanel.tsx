"use client";

/**
 * 키움 장중 ARM 자동연장 — MARKET_HOURS unattended 최소 제어.
 * Upbit 24H 스택과 분리. LIVE/ARM 원본 상태는 변경하지 않음(lease/auto-renew만).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Space, Switch, Typography } from "antd";
import { useMemo, useState } from "react";

import {
  enableAdminUbaUnattended,
  getAdminUbaUnattended,
  setAdminUbaUnattendedAutoRenew,
} from "@/features/admin/api/adminApi";
import { toApiError } from "@/shared/api/http";

const CONFIRM_ENABLE = "ENABLE MARKET HOURS UNATTENDED";

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

  const data = q.data as Record<string, unknown> | undefined;
  const enabled = Boolean(data?.entry_lease_active || data?.unattended_enabled);
  const autoRenew = Boolean(data?.auto_renew_enabled);
  const mode = String(data?.authorization_mode || "MARKET_HOURS");

  const enableMut = useMutation({
    mutationFn: async () => {
      setErr(null);
      return enableAdminUbaUnattended(ubaId, {
        confirmation_text: CONFIRM_ENABLE,
        reason: "KIWOOM market-hours ARM auto-renew opt-in",
        source: "ADMIN_UI",
        authorization_mode: "MARKET_HOURS",
      });
    },
    onSuccess: async () => {
      await qc.invalidateQueries({
        queryKey: ["admin", "uba-unattended", ubaId],
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

  const summary = useMemo(() => {
    return {
      until: fmtKst(data?.authorized_until as string | undefined),
      nextRenew: fmtKst(data?.next_arm_renew_eligible_at as string | undefined),
      close: String(data?.market_hours_regular_close || "15:30"),
      lastRenew: fmtKst(data?.last_renewed_at as string | undefined),
      lastFail: (() => {
        const detail = (data?.last_renewal_detail || {}) as Record<
          string,
          unknown
        >;
        const blockers = detail.blockers;
        if (Array.isArray(blockers) && blockers.length) {
          return blockers.map(String).join(", ");
        }
        return "—";
      })(),
    };
  }, [data]);

  return (
    <Card size="small" title="장중 ARM 자동연장 (키움)">
      <Space orientation="vertical" size={8} style={{ width: "100%" }}>
        <Typography.Text>
          [장중 ARM 자동연장: {autoRenew && enabled ? "켜짐" : "꺼짐"}]
        </Typography.Text>
        <Typography.Text type="secondary">
          모드 {mode} · 현재 승인 만료: {summary.until}
        </Typography.Text>
        <Typography.Text type="secondary">
          다음 갱신 예상: {summary.nextRenew} 이후 · 정규장 종료:{" "}
          {summary.close}
        </Typography.Text>
        <Typography.Text type="secondary">
          최근 갱신: {summary.lastRenew} · 최근 실패: {summary.lastFail}
        </Typography.Text>

        {!enabled ? (
          <Button
            type="primary"
            loading={enableMut.isPending}
            onClick={() => enableMut.mutate()}
          >
            장중 자동승인 켜기
          </Button>
        ) : (
          <Space>
            <Typography.Text>자동연장</Typography.Text>
            <Switch
              checked={autoRenew}
              loading={renewMut.isPending}
              onChange={(v) => renewMut.mutate(v)}
            />
          </Space>
        )}

        {err ? <Alert type="error" showIcon title={err} /> : null}
      </Space>
    </Card>
  );
}
