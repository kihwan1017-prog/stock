"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type PrefItem = {
  key: string;
  group: string;
  label: string;
  description: string;
  enabled: boolean;
};

const GROUP_ORDER = ["UPBIT", "KIWOOM", "SYSTEM"] as const;
const GROUP_LABEL: Record<string, string> = {
  UPBIT: "UPBIT 자동매매",
  KIWOOM: "KIWOOM 자동매매",
  SYSTEM: "시스템",
};

export function TradingAlertPreferencesPanel() {
  const qc = useQueryClient();
  const prefs = useQuery({
    queryKey: queryKeys.admin.tradingAlertPreferences(),
    queryFn: adminApi.getTradingAlertPreferences,
  });
  const history = useQuery({
    queryKey: queryKeys.admin.tradingAlertHistory(),
    queryFn: () => adminApi.getTradingAlertHistory({ limit: 40 }),
  });

  const patch = useMutation({
    mutationFn: (body: { preferences: Record<string, boolean> }) =>
      adminApi.patchTradingAlertPreferences(body),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.tradingAlertPreferences(),
      });
    },
  });

  const items = (prefs.data?.items ?? []) as PrefItem[];
  const notice =
    prefs.data?.delivery_only_notice ??
    "알림 수신 여부만 변경하며 자동매매 동작에는 영향을 주지 않습니다.";

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert type="info" showIcon title={notice} />
      {prefs.error ? (
        <Alert type="error" title={toApiError(prefs.error).message} />
      ) : null}
      {GROUP_ORDER.map((group) => {
        const rows = items.filter((i) => i.group === group);
        if (!rows.length && prefs.isLoading) {
          return null;
        }
        return (
          <Card
            key={group}
            size="small"
            title={GROUP_LABEL[group] ?? group}
            loading={prefs.isLoading}
          >
            <Space orientation="vertical" style={{ width: "100%" }} size={8}>
              {rows.map((row) => (
                <div
                  key={row.key}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: 12,
                    alignItems: "flex-start",
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <Typography.Text strong>{row.label}</Typography.Text>
                    <Typography.Paragraph
                      type="secondary"
                      style={{ marginBottom: 0, marginTop: 2 }}
                    >
                      {row.description}
                    </Typography.Paragraph>
                  </div>
                  <Switch
                    checked={row.enabled}
                    loading={patch.isPending}
                    onChange={(checked) =>
                      patch.mutate({
                        preferences: { [row.key]: checked },
                      })
                    }
                  />
                </div>
              ))}
              {!rows.length && !prefs.isLoading ? (
                <Typography.Text type="secondary">설정 없음</Typography.Text>
              ) : null}
            </Space>
          </Card>
        );
      })}

      <Card size="small" title="최근 알림 이력 (프로세스 로컬)">
        <Table
          size="small"
          loading={history.isLoading}
          rowKey={(r) => `${r.created_at}-${r.event_type}-${r.title}`}
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
              </Typography.Paragraph>
            ),
          }}
        />
      </Card>
    </Space>
  );
}
