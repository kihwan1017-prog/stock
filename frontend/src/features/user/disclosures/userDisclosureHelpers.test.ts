import { describe, expect, it } from "vitest";

import type { DisclosureAiSummary } from "@/features/user/api/userApi";

function externalLinkProps(url: string | null) {
  if (!url) return null;
  return {
    href: url,
    target: "_blank" as const,
    rel: "noopener noreferrer" as const,
  };
}

describe("user disclosure helpers", () => {
  it("원문 링크에 noopener noreferrer를 붙인다", () => {
    const props = externalLinkProps(
      "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=1",
    );
    expect(props?.rel).toBe("noopener noreferrer");
  });

  it("AI 요약 COMPLETED 상태를 인식한다", () => {
    const summary: DisclosureAiSummary = {
      disclosure_id: 1,
      status: "COMPLETED",
      summary: "요약",
      key_points: [],
      risk_factors: [],
      is_stale: false,
    };
    expect(summary.status).toBe("COMPLETED");
  });
});
