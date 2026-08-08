/** LIVE Validation UBA 목록 정규화 (API 응답 shape 보정) */

import { asRecord } from "@/features/admin/utils/dataHelpers";

export type UbaOption = {
  user_broker_account_id: number;
  broker_code: string;
  account_alias?: string | null;
  is_active?: boolean;
  is_default?: boolean;
  live_order_enabled?: boolean;
  live_armed?: boolean;
  arm_expires_at?: string | null;
};

/** /user/live-order/accounts → { accounts: [...] } 및 계좌 API fallback */
export function normalizeUpbitAccounts(
  liveStatus: unknown,
  userAccounts: unknown,
): UbaOption[] {
  const live = asRecord(liveStatus);
  const liveRows =
    (live?.accounts as Record<string, unknown>[] | undefined) ??
    (live?.items as Record<string, unknown>[] | undefined) ??
    (Array.isArray(liveStatus)
      ? (liveStatus as Record<string, unknown>[])
      : []);

  const fromLive: UbaOption[] = liveRows
    .filter(
      (a) =>
        String(a.broker_code || "").toUpperCase() === "UPBIT" &&
        a.is_active !== false,
    )
    .map((a) => ({
      user_broker_account_id: Number(a.user_broker_account_id),
      broker_code: "UPBIT",
      account_alias: (a.account_alias as string | null) ?? null,
      is_active: a.is_active !== false,
      is_default: Boolean(a.is_default),
      live_order_enabled: Boolean(a.live_order_enabled),
      live_armed: Boolean(a.live_armed),
      arm_expires_at: (a.arm_expires_at as string | null) ?? null,
    }))
    .filter(
      (a) =>
        Number.isFinite(a.user_broker_account_id) &&
        a.user_broker_account_id > 0,
    );

  if (fromLive.length > 0) return fromLive;

  const uaPayload = asRecord(userAccounts);
  const uaRows =
    (uaPayload?.items as Record<string, unknown>[] | undefined) ??
    (Array.isArray(userAccounts)
      ? (userAccounts as Record<string, unknown>[])
      : []);

  return uaRows
    .filter(
      (a) =>
        String(a.account_type || a.broker_code || "").toUpperCase() ===
          "UPBIT" && a.is_active !== false,
    )
    .map((a) => ({
      user_broker_account_id: Number(a.account_id ?? a.user_broker_account_id),
      broker_code: "UPBIT",
      account_alias:
        (a.account_name as string | null) ??
        (a.account_alias as string | null) ??
        null,
      is_active: a.is_active !== false,
      is_default: Boolean(a.is_default),
      live_order_enabled: Boolean(a.live_order_enabled),
      live_armed: Boolean(a.live_armed),
      arm_expires_at: (a.arm_expires_at as string | null) ?? null,
    }))
    .filter(
      (a) =>
        Number.isFinite(a.user_broker_account_id) &&
        a.user_broker_account_id > 0,
    );
}

export function pickDefaultUba(accounts: UbaOption[]): number | null {
  if (accounts.length === 0) return null;
  if (accounts.length === 1) return accounts[0].user_broker_account_id;
  const preferred =
    accounts.find((a) => a.is_default) ??
    accounts.find((a) => a.is_active !== false) ??
    accounts[0];
  return preferred.user_broker_account_id;
}
