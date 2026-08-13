"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Space, Tag, Typography } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { asRecord, cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

/** N6 EXPERIMENT ONLY — CONTROL Scanner/Shadow 변경 없음. */
export function UpbitNewsCombinedShadowPanel() {
  const { message } = App.useApp();
  const qc = useQueryClient();

  const status = useQuery({
    queryKey: queryKeys.admin.upbitCombinedShadow(),
    queryFn: adminApi.getUpbitCombinedShadowStatus,
    refetchInterval: 30_000,
  });

  const recent = useQuery({
    queryKey: queryKeys.admin.upbitCombinedShadowRecent(),
    queryFn: () => adminApi.getUpbitCombinedShadowRecent({ limit: 20 }),
    refetchInterval: 60_000,
  });

  const stats = useQuery({
    queryKey: queryKeys.admin.upbitCombinedShadowStats(),
    queryFn: adminApi.getUpbitCombinedShadowStats,
    refetchInterval: 60_000,
  });

  const runOnce = useMutation({
    mutationFn: () =>
      adminApi.runUpbitCombinedShadow({ limit_runs: 5, force: false }),
    onSuccess: () => {
      message.success(
        "Combined Shadow Experiment run 완료 (CONTROL 미변경 / LLM 0)",
      );
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitCombinedShadow(),
      });
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitCombinedShadowRecent(),
      });
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitCombinedShadowStats(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const evaluate = useMutation({
    mutationFn: () => adminApi.evaluateUpbitCombinedShadow({ limit: 50 }),
    onSuccess: () => {
      message.success("Experiment evaluate 완료 (CONTROL Shadow 미변경)");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitCombinedShadow(),
      });
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitCombinedShadowRecent(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const st = asRecord(status.data) ?? {};
  const byDecision = asRecord(st.by_decision) ?? {};
  const byNews = asRecord(st.by_news_context) ?? {};
  const milestone = asRecord(st.sample_milestone) ?? {};
  const diagnostics = asRecord(st.diagnostics) ?? {};
  const pipeline = asRecord(st.pipeline) ?? {};
  const pipelineEnv = asRecord(pipeline.env) ?? {};
  const futureAt = asRecord(pipeline.future_signal_at) ?? {};
  const matchedExamples = Array.isArray(st.matched_examples)
    ? (st.matched_examples as Record<string, unknown>[])
    : [];
  const items = Array.isArray(asRecord(recent.data)?.items)
    ? (asRecord(recent.data)?.items as Record<string, unknown>[])
    : [];

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        News Combined Experiment (EXPERIMENT / SHADOW ONLY)
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        CONTROL Scanner/Shadow/Cohort 불변. experimental score ≠ scanner_score.
        BOOST/UNCHANGED/DEPRIORITIZE는 실험 라벨이며 BUY/SELL/ALLOW 아님.
      </Typography.Paragraph>
      <Space wrap>
        <Tag>Collector={String(pipelineEnv.UPBIT_NOTICE_COLLECTION_ENABLED ?? "?")}</Tag>
        <Tag>Crypto={String(pipelineEnv.CRYPTO_NEWS_COLLECTION_ENABLED ?? "?")}</Tag>
        <Tag>N4={String(pipelineEnv.UPBIT_NEWS_AI_ANALYSIS_ENABLED ?? "?")}</Tag>
        <Tag>N5={String(pipelineEnv.UPBIT_NEWS_SIGNAL_ENABLED ?? "?")}</Tag>
        <Tag>N6Exp={String(pipelineEnv.UPBIT_NEWS_COMBINED_SHADOW_ENABLED ?? "?")}</Tag>
        <Tag>MappingGlue={String(asRecord(pipeline.n3_automation)?.post_collect_glue ?? false)}</Tag>
      </Space>
      <Space wrap>
        <Tag>
          N4_pending=
          {cell(asRecord(asRecord(pipeline.latency_alignment)?.backlog)?.pending_n)}
        </Tag>
        <Tag>
          oldest_pending_s=
          {cell(
            asRecord(asRecord(pipeline.latency_alignment)?.backlog)
              ?.oldest_pending_age_s,
          )}
        </Tag>
        <Tag>
          N4→N5_med=
          {cell(
            asRecord(
              asRecord(asRecord(pipeline.latency_alignment)?.historical)?.n4_to_n5,
            )?.median_s,
          )}
        </Tag>
        <Tag>
          collect→N5_med=
          {cell(
            asRecord(
              asRecord(asRecord(pipeline.latency_alignment)?.historical)
                ?.collection_to_n5,
            )?.median_s,
          )}
        </Tag>
        <Tag>
          in_1h=
          {cell(
            asRecord(asRecord(pipeline.latency_alignment)?.capacity)
              ?.incoming_articles_1h,
          )}
        </Tag>
        <Tag>
          N4_cap/h=
          {cell(
            asRecord(asRecord(pipeline.latency_alignment)?.capacity)
              ?.n4_theoretical_capacity_per_hour,
          )}
        </Tag>
        <Tag>
          latency_root=
          {cell(asRecord(pipeline.latency_alignment)?.root_cause)}
        </Tag>
      </Space>
      <Space wrap>
        <Tag>enabled={String(st.enabled ?? false)}</Tag>
        <Tag>rows={cell(st.total_rows)}</Tag>
        <Tag color="purple">sample={cell(milestone.status)}</Tag>
        <Tag>
          review_target=20/20 matched={cell(milestone.matched_completed)}/
          {cell(milestone.matched_target)} no_news=
          {cell(milestone.no_news_completed)}/{cell(milestone.no_news_target)}
        </Tag>
        <Tag>
          overlap={cell(diagnostics.intersection_count_all)} rate=
          {cell(diagnostics.overlap_rate_all)}
        </Tag>
        <Tag>root={cell(diagnostics.root_cause)}</Tag>
        <Tag>
          FUTURE_SIGNAL_AT=
          {cell(futureAt.future_signal_at_excluded)}
        </Tag>
        <Tag>24h_articles={cell(diagnostics.collected_articles_total)}</Tag>
        <Tag>TRUSTED={cell(diagnostics.trusted_mapped_articles)}</Tag>
        <Tag>N4_ok={cell(diagnostics.completed_n4_analyses_24h)}</Tag>
        <Tag>N5_valid={cell(diagnostics.valid_n5_signals)}</Tag>
        <Tag>NEWS_MATCHED={cell(byNews.NEWS_MATCHED)}</Tag>
        <Tag>NO_NEWS={cell(byNews.NO_NEWS)}</Tag>
        <Tag>EXCLUDED={cell(byNews.EXCLUDED_ONLY)}</Tag>
        <Tag>BOOST={cell(byDecision.BOOST)}</Tag>
        <Tag>UNCHANGED={cell(byDecision.UNCHANGED)}</Tag>
        <Tag>DEPRIORITIZE={cell(byDecision.DEPRIORITIZE)}</Tag>
        <Tag color="blue">completed={cell(st.completed_n)}</Tag>
      </Space>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Top N DB history 재사용 불가 (SOURCE_COVERAGE_LIMITED). Apply/Enable Trading 버튼 없음.
        experimental_rank만으로 우수 종목 결론 금지. look-ahead 완화 금지.
      </Typography.Paragraph>
      <Space wrap>
        <Button type="primary" loading={runOnce.isPending} onClick={() => runOnce.mutate()}>
          Experiment Run (recent 5 runs)
        </Button>
        <Button loading={evaluate.isPending} onClick={() => evaluate.mutate()}>
          Evaluate Pending
        </Button>
        <Button
          onClick={() => {
            void status.refetch();
            void recent.refetch();
            void stats.refetch();
          }}
        >
          새로고침
        </Button>
      </Space>
      <AdminDataTable
        title="Latest NEWS_MATCHED examples"
        loading={status.isLoading}
        rowKey="experiment_id"
        columns={[
          { title: "symbol", dataIndex: "symbol", width: 100 },
          { title: "run", dataIndex: "scanner_run_id", width: 120 },
          { title: "rank", dataIndex: "actual_rank", width: 60 },
          { title: "dir", dataIndex: "direction", width: 70 },
          { title: "contrib", dataIndex: "contribution", width: 80 },
          { title: "news_comp", dataIndex: "news_component", width: 90 },
          { title: "exp_score", dataIndex: "experimental_score", width: 90 },
          { title: "cf_rank", dataIndex: "experimental_rank", width: 70 },
          { title: "Δrank", dataIndex: "rank_delta", width: 60 },
          { title: "r60", dataIndex: "return_60m_pct", width: 70 },
          { title: "MFE", dataIndex: "mfe_pct", width: 70 },
          { title: "MAE", dataIndex: "mae_pct", width: 70 },
        ]}
        dataSource={matchedExamples.map((row, idx) => ({
          ...row,
          // AdminDataTable 기본 rowKey=id 대신 experiment_id 사용
          experiment_id: row.experiment_id ?? `matched-${idx}`,
        }))}
      />
      <AdminDataTable
        title="Recent Experiment Rows"
        loading={recent.isLoading}
        rowKey="experiment_id"
        columns={[
          { title: "symbol", dataIndex: "symbol", width: 100 },
          { title: "rank", dataIndex: "control_scanner_rank", width: 60 },
          { title: "scan", dataIndex: "control_scanner_score", width: 70 },
          { title: "news#", dataIndex: "eligible_news_count", width: 60 },
          { title: "news_comp", dataIndex: "news_component_normalized", width: 90 },
          { title: "exp_score", dataIndex: "experimental_combined_score", width: 90 },
          { title: "decision", dataIndex: "experimental_decision", width: 110 },
          { title: "cf_rank", dataIndex: "counterfactual_rank", width: 70 },
          { title: "Δrank", dataIndex: "rank_delta", width: 60 },
          { title: "r60", dataIndex: "return_60m_pct", width: 70 },
          { title: "MFE", dataIndex: "mfe_pct", width: 70 },
          { title: "MAE", dataIndex: "mae_pct", width: 70 },
          { title: "status", dataIndex: "evaluation_status", width: 100 },
        ]}
        dataSource={items.map((row, idx) => ({
          ...row,
          experiment_id: row.experiment_id ?? `exp-${idx}`,
        }))}
      />
      <AdminJsonCard
        title="Experiment stats"
        loading={stats.isLoading}
        error={stats.error ? toApiError(stats.error) : null}
        data={stats.data}
      />
    </Space>
  );
}
