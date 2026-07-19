"use client";

import { useQuery } from "@tanstack/react-query";
import { Button, Card, Input, Space, Typography } from "antd";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { openApiDocsUrl } from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type DocRow = {
  slug?: string;
  title?: string;
  category?: string;
  path?: string;
  size_bytes?: number;
};

export default function AdminDocsPage() {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const docsUrl = openApiDocsUrl();

  const list = useQuery({
    queryKey: queryKeys.admin.docsList(),
    queryFn: adminApi.listDocs,
  });
  const detail = useQuery({
    queryKey: queryKeys.admin.docDetail(selectedSlug ?? ""),
    queryFn: () => adminApi.getDoc(selectedSlug!),
    enabled: Boolean(selectedSlug),
  });

  const rows = useMemo(() => {
    const all = extractRows(
      (list.data as { items?: unknown[] } | undefined)?.items ?? list.data,
    ) as DocRow[];
    const q = filter.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (r) =>
        cell(r.title).toLowerCase().includes(q) ||
        cell(r.slug).toLowerCase().includes(q) ||
        cell(r.category).toLowerCase().includes(q),
    );
  }, [list.data, filter]);

  const content = (detail.data as { content?: string; title?: string } | undefined)
    ?.content;

  return (
    <AdminPageShell
      title="문서 CMS"
      description="읽기 전용 — docs/manual · deployment · trading · backend Markdown"
      extra={
        <Button type="primary" href={docsUrl} target="_blank" rel="noreferrer">
          OpenAPI Swagger
        </Button>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card size="small" title="안내">
          <Typography.Paragraph style={{ marginBottom: 0 }}>
            문서는 저장소 Markdown을 API로 제공합니다. 업로드/버전 CRUD는 의도적으로
            없습니다. 수정은 Git으로 <Typography.Text code>docs/</Typography.Text> 에
            커밋하세요.
          </Typography.Paragraph>
        </Card>

        <Input.Search
          allowClear
          placeholder="제목·slug·카테고리 검색"
          onSearch={setFilter}
          onChange={(e) => setFilter(e.target.value)}
          style={{ maxWidth: 360 }}
        />

        <AdminDataTable
          title="GET /docs"
          loading={list.isLoading}
          error={list.error ? toApiError(list.error) : null}
          rowKey={(r) => cell(r.slug ?? JSON.stringify(r))}
          columns={[
            { title: "category", dataIndex: "category", width: 120 },
            { title: "title", dataIndex: "title" },
            { title: "slug", dataIndex: "slug" },
            { title: "bytes", dataIndex: "size_bytes", width: 90 },
            {
              title: "열기",
              width: 90,
              render: (_, row) => (
                <Button
                  size="small"
                  type="link"
                  onClick={() => setSelectedSlug(String(row.slug))}
                >
                  보기
                </Button>
              ),
            },
          ]}
          dataSource={rows}
          pagination={{ pageSize: 20 }}
        />

        {selectedSlug ? (
          <Card
            size="small"
            title={(detail.data as { title?: string } | undefined)?.title ?? selectedSlug}
            extra={
              <Button size="small" onClick={() => setSelectedSlug(null)}>
                닫기
              </Button>
            }
          >
            {detail.isLoading ? (
              <Typography.Text type="secondary">불러오는 중…</Typography.Text>
            ) : detail.error ? (
              <Typography.Text type="danger">
                {toApiError(detail.error).message}
              </Typography.Text>
            ) : (
              <Typography.Paragraph>
                <pre
                  style={{
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    margin: 0,
                    maxHeight: 480,
                    overflow: "auto",
                    fontSize: 13,
                  }}
                >
                  {content ?? ""}
                </pre>
              </Typography.Paragraph>
            )}
          </Card>
        ) : null}

        {detail.data ? (
          <AdminJsonCard title="메타" data={{
            slug: (detail.data as { slug?: string }).slug,
            path: (detail.data as { path?: string }).path,
            category: (detail.data as { category?: string }).category,
          }} />
        ) : null}
      </Space>
    </AdminPageShell>
  );
}
