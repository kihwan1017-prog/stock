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
      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        UPBIT News / Notice Collector
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        N2 COLLECT → N3 Mapping → N3.1 Quality → N4 AI Analysis.
        AI 결과는 INFORMATIONAL ONLY. BUY/SELL/ALLOW/Scanner Apply 없음.
      </Typography.Paragraph>
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
        <Tag>universe={cell(mapping.universe_count)}</Tag>
        <Tag color="green">trusted={cell(mapping.quality_trusted)}</Tag>
        <Tag color="orange">review={cell(mapping.quality_review_required)}</Tag>
        <Tag color="gold">ambiguous_q={cell(mapping.quality_ambiguous)}</Tag>
        <Tag color="red">rejected={cell(mapping.quality_rejected)}</Tag>
        <Tag>mapped={cell(mapping.mapped_articles)}</Tag>
        <Tag>links={cell(mapping.mapping_link_count)}</Tag>
      </Space>
      <Typography.Text type="secondary">
        last_run={cell(st.last_run)} · next_run={cell(st.next_run)} · last_error=
        {cell(st.last_error ?? "-")}
      </Typography.Text>
      <Space wrap>
        <Button
          type="primary"
          loading={runOnce.isPending}
          onClick={() => runOnce.mutate()}
        >
          수동 수집 1회
        </Button>
        <Button
          loading={runMapping.isPending}
          onClick={() => runMapping.mutate()}
        >
          Symbol Mapping 실행
        </Button>
        <Button loading={runAi.isPending} onClick={() => runAi.mutate()}>
          AI News Analysis (max 5)
        </Button>
        <Button
          onClick={() => {
            void status.refetch();
            void recent.refetch();
            void aiStatus.refetch();
            void aiRecent.refetch();
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
        AI News Analysis (INFORMATIONAL ONLY)
      </Typography.Title>
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
        title="Collector + Mapping status"
        loading={status.isLoading}
        error={status.error ? toApiError(status.error) : null}
        data={status.data}
      />
      <AdminJsonCard
        title="AI News Analysis status"
        loading={aiStatus.isLoading}
        error={aiStatus.error ? toApiError(aiStatus.error) : null}
        data={aiStatus.data}
      />
    </Space>
  );
}
