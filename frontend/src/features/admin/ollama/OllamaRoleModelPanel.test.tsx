/**
 * Ollama 역할 모델 패널 — 설치 Select · SHADOW · 친화적 설치 목록.
 */

import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import fs from "node:fs";
import path from "node:path";

import { OllamaRoleModelPanel } from "@/features/admin/ollama/OllamaRoleModelPanel";
import { queryKeys } from "@/lib/query/queryKeys";

vi.mock("@/features/admin/api/adminApi", () => ({
  getOllamaRoleModels: vi.fn(async () => ({})),
  listOllamaModels: vi.fn(async () => ({ models: [] })),
  updateOllamaRoleModels: vi.fn(async () => ({})),
}));

vi.mock("@/features/auth/components/PermissionButton", () => ({
  PermissionButton: ({
    children,
    ...rest
  }: {
    children: React.ReactNode;
  }) => React.createElement("button", rest, children),
}));

const ROLE_PAYLOAD = {
  schema: "ollama_role_models_v1",
  TRADING_LLM_MODE: "SHADOW",
  TRADING_LLM_REAL_GATE: false,
  installed_model_count: 3,
  installed_model_names: ["qwen3:1.7b", "qwen3.5:2b", "qwen3.5:4b"],
  installed_models: [
    {
      name: "qwen3:1.7b",
      size_gb: 1.36,
      size_bytes: 1.36 * 1024 ** 3,
      roles: ["분석"],
    },
    {
      name: "qwen3.5:2b",
      size_gb: 2.74,
      size_bytes: 2.74 * 1024 ** 3,
      roles: ["매매 판단"],
    },
    {
      name: "qwen3.5:4b",
      size_gb: 3.39,
      size_bytes: 3.39 * 1024 ** 3,
      roles: ["Teacher", "Fallback"],
    },
  ],
  roles: {
    analysis: {
      label: "분석 모델",
      purpose: "시장/후보 분석",
      description: "시장·기술지표·후보 정보를 빠르게 분석합니다.",
      RUNTIME_RESOLVED_VALUE: "qwen3:1.7b",
      DB_VALUE: "qwen3:1.7b",
      installed: true,
      FALLBACK_RULE: "empty → hardcoded 'qwen3:1.7b'",
      health: { calls: 0, ok: 0, timeouts: 0, errors: 0 },
    },
    trading: {
      label: "매매 판단 모델",
      purpose: "BUY/HOLD/REDUCE 등 Trading 판단",
      description: "분석 결과를 바탕으로 매수/보류/축소 판단을 생성합니다.",
      RUNTIME_RESOLVED_VALUE: "qwen3.5:2b",
      DB_VALUE: "qwen3.5:2b",
      mode: "SHADOW",
      installed: true,
      health: { calls: 1, ok: 1, timeouts: 0, errors: 0 },
    },
    teacher: {
      label: "Teacher 모델",
      purpose: "conflict/low-confidence/오판 사례 검토",
      description:
        "판단 충돌·낮은 신뢰도·오판 사례를 검토하여 향후 학습 데이터를 만듭니다.",
      RUNTIME_RESOLVED_VALUE: "qwen3.5:4b",
      DB_VALUE: "",
      installed: true,
      FALLBACK_RULE: "empty → ollama_model",
      health: { calls: 0, ok: 0, timeouts: 0, errors: 0 },
    },
    fallback: {
      label: "기본/Fallback 모델",
      purpose: "역할별 모델 미설정 시 fallback",
      description: "역할별 모델을 사용할 수 없을 때 사용하는 기본 모델입니다.",
      RUNTIME_RESOLVED_VALUE: "qwen3.5:4b",
      DB_VALUE: "qwen3.5:4b",
      installed: true,
    },
  },
};

describe("OllamaRoleModelPanel", () => {
  it("renders role cards, SHADOW, and friendly installed list", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    qc.setQueryData(queryKeys.admin.ollamaRoleModels(), ROLE_PAYLOAD);
    qc.setQueryData(queryKeys.admin.ollamaModels(), {
      base_url: "http://127.0.0.1:11434",
      models: ROLE_PAYLOAD.installed_models,
    });

    const html = renderToStaticMarkup(
      React.createElement(
        QueryClientProvider,
        { client: qc },
        React.createElement(OllamaRoleModelPanel),
      ),
    );

    expect(html).toContain("분석 모델");
    expect(html).toContain("매매 판단 모델");
    expect(html).toContain("Teacher 모델");
    expect(html).toContain("기본/Fallback 모델");
    expect(html).toContain("SHADOW");
    expect(html).toContain("실제 주문 Gate에 직접 연결되지");
    expect(html).toContain("설치 모델 3개");
    expect(html).toContain("약 1.36GB");
    expect(html).toContain("개발자 상세 보기");
    expect(html).not.toContain("REAL 활성화");
  });

  it("source avoids REAL gate mutation and model install/delete APIs", () => {
    const src = fs.readFileSync(
      path.join(
        process.cwd(),
        "src/features/admin/ollama/OllamaRoleModelPanel.tsx",
      ),
      "utf8",
    );
    expect(src).toContain("SHADOW");
    expect(src).not.toMatch(/enableRealGate|installModel|deleteModel|startLora/i);
    expect(src).toContain("REAL 주문 Gate를 켜지 않습니다");
  });
});
