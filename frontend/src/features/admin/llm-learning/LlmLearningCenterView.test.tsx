import { describe, expect, it } from "vitest";

import {
  LLM_LEARNING_ASSISTANT_ASK_TIMEOUT_MS,
} from "@/features/admin/api/adminApi";
import { adminRoutes } from "@/config/routes";

describe("LlmLearningCenter", () => {
  it("exposes canonical admin route", () => {
    expect(adminRoutes.llmLearning).toBe("/admin/llm-learning");
  });

  it("uses llm-learning API prefix", () => {
    const api = "/admin/llm-learning/summary";
    expect(api).toContain("/admin/llm-learning");
  });

  it("uses extended timeout for assistant ask (Teacher 4B)", () => {
    expect(LLM_LEARNING_ASSISTANT_ASK_TIMEOUT_MS).toBeGreaterThanOrEqual(120_000);
  });
});
