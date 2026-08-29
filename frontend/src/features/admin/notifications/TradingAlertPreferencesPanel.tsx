"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Segmented,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import {
  type ImportanceFilter,
  type PrefItem,
  type SourceFilter,
  SOURCE_BADGE,
  UX_GROUP_LABEL,
  UX_GROUP_ORDER,
  dirtyPreferences,
  enabledMapFromItems,
  filterPreferenceItems,
  groupItemsByUx,
  isDirty,
  resolveUxMeta,
} from "@/features/admin/notifications/alertPreferenceUx";

type PrefsResponse = {
  items: PrefItem[];
  groups?: string[];
  delivery_only_notice?: string;
};

export function TradingAlertPreferencesPanel() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const prefs = useQuery({
    queryKey: queryKeys.admin.tradingAlertPreferences(),
    queryFn: adminApi.getTradingAlertPreferences,
  });
  const history = useQuery({
    queryKey: queryKeys.admin.tradingAlertHistory(),
    queryFn: () => adminApi.getTradingAlertHistory({ limit: 40 }),
  });

  const serverItems = (prefs.data?.items ?? []) as PrefItem[];
  const [baseline, setBaseline] = useState<Record<string, boolean>>({});
  const [draft, setDraft] = useState<Record<string, boolean>>({});
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("ALL");
  const [importanceFilter, setImportanceFilter] =
    useState<ImportanceFilter>("ALL");
  const dirtyRef = useRef(false);

  const dirty = isDirty(draft, baseline);
  dirtyRef.current = dirty;

  // 서버 로드/refetch — dirty 중이면 draft 유지 (원복 방지)
  useEffect(() => {
    if (!serverItems.length) return;
    if (dirtyRef.current) return;
    const next = enabledMapFromItems(serverItems);
    setBaseline(next);
    setDraft(next);
  }, [prefs.dataUpdatedAt, serverItems]);

  const dirtyPayload = useMemo(
    () => dirtyPreferences(draft, baseline),
    [draft, baseline],
  );

  const patch = useMutation({
    mutationFn: (body: { preferences: Record<string, boolean> }) =>
      adminApi.patchTradingAlertPreferences(body) as Promise<PrefsResponse>,
    onSuccess: (data) => {
      const items = (data?.items ?? []) as PrefItem[];
      const next = enabledMapFromItems(items);
      // response 가 canonical SoT — refetch race 로 덮어쓰지 않도록 즉시 반영
      qc.setQueryData(queryKeys.admin.tradingAlertPreferences(), {
        ...(prefs.data ?? {}),
        ...data,
        items,
      });
      setBaseline(next);
      setDraft(next);
      message.success("알림 설정을 저장했습니다.");
    },
    onError: (e) => {
      message.error(
        toApiError(e).message || "알림 설정을 저장하지 못했습니다.",
      );
    },
  });

  const notice =
    prefs.data?.delivery_only_notice ??
    "알림을 꺼도 자동매매와 분석 기능은 계속 실행됩니다.";

  const filtered = filterPreferenceItems(
    serverItems,
    sourceFilter,
    importanceFilter,
  );
  const grouped = groupItemsByUx(filtered);

  const onToggle = (key: string, checked: boolean) => {
    setDraft((prev) => ({ ...prev, [key]: checked }));
  };

  const onSave = () => {
    if (!dirty || patch.isPending) return;
    const payload = dirtyPreferences(draft, baseline);
    if (!Object.keys(payload).length) return;
    patch.mutate({ preferences: payload });
  };

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="자동매매에서 받을 알림을 선택합니다. 알림을 꺼도 자동매매와 분석 기능은 계속 실행됩니다."
        description={notice}
      />
      {prefs.error ? (
        <Alert
          type="error"
          showIcon
          title="알림 설정을 불러오지 못했습니다."
          description={toApiError(prefs.error).message}
        />
      ) : null}
      {dirty ? (
        <Alert
          type="warning"
          showIcon
          title="저장하지 않은 변경사항이 있습니다."
        />
      ) : null}

      <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
        <Space wrap>
          <Segmented
            value={sourceFilter}
            onChange={(v) => setSourceFilter(v as SourceFilter)}
            options={[
              { label: "전체", value: "ALL" },
              { label: "업비트", value: "UPBIT" },
              { label: "키움", value: "KIWOOM" },
              { label: "시스템", value: "SYSTEM" },
            ]}
          />
          <Segmented
            value={importanceFilter}
            onChange={(v) => setImportanceFilter(v as ImportanceFilter)}
            options={[
              { label: "전체", value: "ALL" },
              { label: "중요", value: "IMPORTANT" },
              { label: "정보", value: "INFO" },
            ]}
          />
        </Space>
        <Button
          type="primary"
          disabled={!dirty || patch.isPending}
          loading={patch.isPending}
          onClick={onSave}
        >
          {patch.isPending ? "저장 중..." : "저장"}
        </Button>
      </Space>

      {prefs.isLoading && !serverItems.length ? (
        <Card loading />
      ) : null}

      {!prefs.isLoading && !serverItems.length ? (
        <Alert type="info" showIcon title="설정할 수 있는 알림이 없습니다." />
      ) : null}

      {UX_GROUP_ORDER.map((groupId) => {
        const rows = grouped[groupId];
        if (!rows.length) return null;
        return (
          <Card
            key={groupId}
            size="small"
            title={UX_GROUP_LABEL[groupId]}
          >
            <Space orientation="vertical" style={{ width: "100%" }} size={12}>
              {rows.map((row) => {
                const meta = resolveUxMeta(row);
                const checked = Boolean(
                  draft[row.key] ?? baseline[row.key] ?? row.enabled,
                );
                return (
                  <div
                    key={row.key}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 12,
                      alignItems: "flex-start",
                    }}
                  >
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <Space wrap size={6}>
                        <Tag>
                          {SOURCE_BADGE[meta.source] ?? meta.source}
                        </Tag>
                        <Typography.Text strong>
                          {meta.userLabel}
                        </Typography.Text>
                        {meta.recommended ? (
                          <Tag color="blue">권장</Tag>
                        ) : null}
                        <Tooltip title={`preference_key=${row.key}`}>
                          <Typography.Text
                            type="secondary"
                            style={{ fontSize: 12 }}
                          >
                            상세
                          </Typography.Text>
                        </Tooltip>
                      </Space>
                      <Typography.Paragraph
                        type="secondary"
                        style={{ marginBottom: 0, marginTop: 4 }}
                      >
                        {meta.userDescription}
                      </Typography.Paragraph>
                    </div>
                    <Switch
                      checked={checked}
                      disabled={patch.isPending}
                      onChange={(v) => onToggle(row.key, v)}
                    />
                  </div>
                );
              })}
            </Space>
          </Card>
        );
      })}

      {dirty ? (
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <Button
            type="primary"
            disabled={patch.isPending}
            loading={patch.isPending}
            onClick={onSave}
          >
            {patch.isPending
              ? "저장 중..."
              : `저장 (${Object.keys(dirtyPayload).length})`}
          </Button>
        </div>
      ) : null}

      <Card size="small" title="최근 알림 이력 (프로세스 로컬)">
        <Table
          size="small"
          loading={history.isLoading}
          rowKey={(r) =>
            `${r.created_at}-${r.event_type}-${r.title}-${r.preference_key ?? ""}`
          }
          pagination={false}
          dataSource={history.data?.items ?? []}
          locale={{ emptyText: "이력이 없습니다" }}
          columns={[
            {
              title: "구분",
              dataIndex: "category",
              width: 90,
              render: (v: string) => <Tag>{v}</Tag>,
            },
            { title: "제목", dataIndex: "title", ellipsis: true },
            {
              title: "상태",
              dataIndex: "status",
              width: 80,
              render: (v: string) => (
                <Tag color={v === "SENT" ? "success" : "error"}>{v}</Tag>
              ),
            },
            {
              title: "시간",
              dataIndex: "created_at",
              width: 180,
              ellipsis: true,
            },
          ]}
          expandable={{
            expandedRowRender: (row) => (
              <Typography.Paragraph
                style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}
              >
                {row.message || "-"}
                {row.preference_key ? (
                  <>
                    {"\n"}
                    <Typography.Text type="secondary">
                      preference_key={row.preference_key}
                    </Typography.Text>
                  </>
                ) : null}
              </Typography.Paragraph>
            ),
          }}
        />
      </Card>
    </Space>
  );
}
