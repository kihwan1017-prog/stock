"use client";

import { useQuery } from "@tanstack/react-query";
import { Button, Form, Input, Space } from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminAiPage() {
  const [exchange, setExchange] = useState("KRX");
  const asOf = adminApi.todayKst();

  const runs = useQuery({
    queryKey: queryKeys.admin.aiRuns(),
    queryFn: () => adminApi.listAiAnalysisRuns(),
  });
  const latest = useQuery({
    queryKey: queryKeys.admin.aiLatest(exchange),
    queryFn: () => adminApi.getLatestAiAnalysis(exchange),
    retry: false,
  });
  const top = useQuery({
    queryKey: queryKeys.admin.topCandidates(exchange, asOf),
    queryFn: () => adminApi.getTopCandidates(exchange, asOf),
  });

  const latestError = latest.error ? toApiError(latest.error) : null;
  const latest404 = latestError?.status === 404;

  return (
    <AdminPageShell title="AI 관리" description="ai-analysis · candidates/top (Ollama 내부 호출)">
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Form
          layout="inline"
          initialValues={{ exchange_code: exchange }}
          onFinish={(v: { exchange_code: string }) => setExchange(v.exchange_code)}
        >
          <Form.Item name="exchange_code" rules={[{ required: true }]}>
            <Input style={{ width: 120 }} />
          </Form.Item>
          <Button htmlType="submit">조회</Button>
        </Form>

        <AdminDataTable
          title="GET /ai-analysis/runs"
          loading={runs.isLoading}
          error={runs.error ? toApiError(runs.error) : null}
          rowKey={(r) => cell(r.analysis_run_id ?? r.id ?? JSON.stringify(r))}
          columns={[
            { title: "run_id", dataIndex: "analysis_run_id", sorter: true },
            { title: "exchange", dataIndex: "exchange_code" },
            { title: "model", dataIndex: "model" },
            { title: "errors", dataIndex: "error_count" },
            { title: "duration_ms", dataIndex: "duration_ms" },
          ]}
          dataSource={extractRows(runs.data)}
        />

        <AdminJsonCard
          title={`GET /ai-analysis/latest/${exchange}`}
          loading={latest.isLoading}
          error={latest404 ? null : latestError}
          data={
            latest404
              ? { message: "아직 AI 분석 결과가 없습니다." }
              : latest.data
          }
        />

        <AdminDataTable
          title={`GET /candidates/top/${exchange}?as_of_date=${asOf}`}
          loading={top.isLoading}
          error={top.error ? toApiError(top.error) : null}
          rowKey={(r) => cell(r.symbol ?? JSON.stringify(r))}
          columns={[
            { title: "symbol", dataIndex: "symbol", sorter: true },
            { title: "score", dataIndex: "total_score", sorter: true },
            { title: "trade_date", dataIndex: "trade_date" },
          ]}
          dataSource={extractRows(top.data)}
        />
      </Space>
    </AdminPageShell>
  );
}
