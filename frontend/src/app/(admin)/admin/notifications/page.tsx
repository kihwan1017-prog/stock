"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Space, Table, Tag, Typography } from "antd";
import Link from "next/link";

import * as adminApi from "@/features/admin/api/adminApi";
import {
  AdminJsonCard,
  UnimplementedApiPanel,
} from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { NOTIFICATION_EVENT_CATALOG } from "@/features/admin/notifications/opsCatalog";
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
      description="notification/status · notification/test — Telegram 운영은 Telegram 페이지"
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
          Discord 채널 UI는 다루지 않습니다. Telegram Bot·이벤트·운영 명령은{" "}
          <Link href={adminRoutes.telegram}>Telegram 운영</Link>을 사용하세요.
        </Typography.Paragraph>

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

        <UnimplementedApiPanel
          feature="알림 채널 설정 CRUD"
          reason="알림 채널 등록/수정/삭제 API가 Backend에 없습니다. 상태 조회·테스트만 가능합니다."
          expectedApis={[
            "GET/POST/PUT/DELETE /api/v1/notification/channels",
          ]}
          relatedApis={[
            "GET /api/v1/notification/status",
            "POST /api/v1/notification/test",
            "/admin/telegram",
          ]}
        />
      </Space>
    </AdminPageShell>
  );
}
