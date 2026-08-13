"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Space, Tag, Typography } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { asRecord, cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

/** STEP N2 — COLLECT only. sentiment/AI/score/symbol 표시 금지. */
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

  const st = asRecord(status.data) ?? {};
  const sources = asRecord(st.sources) ?? {};
  const notice = asRecord(sources.UPBIT_NOTICE) ?? {};
  const crypto = asRecord(sources.CRYPTO_NEWS) ?? {};
  const recentPayload = asRecord(recent.data) ?? {};
  const items = Array.isArray(recentPayload.items)
    ? (recentPayload.items as Record<string, unknown>[])
    : [];

  const columns = [
    { title: "source", dataIndex: "source", width: 120 },
    { title: "category", dataIndex: "category", width: 140 },
    { title: "title", dataIndex: "title" },
    { title: "published_at", dataIndex: "published_at", width: 180 },
    { title: "status", dataIndex: "status", width: 90 },
  ];

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        UPBIT News / Notice Collector
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        COLLECT → NORMALIZE → DEDUP → STORE 만. Symbol Mapping / AI / Scanner /
        Shadow / Gate 연동 없음.
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
        <Tag>provider={cell(crypto.provider)}</Tag>
        <Tag>fetched={cell(st.fetched_count)}</Tag>
        <Tag>inserted={cell(st.inserted_count)}</Tag>
        <Tag>duplicate={cell(st.duplicate_count)}</Tag>
        <Tag>updated={cell(st.updated_count)}</Tag>
        <Tag>failed={cell(st.failure_count)}</Tag>
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
          onClick={() => {
            void status.refetch();
            void recent.refetch();
          }}
        >
          새로고침
        </Button>
      </Space>
      <AdminDataTable
        title="최근 공지/뉴스"
        loading={recent.isLoading}
        columns={columns}
        dataSource={items.map((row, idx) => ({
          key: String(row.article_id ?? idx),
          ...row,
        }))}
      />
      <AdminJsonCard
        title="Collector status"
        loading={status.isLoading}
        error={status.error ? toApiError(status.error) : null}
        data={status.data}
      />
    </Space>
  );
}
