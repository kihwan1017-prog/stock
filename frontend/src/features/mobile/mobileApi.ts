/**
 * Mobile READ-ONLY API client — GET only.
 * 이 파일에 post/put/patch/delete 추가 금지.
 */

import { apiClient } from "@/lib/api/apiClient";

import type { MobileOverview } from "./mobileFormat";

export async function getMobileOverview(): Promise<MobileOverview> {
  const { data } = await apiClient.get<MobileOverview>("/mobile/overview");
  return data;
}

export async function getMobileApiHealth(): Promise<{
  status?: string;
  read_only?: boolean;
}> {
  const { data } = await apiClient.get("/mobile/health");
  return data as { status?: string; read_only?: boolean };
}
