"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Row,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { SettingsEditor } from "@/features/admin/components/SettingsEditor";
import {
  NOTIFICATION_EVENT_CATALOG,
  TELEGRAM_OPS_COMMAND_CATALOG,
} from "@/features/admin/notifications/opsCatalog";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { adminRoutes } from "@/config/routes";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminTelegramPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const notificationQuery = useQuery({
    queryKey: queryKeys.admin.notificationStatus(),
    queryFn: adminApi.getNotificationStatus,
  });

  const testNotification = useMutation({
    mutationFn: () =>
      adminApi.testNotification({
        title: "Telegram 테스트",
        message: "Admin Telegram 페이지에서 보낸 테스트 알림입니다.",
        detail: { source: "admin.telegram", discord: false },
      }),
    onSuccess: async () => {
      message.success("Telegram 등 활성 채널로 테스트 전송 요청");
      await queryClient.invalidateQueries({
        queryKey: queryKeys.admin.notificationStatus(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const notify = asRecord(notificationQuery.data);
  const channels = extractRows(notify?.channels ?? notificationQuery.data);
  const telegramChannel = channels.find((row) => {
    const name = String(row.channel ?? row.name ?? row.type ?? "").toUpperCase();
    return name.includes("TELEGRAM");
  });

  return (
    <AdminPageShell
      title="Telegram 운영"
      description="Telegram Bot · 알림 이벤트 · 운영 명령 (Discord 제외)"
      extra={
        <Space wrap>
          <Button
            type="primary"
            loading={testNotification.isPending}
            onClick={() => testNotification.mutate()}
          >
            알림 테스트
          </Button>
          <Link href={adminRoutes.notifications}>알림 관리</Link>
          <Link href={adminRoutes.ollama}>Ollama</Link>
          <Link href={adminRoutes.envSettings}>환경설정</Link>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          title="Discord는 이 화면에서 다루지 않습니다"
          description="Telegram·알림 이벤트·운영 명령만 표시합니다. Ollama는 전용 관리 페이지를 사용하세요."
        />

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={24}>
            <Card
              size="small"
              title="Telegram Bot 상태"
              loading={notificationQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /notification/status
                </Typography.Text>
              }
            >
              {notificationQuery.error ? (
                <Alert
                  type="error"
                  showIcon
                  title={toApiError(notificationQuery.error).message}
                />
              ) : telegramChannel ? (
                <Space wrap>
                  <Tag color="blue">TELEGRAM</Tag>
                  {Object.entries(telegramChannel)
                    .filter(([key]) => key !== "channel")
                    .slice(0, 6)
                    .map(([key, value]) => (
                      <Typography.Text key={key}>
                        {key}: {cell(value)}
                      </Typography.Text>
                    ))}
                </Space>
              ) : (
                <Typography.Text type="secondary">
                  TELEGRAM 채널 정보가 없습니다. 환경설정에서
                  telegram_enabled / bot_token / chat_id를 확인하세요.
                </Typography.Text>
              )}
            </Card>
          </Col>
        </Row>

        <Card
          size="small"
          title="Telegram Chat ID · Bot 설정"
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              settings category=environment (telegram_*)
            </Typography.Text>
          }
        >
          <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
            Bot Token · Chat ID · Enable · Ops Polling · Notification Level ·
            Allowed Chat IDs는 환경 설정 카탈로그로 관리합니다. (STEP54)
          </Typography.Paragraph>
          <SettingsEditor category="environment" />
        </Card>

        <Card size="small" title="알림 이벤트">
          <Table
            size="small"
            pagination={false}
            rowKey={(row) => row.id}
            dataSource={NOTIFICATION_EVENT_CATALOG}
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
              {
                title: "관련",
                dataIndex: "related",
                render: (v: string[] | undefined) =>
                  v?.length ? (
                    <Typography.Text style={{ fontSize: 12 }}>
                      {v.join(" · ")}
                    </Typography.Text>
                  ) : (
                    "-"
                  ),
              },
            ]}
          />
          <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
            Publisher → NotificationService → TelegramSender. 구독 CRUD API는
            없습니다. Enable/Level로 필터합니다.
          </Typography.Paragraph>
        </Card>

        <Card size="small" title="운영 명령 (Telegram)">
          <Alert
            type="success"
            showIcon
            style={{ marginBottom: 12 }}
            title="STEP54 Bot 명령 활성"
            description="Polling(TELEGRAM_OPS_ENABLED) 또는 POST /api/v1/telegram/webhook · Admin 테스트 POST /api/v1/telegram/commands/test"
          />
          <Table
            size="small"
            pagination={false}
            rowKey={(row) => row.command}
            dataSource={TELEGRAM_OPS_COMMAND_CATALOG}
            columns={[
              {
                title: "명령",
                dataIndex: "command",
                width: 120,
                render: (v: string) => (
                  <Typography.Text code>{v}</Typography.Text>
                ),
              },
              { title: "기능", dataIndex: "label", width: 120 },
              { title: "설명", dataIndex: "description" },
              {
                title: "지원",
                dataIndex: "support",
                width: 80,
                render: (v: string) => (
                  <Tag color={v === "live" ? "success" : "default"}>{v}</Tag>
                ),
              },
              {
                title: "REST 힌트",
                dataIndex: "restHints",
                render: (v: string[]) => (
                  <Typography.Text style={{ fontSize: 12 }}>
                    {v.join(" · ")}
                  </Typography.Text>
                ),
              },
            ]}
          />
        </Card>

        <AdminJsonCard
          title="GET /notification/status (raw)"
          loading={notificationQuery.isLoading}
          error={
            notificationQuery.error
              ? toApiError(notificationQuery.error)
              : null
          }
          data={notificationQuery.data}
        />
      </Space>
    </AdminPageShell>
  );
}
