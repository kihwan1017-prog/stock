"use client";

import { useQuery } from "@tanstack/react-query";
import { Form, Input, Space, Button } from "antd";
import { useState } from "react";

import { PageContainer } from "@/components/common/PageContainer";
import { JsonPanel } from "@/features/user/components/JsonPanel";
import * as userApi from "@/features/user/api/userApi";
import { queryKeys } from "@/lib/query/queryKeys";
import { toApiError } from "@/lib/api/apiError";

export default function UserAiPage() {
  const [exchange, setExchange] = useState("KRX");

  const top = useQuery({
    queryKey: queryKeys.user.topCandidates(exchange),
    queryFn: () => userApi.getTopCandidates(exchange),
  });
  const latest = useQuery({
    queryKey: queryKeys.user.aiLatest(exchange),
    queryFn: () => userApi.getLatestAiAnalysis(exchange),
  });
  const runs = useQuery({
    queryKey: queryKeys.user.aiRuns(),
    queryFn: userApi.listAiAnalysisRuns,
  });

  return (
    <PageContainer title="AI 추천" description="candidates/top · ai-analysis API (Ollama 필요)">
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Form
          layout="inline"
          onFinish={(v: { exchange_code: string }) => setExchange(v.exchange_code)}
          initialValues={{ exchange_code: exchange }}
        >
          <Form.Item name="exchange_code" rules={[{ required: true }]}>
            <Input placeholder="exchange_code" style={{ width: 160 }} />
          </Form.Item>
          <Button htmlType="submit">조회</Button>
        </Form>
        <JsonPanel
          title={`GET /api/v1/candidates/top/${exchange}`}
          loading={top.isLoading}
          error={top.error ? toApiError(top.error) : null}
          data={top.data}
        />
        <JsonPanel
          title={`GET /api/v1/ai-analysis/latest/${exchange}`}
          loading={latest.isLoading}
          error={latest.error ? toApiError(latest.error) : null}
          data={latest.data}
        />
        <JsonPanel
          title="GET /api/v1/ai-analysis/runs"
          loading={runs.isLoading}
          error={runs.error ? toApiError(runs.error) : null}
          data={runs.data}
        />
      </Space>
    </PageContainer>
  );
}
