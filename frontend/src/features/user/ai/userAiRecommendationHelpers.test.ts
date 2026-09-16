import { describe, expect, it } from "vitest";

import type {
  AiRecommendationDetail,
  UserAiStatusResponse,
} from "@/features/user/api/userApi";

describe("user AI recommendation helpers", () => {
  it("상태 응답에 Host를 포함하지 않는다", () => {
    const status: UserAiStatusResponse = {
      available: true,
      status: "AVAILABLE",
      message: "ok",
      active_model_display_name: "기본 분석 모델",
    };
    expect(status).not.toHaveProperty("base_url");
    expect(status).not.toHaveProperty("host");
  });

  it("추천 상세에 disclaimer가 있다", () => {
    const detail: AiRecommendationDetail = {
      request_id: 1,
      status: "COMPLETED",
      market_code: "KRX",
      account_id: null,
      source_type: "WATCHLIST",
      investment_horizon: "SHORT_TERM",
      risk_level: "MODERATE",
      recommendation_count: 5,
      generated_at: null,
      expires_at: null,
      is_expired: false,
      is_bookmarked: false,
      is_hidden: false,
      candidate_count: 3,
      disclaimer: "참고 정보",
      items: [],
    };
    expect(detail.disclaimer).toContain("참고");
  });
});
