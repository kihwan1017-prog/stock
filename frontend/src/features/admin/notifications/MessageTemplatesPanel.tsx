"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Input,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type TemplateRow = {
  message_template_id: number;
  event_type: string;
  channel: string;
  locale: string;
  severity: string;
  title_template: string;
  body_template: string;
  short_body_template?: string | null;
  enabled: boolean;
  version: number;
};

function asItems(data: unknown): TemplateRow[] {
  if (!data || typeof data !== "object") return [];
  const items = (data as { items?: unknown }).items;
  return Array.isArray(items) ? (items as TemplateRow[]) : [];
}

export function MessageTemplatesPanel() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [channel, setChannel] = useState("TELEGRAM");
  const [selected, setSelected] = useState<TemplateRow | null>(null);
  const [titleTpl, setTitleTpl] = useState("");
  const [bodyTpl, setBodyTpl] = useState("");
  const [previewText, setPreviewText] = useState<string>("");

  const list = useQuery({
    queryKey: queryKeys.admin.notificationTemplates({ channel }),
    queryFn: () => adminApi.listNotificationTemplates({ channel }),
  });

  const logs = useQuery({
    queryKey: queryKeys.admin.notificationDeliveryLogs({ limit: 30 }),
    queryFn: () => adminApi.listNotificationDeliveryLogs({ limit: 30 }),
  });

  const seed = useMutation({
    mutationFn: adminApi.seedNotificationTemplates,
    onSuccess: () => {
      message.success("기본 한글 템플릿 seed 완료");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.notificationTemplates({ channel }),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const save = useMutation({
    mutationFn: () =>
      adminApi.upsertNotificationTemplate({
        event_type: selected?.event_type || "ORDER_FILLED",
        channel,
        title_template: titleTpl,
        body_template: bodyTpl,
        short_body_template: selected?.short_body_template || undefined,
        enabled: selected?.enabled ?? true,
        version: selected?.version,
      }),
    onSuccess: () => {
      message.success("템플릿 저장됨");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.notificationTemplates({ channel }),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const preview = useMutation({
    mutationFn: () =>
      adminApi.previewNotificationTemplate({
        event_type: selected?.event_type || "ORDER_FILLED",
        title_template: titleTpl,
        body_template: bodyTpl,
      }),
    onSuccess: (data) => {
      const d = data as { title?: string; body?: string };
      setPreviewText(`${d.title || ""}\n\n${d.body || ""}`);
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      adminApi.setNotificationTemplateEnabled(id, enabled),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.notificationTemplates({ channel }),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const rows = useMemo(() => asItems(list.data), [list.data]);
  const logItems = useMemo(() => {
    const raw = logs.data as { items?: unknown[] } | undefined;
    return Array.isArray(raw?.items) ? raw!.items! : [];
  }, [logs.data]);

  return (
    <Card title="한글 메시지 템플릿" size="small">
      <Space orientation="vertical" size={12} style={{ width: "100%" }}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          정형 이벤트는 LLM 없이 DB/내장 템플릿으로 즉시 한글 렌더링합니다.
          Toss 송신기는 현재 미구현이며 템플릿·short body만 준비되어 있습니다.
        </Typography.Paragraph>
        <Space wrap>
          <Select
            value={channel}
            style={{ width: 140 }}
            options={[
              { value: "TELEGRAM", label: "TELEGRAM" },
              { value: "TOSS", label: "TOSS" },
              { value: "COMMON", label: "COMMON" },
            ]}
            onChange={setChannel}
          />
          <Button loading={seed.isPending} onClick={() => seed.mutate()}>
            기본 템플릿 Seed
          </Button>
          <Button
            type="primary"
            loading={preview.isPending}
            disabled={!titleTpl || !bodyTpl}
            onClick={() => preview.mutate()}
          >
            Preview
          </Button>
          <Button
            loading={save.isPending}
            disabled={!selected || !titleTpl || !bodyTpl}
            onClick={() => save.mutate()}
          >
            저장
          </Button>
        </Space>

        <Tabs
          items={[
            {
              key: "templates",
              label: "템플릿 목록",
              children: (
                <Table
                  size="small"
                  loading={list.isLoading}
                  rowKey={(r) => String(r.message_template_id)}
                  dataSource={rows}
                  pagination={{ pageSize: 8 }}
                  onRow={(row) => ({
                    onClick: () => {
                      setSelected(row);
                      setTitleTpl(row.title_template);
                      setBodyTpl(row.body_template);
                    },
                  })}
                  columns={[
                    { title: "이벤트", dataIndex: "event_type", width: 220 },
                    { title: "채널", dataIndex: "channel", width: 100 },
                    { title: "버전", dataIndex: "version", width: 70 },
                    {
                      title: "사용",
                      dataIndex: "enabled",
                      width: 80,
                      render: (v: boolean, row) => (
                        <Switch
                          size="small"
                          checked={v}
                          onChange={(checked) =>
                            toggle.mutate({
                              id: row.message_template_id,
                              enabled: checked,
                            })
                          }
                        />
                      ),
                    },
                    {
                      title: "제목",
                      dataIndex: "title_template",
                      ellipsis: true,
                    },
                  ]}
                />
              ),
            },
            {
              key: "edit",
              label: "편집 / Preview",
              children: (
                <Space orientation="vertical" style={{ width: "100%" }} size={8}>
                  <Typography.Text type="secondary">
                    {selected
                      ? `${selected.event_type} · v${selected.version}`
                      : "목록에서 템플릿을 선택하세요"}
                  </Typography.Text>
                  <Input.TextArea
                    rows={2}
                    value={titleTpl}
                    onChange={(e) => setTitleTpl(e.target.value)}
                    placeholder="title_template"
                  />
                  <Input.TextArea
                    rows={8}
                    value={bodyTpl}
                    onChange={(e) => setBodyTpl(e.target.value)}
                    placeholder="body_template"
                  />
                  {previewText ? (
                    <Card size="small" title="Preview (ko-KR)">
                      <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                        {previewText}
                      </pre>
                    </Card>
                  ) : null}
                </Space>
              ),
            },
            {
              key: "history",
              label: "전송 이력 / 원본 JSON",
              children: (
                <Table
                  size="small"
                  loading={logs.isLoading}
                  rowKey={(r) => String((r as { id?: number }).id)}
                  dataSource={logItems as object[]}
                  pagination={{ pageSize: 8 }}
                  expandable={{
                    expandedRowRender: (row) => (
                      <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                        {JSON.stringify(
                          (row as { original_payload_json?: unknown })
                            .original_payload_json,
                          null,
                          2,
                        )}
                      </pre>
                    ),
                  }}
                  columns={[
                    { title: "이벤트", dataIndex: "event_type", width: 180 },
                    { title: "채널", dataIndex: "channel", width: 90 },
                    { title: "상태", dataIndex: "status", width: 90 },
                    {
                      title: "제목",
                      dataIndex: "rendered_title",
                      ellipsis: true,
                    },
                    {
                      title: "시각",
                      dataIndex: "created_at",
                      width: 180,
                    },
                  ]}
                />
              ),
            },
          ]}
        />
      </Space>
    </Card>
  );
}
