"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Form, Input, Space } from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminNewsPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [ex, setEx] = useState("KRX");
  const [symbol, setSymbol] = useState("005930");

  const news = useQuery({
    queryKey: queryKeys.admin.news(ex, symbol),
    queryFn: () => adminApi.getNews(ex, symbol),
  });
  const failures = useQuery({
    queryKey: queryKeys.admin.newsFailures(),
    queryFn: adminApi.listNewsFailures,
  });

  const sync = useMutation({
    mutationFn: (v: { exchange_code: string; symbol: string; query: string }) =>
      adminApi.syncNews(v),
    onSuccess: () => {
      message.success("뉴스 동기화 요청 완료");
      void qc.invalidateQueries({ queryKey: queryKeys.admin.news(ex, symbol) });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  return (
    <AdminPageShell title="뉴스관리" description="news sync · get · failures">
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Form
          layout="inline"
          initialValues={{ exchange_code: ex, symbol, query: symbol }}
          onFinish={(v) => {
            setEx(v.exchange_code);
            setSymbol(v.symbol);
            sync.mutate(v);
          }}
        >
          <Form.Item name="exchange_code" rules={[{ required: true }]}>
            <Input placeholder="exchange" style={{ width: 100 }} />
          </Form.Item>
          <Form.Item name="symbol" rules={[{ required: true }]}>
            <Input placeholder="symbol" style={{ width: 120 }} />
          </Form.Item>
          <Form.Item name="query" rules={[{ required: true }]}>
            <Input placeholder="query" style={{ width: 160 }} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={sync.isPending}>
            동기화(POST /news/sync)
          </Button>
          <Button
            onClick={() => {
              void news.refetch();
            }}
          >
            조회
          </Button>
        </Form>

        <AdminDataTable
          title={`GET /news/${ex}/${symbol}`}
          loading={news.isLoading}
          error={news.error ? toApiError(news.error) : null}
          rowKey={(r) => cell(r.article_id ?? r.id ?? JSON.stringify(r))}
          columns={[
            { title: "title", dataIndex: "title", ellipsis: true },
            { title: "symbol", dataIndex: "symbol" },
            { title: "published", dataIndex: "published_at" },
          ]}
          dataSource={extractRows(news.data)}
        />

        <AdminJsonCard
          title="GET /news/failures"
          loading={failures.isLoading}
          error={failures.error ? toApiError(failures.error) : null}
          data={failures.data}
        />
      </Space>
    </AdminPageShell>
  );
}
