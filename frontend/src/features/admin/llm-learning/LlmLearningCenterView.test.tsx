import { describe, expect, it } from "vitest";

import { adminRoutes } from "@/config/routes";

describe("LlmLearningCenter", () => {
  it("exposes canonical admin route", () => {
    expect(adminRoutes.llmLearning).toBe("/admin/llm-learning");
  });

  it("uses llm-learning API prefix", () => {
    const api = "/admin/llm-learning/summary";
    expect(api).toContain("/admin/llm-learning");
  });
});
