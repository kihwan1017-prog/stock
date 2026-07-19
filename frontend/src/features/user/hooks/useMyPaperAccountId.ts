"use client";

import { useQuery } from "@tanstack/react-query";

import { asRecord } from "@/features/admin/utils/dataHelpers";
import * as userApi from "@/features/user/api/userApi";
import { queryKeys } from "@/lib/query/queryKeys";

/**
 * STEP52 — 로그인 사용자 Paper 계좌 ID.
 * GET /paper-accounts/me (없으면 Backend lazy 생성)
 */
export function useMyPaperAccountId() {
  const query = useQuery({
    queryKey: queryKeys.user.myPaperAccount(),
    queryFn: userApi.getMyPaperAccount,
    staleTime: 60_000,
  });

  const record = asRecord(query.data);
  const raw = record?.account_id ?? record?.id;
  const accountId =
    raw === null || raw === undefined || raw === ""
      ? null
      : Number(raw);

  return {
    accountId:
      accountId !== null && Number.isFinite(accountId) && accountId > 0
        ? accountId
        : null,
    account: record,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    refetch: query.refetch,
  };
}
