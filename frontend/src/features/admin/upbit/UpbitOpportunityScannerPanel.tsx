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
    { title: "종목", dataIndex: "symbol" },
    { title: "AI 판단", dataIndex: "recommendation", width: 88 },
    { title: "진입가", dataIndex: "entry_price" },
    { title: "시작", dataIndex: "detected_at" },
    { title: "5분", dataIndex: "return_5m_pct", width: 70 },
    { title: "15분", dataIndex: "return_15m_pct", width: 70 },
    { title: "30분", dataIndex: "return_30m_pct", width: 70 },
    { title: "60분", dataIndex: "return_60m_pct", width: 70 },
    { title: "최대유리폭(MFE)", dataIndex: "mfe_pct", width: 110 },
    { title: "최대불리폭(MAE)", dataIndex: "mae_pct", width: 110 },
    { title: "상태", dataIndex: "status", width: 100 },
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
      {(() => {
        const ab = asRecord(shadowStats.entry_policy_ab) ?? {};
        const base = asRecord(ab.baseline) ?? {};
        const cand = asRecord(ab.candidate_b) ?? {};
        if (!ab.sample_count && ab.sample_count !== 0) return null;
        return (
          <>
            <Typography.Title level={5} style={{ marginBottom: 0 }}>
              진입 정책 A/B (Shadow)
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              Shadow 진입만 비교합니다 (청산=TP10/Trail3 고정, REAL 미변경). 기준
              전략 vs 후보 B (RSI65 / VOL1.0).
            </Typography.Paragraph>
            <Space wrap>
              <Tag>
                표본={cell(ab.sample_count)} / {cell(ab.final_verdict)}
              </Tag>
              <Tag>
                기준 전략 진입={cell(ab.baseline_entries)} 손익=
                {cell(base.net_pnl)} 승률={cell(base.win_rate)}
              </Tag>
              <Tag color="blue">
                후보 B 진입={cell(ab.candidate_entries)} 손익=
                {cell(cand.net_pnl)} 승률={cell(cand.win_rate)} 필터=
                {cell(ab.candidate_filtered_count)}
              </Tag>
            </Space>
          </>
        );
      })()}
      {(() => {
        const fv = asRecord(shadowStats.entry_b1_forward_validation) ?? {};
        const progress = asRecord(fv.progress) ?? {};
        const base = asRecord(fv.baseline) ?? {};
        const b1 = asRecord(fv.b1) ?? {};
        const filt = asRecord(fv.filter_attribution) ?? {};
        const early = asRecord(fv.early_dump) ?? {};
        if (fv.combined_sample_count == null && fv.combined_sample_count !== 0) {
          return null;
        }
        const promoRaw = String(fv.PROMOTION_STATUS ?? "NOT READY");
        const promo =
          promoRaw === "REVIEW READY"
            ? "적용 검토 가능"
            : promoRaw === "NOT READY"
              ? "표본 수집 중"
              : promoRaw;
        return (
          <>
            <Typography.Title level={5} style={{ marginBottom: 0 }}>
              진입 전략 Forward 검증
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              검증 후보 B1 (RSI65 / VOL0.8) · LEGACY+신규 표본 분리 · REAL 정책
              미변경 · 자동 승격 없음
            </Typography.Paragraph>
            <Space wrap>
              <Tag>검증 후보: RSI65 / VOL0.8</Tag>
              <Tag>전체 표본 {cell(progress.combined)}</Tag>
              <Tag>신규 미사용 표본 {cell(progress.new)}</Tag>
              <Tag>
                기준 전략 손익={cell(base.net_pnl)} PF=
                {cell(base.profit_factor)} 승률={cell(base.win_rate)}
              </Tag>
              <Tag color="blue">
                후보 B1 손익={cell(b1.net_pnl)} PF={cell(b1.profit_factor)} 승률=
                {cell(b1.win_rate)}
              </Tag>
              <Tag>필터 개선 효과={cell(filt.net_filter_benefit)}</Tag>
              <Tag>
                진입 직후 하락 기준/B1=
                {cell(early.baseline_early_dump_rate)}/
                {cell(early.b1_early_dump_rate)}
              </Tag>
              <Tag color={promoRaw === "REVIEW READY" ? "green" : "default"}>
                REAL 적용 검토: {promo}
              </Tag>
            </Space>
            <details style={{ marginTop: 4 }}>
              <summary style={{ cursor: "pointer" }}>B1 상세 (펼치기)</summary>
              <AdminJsonCard
                title="진입 전략 B1 Forward 검증 상세"
                loading={false}
                error={null}
                data={fv}
              />
            </details>
          </>
        );
      })()}
      <AdminJsonCard
        title="Shadow 통계 / 코호트"
        loading={status.isLoading}
        error={null}
        data={shadowStats}
      />
    </Space>
  );
}
