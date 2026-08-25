"use client";

import { Suspense } from "react";

import { LlmLearningCenterPage } from "@/features/admin/llm-learning/LlmLearningCenterView";

export default function AdminLlmLearningPage() {
  return (
    <Suspense fallback={null}>
      <LlmLearningCenterPage />
    </Suspense>
  );
}
