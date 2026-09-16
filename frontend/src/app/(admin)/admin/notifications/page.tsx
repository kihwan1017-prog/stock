"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Space, Table, Tag, Typography } from "antd";
import Link from "next/link";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { NOTIFICATION_EVENT_CATALOG } from "@/features/admin/notifications/opsCatalog";
import { MessageTemplatesPanel } from "@/features/admin/notifications/MessageTemplatesPanel";
import { TradingAlertPreferencesPanel } from "@/features/admin/notifications/TradingAlertPreferencesPanel";
import { adminRoutes } from "@/config/routes";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminNotificationsPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();

  const status = useQuery({
    queryKey: queryKeys.admin.notificationStatus(),
    queryFn: adminApi.getNotificationStatus,
  });

  const test = useMutation({
    mutationFn: adminApi.testNotification,
    onSuccess: () => {
      message.success("알림 테스트 전송 요청 완료");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.notificationStatus(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  return (
    <AdminPageShell
      title="알림 관리"
      description="자동매매에서 받을 알림을 선택합니다. 알림을 꺼도 자동매매와 분석 기능은 계속 실행됩니다."
      extra={
        <Space wrap>
          <Button
            type="primary"
            loading={test.isPending}
            onClick={() => test.mutate(undefined)}
          >
            테스트 전송
          </Button>
          <Link href={adminRoutes.telegram}>Telegram 운영</Link>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          알림 설정은 수신(Telegram 등)만 제어합니다. EVENT_TYPE·자동매매·AI·후보
          분석 로직은 그대로 동작합니다.
        </Typography.Paragraph>

        <TradingAlertPreferencesPanel />

        <MessageTemplatesPanel />

        <AdminJsonCard
          title="GET /notification/status"
          loading={status.isLoading}
          error={status.error ? toApiError(status.error) : null}
          data={status.data}
        />

        <Table
          size="small"
          pagination={false}
          rowKey={(row) => row.id}
          dataSource={NOTIFICATION_EVENT_CATALOG}
          title={() => "알림 이벤트 카탈로그"}
          columns={[
            { title: "이벤트", dataIndex: "label", width: 140 },
            { title: "설명", dataIndex: "description" },
            {
              title: "지원",
              dataIndex: "support",
              width: 110,
              render: (v: string) => (
                <Tag
                  color={
                    v === "live"
                      ? "success"
                      : v === "partial"
                        ? "processing"
                        : "default"
                  }
                >
                  {v}
                </Tag>
              ),
            },
          ]}
        />
      </Space>
    </AdminPageShell>
  );
}
