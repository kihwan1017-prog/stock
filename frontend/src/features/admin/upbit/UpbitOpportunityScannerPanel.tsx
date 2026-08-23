"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Space, Tag, Typography } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { asRecord, cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

/** SHADOW_ONLY Opportunity Scanner + Paper Shadow — LIVE/주문과 무관 */
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
      message.success("Scanner Dry Run 완료 (SHADOW ONLY / LIVE ORDER: NO)");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitOpportunityScanner(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const evaluateShadows = useMutation({
    mutationFn: () => adminApi.evaluateUpbitOpportunityShadows(),
    onSuccess: () => {
      message.success("Shadow 평가 완료 (주문 없음)");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitOpportunityScanner(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const st = asRecord(status.data) ?? {};
  const summary = asRecord(st.last_result_summary) ?? {};
  const evaluator = asRecord(st.evaluator) ?? {};
  const candidates = Array.isArray(summary.candidates)
    ? (summary.candidates as Record<string, unknown>[])
    : [];
  const shadows = asRecord(st.shadows) ?? {};
  const activeShadows = Array.isArray(shadows.active)
    ? (shadows.active as Record<string, unknown>[])
    : [];
  const completedShadows = Array.isArray(shadows.completed)
    ? (shadows.completed as Record<string, unknown>[])
    : [];
  const shadowStats = asRecord(shadows.stats) ?? {};

  const shadowColumns = [
    { title: "Symbol", dataIndex: "symbol" },
    { title: "AI", dataIndex: "recommendation", width: 80 },
    { title: "Entry", dataIndex: "entry_price" },
    { title: "Started", dataIndex: "detected_at" },
    { title: "5m", dataIndex: "return_5m_pct", width: 70 },
    { title: "15m", dataIndex: "return_15m_pct", width: 70 },
    { title: "30m", dataIndex: "return_30m_pct", width: 70 },
    { title: "60m", dataIndex: "return_60m_pct", width: 70 },
    { title: "MFE", dataIndex: "mfe_pct", width: 70 },
    { title: "MAE", dataIndex: "mae_pct", width: 70 },
    { title: "Status", dataIndex: "status", width: 100 },
  ];

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        KRW universe → liquidity/technical Top N → AI → Telegram / Paper Shadow.
        Strategy / LIVE / ARM / 실주문과 연결되지 않습니다. LIVE ORDER: NO.
      </Typography.Paragraph>

      {/* M5-B: Scanner → Candidates → Shadow → Evaluate → Cohort */}
      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        Scanner 상태
      </Typography.Title>
      <Space wrap>
        <Tag color={st.enabled ? "green" : "default"}>
          enabled={String(st.enabled ?? false)}
        </Tag>
        <Tag color={String(st.mode) === "SHADOW_ONLY" ? "blue" : "orange"}>
          mode={cell(st.mode ?? "SHADOW_ONLY")}
        </Tag>
        <Tag color={st.running ? "blue" : "default"}>
          running={String(st.running ?? false)}
        </Tag>
        <Tag>interval={cell(st.interval_seconds)}</Tag>
        <Tag>duration_ms={cell(st.last_duration_ms)}</Tag>
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
          enabled: st.enabled,
          mode: st.mode,
          running: st.running,
          interval_seconds: st.interval_seconds,
          last_run_at: st.last_run_at,
          next_run_at: st.next_run_at,
          last_duration_ms: st.last_duration_ms,
          last_error: st.last_error,
          run_count: st.run_count,
          success_count: st.success_count,
          failure_count: st.failure_count,
          overlap_skip_count: st.overlap_skip_count,
          universe_count: summary.universe_count,
          liquidity_pass_count: summary.liquidity_pass_count,
          technical_candidate_count: summary.technical_candidate_count,
          ai_calls: summary.ai_calls,
          ai_failed_skipped: summary.ai_failed_skipped,
          shadow: summary.shadow,
          elapsed_ms: summary.elapsed_ms,
          notifications: summary.notifications,
          shadow_only: true,
          live_order: false,
        }}
      />

      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        후보 / AI 분석
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Scanner Top-N 후보와 기존 AI recommendation/confidence/risk 필드입니다.
        별도 Market AI 화면이 아닙니다.
      </Typography.Paragraph>
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

      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        Paper Shadow
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        ALLOW/REDUCE만 추적. SHADOW ONLY / LIVE ORDER: NO. TradingOrder/Outbox
        생성 없음.
      </Typography.Paragraph>
      <AdminDataTable
        title="Active Shadows"
        loading={status.isLoading}
        rowKey={(r) => cell(r.shadow_id ?? r.symbol)}
        columns={shadowColumns}
        dataSource={activeShadows}
      />
      <AdminDataTable
        title="Completed Shadows"
        loading={status.isLoading}
        rowKey={(r) => cell(r.shadow_id ?? r.symbol)}
        columns={shadowColumns}
        dataSource={completedShadows}
      />

      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        Shadow 평가
      </Typography.Title>
      <Space wrap>
        <Tag color={evaluator.running ? "blue" : "default"}>
          evaluator={String(evaluator.running ?? false)}/
          {cell(evaluator.interval_seconds)}s
        </Tag>
        <Button
          size="small"
          loading={evaluateShadows.isPending}
          onClick={() => evaluateShadows.mutate()}
        >
          Shadow 평가
        </Button>
      </Space>
      <AdminJsonCard
        title="Shadow Evaluator Scheduler"
        loading={status.isLoading}
        error={null}
        data={{
          enabled: evaluator.enabled,
          running: evaluator.running,
          interval_seconds: evaluator.interval_seconds,
          last_run_at: evaluator.last_run_at,
          next_run_at: evaluator.next_run_at,
          last_duration_ms: evaluator.last_duration_ms,
          last_error: evaluator.last_error,
          run_count: evaluator.run_count,
          last_result: evaluator.last_result,
          shadow_only: true,
          live_order: false,
        }}
      />

      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        Cohort 성과
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        cohort_n / cohort_status 등 기존 stats 필드만 표시합니다. 전용 Milestone
        대시보드가 아닙니다.
      </Typography.Paragraph>
      <Space wrap>
        <Tag>
          cohort={cell(shadowStats.cohort_n)}/{cell(shadowStats.cohort_status)}
        </Tag>
        <Tag
          color={Number(shadowStats.mismatch_count ?? 0) > 0 ? "red" : "default"}
        >
          mismatch={cell(shadowStats.mismatch_count ?? 0)}
        </Tag>
      </Space>
      {(() => {
        const ab = asRecord(shadowStats.exit_policy_ab) ?? {};
        const base = asRecord(ab.baseline) ?? {};
        const cand = asRecord(ab.candidate_a) ?? {};
        if (!ab.sample_count && ab.sample_count !== 0) return null;
        return (
          <>
            <Typography.Title level={5} style={{ marginBottom: 0 }}>
              Exit Policy A/B
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              Shadow exit-only 비교 (REAL 정책 미변경). Baseline vs Candidate A.
            </Typography.Paragraph>
            <Space wrap>
              <Tag>
                n={cell(ab.sample_count)}/{cell(ab.final_verdict)}
              </Tag>
              <Tag>
                Baseline net={cell(base.net_pnl)} wr={cell(base.win_rate)} TP=
                {cell(base.tp_exit_count)} Trail={cell(base.trailing_exit_count)}{" "}
                MA={cell(base.ma_exit_count)}
              </Tag>
              <Tag color="blue">
                Candidate A net={cell(cand.net_pnl)} wr={cell(cand.win_rate)} TP=
                {cell(cand.tp_exit_count)} Trail=
                {cell(cand.trailing_exit_count)} MA={cell(cand.ma_exit_count)}
              </Tag>
            </Space>
          </>
        );
      })()}
      <AdminJsonCard
        title="Shadow Stats / Cohort"
        loading={status.isLoading}
        error={null}
        data={shadowStats}
      />
    </Space>
  );
}
