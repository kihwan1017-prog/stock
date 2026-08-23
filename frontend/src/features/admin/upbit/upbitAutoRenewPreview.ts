/** 24H auto-renew preview 파싱 — null-safe (테스트 가능) */

import { asRecord } from "@/shared/utils/dataHelpers";

export type AutoRenewPreviewParsed = {
  preview: Record<string, unknown>;
  precheck: Record<string, unknown>;
  precheckBlockers: string[];
  hasPreviewData: boolean;
};

export function parseAutoRenewPreview(
  data: unknown,
): AutoRenewPreviewParsed {
  const preview = asRecord(data) ?? {};
  const precheck = asRecord(preview.precheck) ?? {};
  const precheckBlockers = Array.isArray(precheck.blockers)
    ? precheck.blockers.map((x) => String(x))
    : [];
  const hasPreviewData = data != null && asRecord(data) != null;
  return { preview, precheck, precheckBlockers, hasPreviewData };
}
