"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Space, Tag, Typography } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { asRecord, cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

/** N2 Collector + N3 Symbol Mapping. AI/Sentiment/Score 표시 금지. */
export function UpbitNewsNoticeCollectorPanel() {
  const { message } = App.useApp();
  const qc = useQueryClient();

  const status = useQuery({
    queryKey: queryKeys.admin.upbitNewsCollector(),
    queryFn: adminApi.getUpbitNewsCollectorStatus,
    refetchInterval: 30_000,
  });

  const recent = useQuery({
    queryKey: queryKeys.admin.upbitNewsCollectorRecent(),
    queryFn: () => adminApi.getUpbitNewsCollectorRecent({ limit: 20 }),
    refetchInterval: 60_000,
  });

  const runOnce = useMutation({
    mutationFn: () =>
      adminApi.runUpbitNewsCollector({
        include_notice: true,
        include_crypto: true,
      }),
    onSuccess: () => {
      message.success("News/Notice 수집 1회 완료 (AI/Scanner 미연동)");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitNewsCollector(),
      });
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitNewsCollectorRecent(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const runMapping = useMutation({
    mutationFn: () =>
      adminApi.runUpbitNewsSymbolMapping({
        include_notice: true,
        include_crypto: true,
      }),
    onSuccess: () => {
      message.success("Symbol Mapping 완료 (AI/Scanner/Shadow 미연동)");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitNewsCollector(),
      });
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitNewsCollectorRecent(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const aiStatus = useQuery({
    queryKey: queryKeys.admin.upbitNewsAnalysis(),
    queryFn: adminApi.getUpbitNewsAnalysisStatus,
    refetchInterval: 30_000,
  });

  const aiRecent = useQuery({
    queryKey: queryKeys.admin.upbitNewsAnalysisRecent(),
    queryFn: () => adminApi.getUpbitNewsAnalysisRecent({ limit: 20 }),
    refetchInterval: 60_000,
  });

  const runAi = useMutation({
    mutationFn: () =>
      adminApi.runUpbitNewsAnalysis({ limit: 5, force: false }),
    onSuccess: () => {
      message.success(
        "AI News Analysis 완료 (INFORMATIONAL ONLY / 주문·Gate 없음)",
      );
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitNewsAnalysis(),
      });
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitNewsAnalysisRecent(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const signalStatus = useQuery({
    queryKey: queryKeys.admin.upbitNewsSignals(),
    queryFn: adminApi.getUpbitNewsSignalsStatus,
    refetchInterval: 30_000,
  });

  const signalRecent = useQuery({
    queryKey: queryKeys.admin.upbitNewsSignalsRecent(),
    queryFn: () => adminApi.getUpbitNewsSignalsRecent({ limit: 20 }),
    refetchInterval: 60_000,
  });

  const signalStats = useQuery({
    queryKey: queryKeys.admin.upbitNewsSignalsStats(),
    queryFn: adminApi.getUpbitNewsSignalsStats,
    refetchInterval: 60_000,
  });

  const runSignals = useMutation({
    mutationFn: () =>
      adminApi.runUpbitNewsSignals({ limit: 50, force: false }),
    onSuccess: () => {
      message.success(
        "News Signal 표준화 완료 (INFORMATIONAL ONLY / LLM·Scanner 없음)",
      );
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitNewsSignals(),
      });
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitNewsSignalsRecent(),
      });
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.upbitNewsSignalsStats(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const st = asRecord(status.data) ?? {};
  const sources = asRecord(st.sources) ?? {};
  const notice = asRecord(sources.UPBIT_NOTICE) ?? {};
  const crypto = asRecord(sources.CRYPTO_NEWS) ?? {};
  const mapping = asRecord(st.symbol_mapping) ?? {};
  const recentPayload = asRecord(recent.data) ?? {};
  const items = Array.isArray(recentPayload.items)
    ? (recentPayload.items as Record<string, unknown>[])
    : [];

  const qualityColor = (status: unknown) => {
    const s = String(status || "").toUpperCase();
    if (s === "TRUSTED") return "green";
    if (s === "REVIEW_REQUIRED") return "orange";
    if (s === "AMBIGUOUS") return "gold";
    if (s === "REJECTED") return "red";
    return "default";
  };

  const columns = [
    { title: "source", dataIndex: "source", width: 110 },
    { title: "category", dataIndex: "category", width: 120 },
    { title: "title", dataIndex: "title" },
    {
      title: "Mapped Symbols",
      dataIndex: "mapped_symbols",
      width: 280,
      render: (value: unknown) => {
        if (!Array.isArray(value) || value.length === 0) {
          return <Typography.Text type="secondary">—</Typography.Text>;
        }
        return (
          <Space wrap size={[4, 4]} orientation="vertical">
            {value.map((row) => {
              const rec = asRecord(row) ?? {};
              const q = cell(rec.quality_status ?? "—");
              const label = `${cell(rec.symbol)} · ${q} · ${cell(rec.match_type)}/${cell(rec.mapping_confidence)}`;
              return (
                <Tag
                  key={`${String(rec.symbol)}-${q}`}
                  color={qualityColor(rec.quality_status)}
                  title={String(rec.quality_reason ?? rec.review_reason ?? "")}
                >
                  {label}
                </Tag>
              );
            })}
          </Space>
        );
      },
    },
    { title: "map", dataIndex: "mapping_status", width: 90 },
    { title: "published_at", dataIndex: "published_at", width: 160 },
  ];

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        N2 COLLECT → N3 Mapping → N3.1 Quality → N4 AI Analysis → N5 News Signal.
        Signal은 INFORMATIONAL ONLY. BUY/SELL/ALLOW/Scanner Apply 없음. N6 A/B는
        「A/B 실험」탭을 사용합니다.
      </Typography.Paragraph>

      {/* M5-C: N2 → N3/N3.1 → N4 → N5 */}
      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        뉴스 수집
      </Typography.Title>
      <Space wrap>
        <Tag color={st.enabled ? "green" : "default"}>
          enabled={String(st.enabled ?? false)}
        </Tag>
        <Tag color={st.running ? "blue" : "default"}>
          running={String(st.running ?? false)}
        </Tag>
        <Tag>
          notice={String(notice.enabled ?? false)}/
          {cell(notice.interval_seconds)}s
        </Tag>
        <Tag>
          crypto={String(crypto.enabled ?? false)}/
          {cell(crypto.interval_seconds)}s
        </Tag>
      </Space>
      <Typography.Text type="secondary">
        LAST_CHECK={cell(st.last_check_at ?? st.last_run)} · LAST_SUCCESS=
        {cell(st.last_success_at ?? st.last_success)} · LAST_NEW_ITEM=
        {cell(st.last_new_item_at ?? "-")} · next_run={cell(st.next_run)} ·
        last_error={cell(st.last_error ?? "-")}
      </Typography.Text>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        새 뉴스가 없어도 check/success면 STALE/BROKEN이 아닙니다. LAST_NEW_ITEM만
        실제 insert 시각입니다.
      </Typography.Paragraph>
      <Space wrap>
        <Button
          type="primary"
          loading={runOnce.isPending}
          onClick={() => runOnce.mutate()}
        >
          수동 수집 1회
        </Button>
        <Button
          onClick={() => {
            void status.refetch();
            void recent.refetch();
            void aiStatus.refetch();
            void aiRecent.refetch();
            void signalStatus.refetch();
            void signalRecent.refetch();
            void signalStats.refetch();
          }}
        >
          새로고침
        </Button>
      </Space>
      <AdminDataTable
        title="최근 공지/뉴스 (+ Mapped Symbols)"
        loading={recent.isLoading}
        columns={columns}
        dataSource={items.map((row, idx) => ({
          key: String(row.article_id ?? idx),
          ...row,
        }))}
      />

      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        심볼 매핑 · 품질
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        N3 Symbol Mapping과 N3.1 quality(TRUSTED/REVIEW/AMBIGUOUS/REJECTED)입니다.
        매핑 결과는 위 최근 기사 테이블의 Mapped Symbols에도 표시됩니다.
      </Typography.Paragraph>
      <Space wrap>
        <Tag>universe={cell(mapping.universe_count)}</Tag>
        <Tag color="green">trusted={cell(mapping.quality_trusted)}</Tag>
        <Tag color="orange">review={cell(mapping.quality_review_required)}</Tag>
        <Tag color="gold">ambiguous_q={cell(mapping.quality_ambiguous)}</Tag>
        <Tag color="red">rejected={cell(mapping.quality_rejected)}</Tag>
        <Tag>mapped={cell(mapping.mapped_articles)}</Tag>
        <Tag>links={cell(mapping.mapping_link_count)}</Tag>
        <Button
          loading={runMapping.isPending}
          onClick={() => runMapping.mutate()}
        >
          Symbol Mapping 실행
        </Button>
      </Space>
      <AdminJsonCard
        title="Collector + Mapping status"
        loading={status.isLoading}
        error={status.error ? toApiError(status.error) : null}
        data={status.data}
      />

      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        AI 뉴스 분석
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        INFORMATIONAL ONLY. BUY/SELL/ALLOW/APPLY 없음.
      </Typography.Paragraph>
      <Space wrap>
        <Tag>
          enabled=
          {String(asRecord(aiStatus.data)?.enabled ?? false)}
        </Tag>
        <Tag>model={cell(asRecord(aiStatus.data)?.model)}</Tag>
        <Tag>
          completed=
          {cell(
            asRecord(asRecord(aiStatus.data)?.status_counts)?.COMPLETED,
          )}
        </Tag>
        <Tag>
          failed=
          {cell(asRecord(asRecord(aiStatus.data)?.status_counts)?.FAILED)}
        </Tag>
        <Tag>
          skipped=
          {cell(asRecord(asRecord(aiStatus.data)?.status_counts)?.SKIPPED)}
        </Tag>
        <Button loading={runAi.isPending} onClick={() => runAi.mutate()}>
          AI News Analysis (max 5)
        </Button>
      </Space>
      <AdminDataTable
        title="최근 AI 분석 (sentiment ≠ trade signal)"
        loading={aiRecent.isLoading}
        columns={[
          { title: "source", dataIndex: "source_type", width: 110 },
          { title: "title", dataIndex: "title" },
          { title: "event", dataIndex: "event_type", width: 120 },
          { title: "sentiment", dataIndex: "sentiment", width: 100 },
          { title: "impact", dataIndex: "news_impact_level", width: 90 },
          { title: "conf", dataIndex: "news_ai_confidence", width: 70 },
          { title: "status", dataIndex: "status", width: 100 },
        ]}
        dataSource={(
          Array.isArray(asRecord(aiRecent.data)?.items)
            ? (asRecord(aiRecent.data)?.items as Record<string, unknown>[])
            : []
        ).map((row, idx) => ({
          key: String(row.analysis_id ?? idx),
          ...row,
          title: cell(row.title),
        }))}
      />
      <AdminJsonCard
        title="AI News Analysis status"
        loading={aiStatus.isLoading}
        error={aiStatus.error ? toApiError(aiStatus.error) : null}
        data={aiStatus.data}
      />

      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        News Signal
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        POSITIVE ≠ BUY · NEGATIVE ≠ SELL · News Signal ≠ AI Gate. LLM 호출 없음.
      </Typography.Paragraph>
      <Space wrap>
        <Tag>
          enabled=
          {String(asRecord(signalStatus.data)?.enabled ?? false)}
        </Tag>
        <Tag>total={cell(asRecord(signalStatus.data)?.total_signals)}</Tag>
        <Tag>
          VALID=
          {cell(asRecord(asRecord(signalStatus.data)?.by_status)?.VALID)}
        </Tag>
        <Tag>
          LOW_CONF=
          {cell(
            asRecord(asRecord(signalStatus.data)?.by_status)?.LOW_CONFIDENCE,
          )}
        </Tag>
        <Tag>
          STALE=
          {cell(asRecord(asRecord(signalStatus.data)?.by_status)?.STALE)}
        </Tag>
        <Tag>
          INVALID=
          {cell(asRecord(asRecord(signalStatus.data)?.by_status)?.INVALID)}
        </Tag>
        <Button
          loading={runSignals.isPending}
          onClick={() => runSignals.mutate()}
        >
          News Signal 표준화
        </Button>
      </Space>
      <AdminDataTable
        title="최근 News Signals"
        loading={signalRecent.isLoading}
        columns={[
          { title: "symbol", dataIndex: "symbol", width: 110 },
          { title: "direction", dataIndex: "direction", width: 100 },
          { title: "strength", dataIndex: "strength", width: 90 },
          { title: "reliability", dataIndex: "reliability", width: 100 },
          { title: "status", dataIndex: "signal_status", width: 110 },
          { title: "event", dataIndex: "event_type", width: 120 },
          { title: "impact", dataIndex: "news_impact_level", width: 90 },
          { title: "horizon", dataIndex: "time_horizon", width: 110 },
          { title: "expires", dataIndex: "expires_at", width: 170 },
          { title: "title", dataIndex: "title" },
        ]}
        dataSource={(
          Array.isArray(asRecord(signalRecent.data)?.items)
            ? (asRecord(signalRecent.data)?.items as Record<string, unknown>[])
            : []
        ).map((row, idx) => ({
          key: String(row.signal_id ?? idx),
          ...row,
          title: cell(row.title),
        }))}
      />
      <AdminJsonCard
        title="News Signal stats"
        loading={signalStats.isLoading}
        error={signalStats.error ? toApiError(signalStats.error) : null}
        data={signalStats.data}
      />
    </Space>
  );
}
