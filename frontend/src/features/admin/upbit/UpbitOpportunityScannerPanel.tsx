"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Space, Tag, Typography } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { asRecord, cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

/** Alert-only Opportunity Scanner — LIVE/주문과 무관 */
export function UpbitOpportunityScannerPanel() {
  const { message } = App.useApp();
  const qc = useQueryClient();

  const status = useQuery({
    queryKey: queryKeys.admin.upbitOpportunityScanner(),
    queryFn: adminApi.getUpbitOpportunityScannerStatus,
    refetchInterval: 30_000,
  });

  const runOnce = useMutation({
    mutationFn: () =>
      adminApi.runUpbitOpportunityScanner({ notify: true, force_ai: false }),
    onSuccess: () => {
      message.success("Scanner Dry Run 완료 (Alert-only)");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitOpportunityScanner(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const st = asRecord(status.data) ?? {};
  const summary = asRecord(st.last_result_summary) ?? {};
  const candidates = Array.isArray(summary.candidates)
    ? (summary.candidates as Record<string, unknown>[])
    : [];

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        Opportunity Scanner (Alert-only)
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        KRW universe → liquidity/technical Top N → AI → Telegram. Strategy /
        LIVE / ARM / 주문과 연결되지 않습니다. 기본 enabled=false.
      </Typography.Paragraph>
      <Space wrap>
        <Tag color={st.enabled ? "green" : "default"}>
          enabled={String(st.enabled ?? false)}
        </Tag>
        <Tag color={st.running ? "blue" : "default"}>
          running={String(st.running ?? false)}
        </Tag>
        <Tag>interval={cell(st.interval_seconds)}</Tag>
        <Tag>top_n={cell(st.top_n)}</Tag>
        <Button
          size="small"
          loading={runOnce.isPending}
          onClick={() => runOnce.mutate()}
        >
          Dry Run 1회
        </Button>
        <Button
          size="small"
          onClick={() => void status.refetch()}
          loading={status.isFetching}
        >
          새로고침
        </Button>
      </Space>
      <AdminJsonCard
        title="Scanner Status"
        loading={status.isLoading}
        error={status.error ? toApiError(status.error) : null}
        data={{
          last_run_at: st.last_run_at,
          next_run_at: st.next_run_at,
          run_count: st.run_count,
          success_count: st.success_count,
          failure_count: st.failure_count,
          last_error: st.last_error,
          universe_count: summary.universe_count,
          liquidity_pass_count: summary.liquidity_pass_count,
          technical_candidate_count: summary.technical_candidate_count,
          ai_calls: summary.ai_calls,
          elapsed_ms: summary.elapsed_ms,
          notifications: summary.notifications,
          alert_only: true,
          live_auto_start: false,
        }}
      />
      <AdminDataTable
        title="Last Top Candidates"
        loading={status.isLoading}
        rowKey={(r) => cell(r.symbol ?? r.rank)}
        columns={[
          { title: "rank", dataIndex: "rank", width: 70 },
          { title: "symbol", dataIndex: "symbol" },
          { title: "score", dataIndex: "score" },
          { title: "AI", dataIndex: "recommendation" },
          { title: "confidence", dataIndex: "confidence" },
          { title: "risk", dataIndex: "risk_level" },
        ]}
        dataSource={candidates}
      />
    </Space>
  );
}
