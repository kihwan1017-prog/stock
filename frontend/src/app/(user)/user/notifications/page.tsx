"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  Row,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";

import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { NOTIFICATION_EVENT_CATALOG } from "@/features/admin/notifications/opsCatalog";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import * as userApi from "@/features/user/api/userApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";

function channelEnabled(row: Record<string, unknown>): boolean {
  const value = row.enabled ?? row.is_enabled ?? row.active;
  if (typeof value === "boolean") return value;
  if (typeof value === "string") {
    return ["true", "1", "yes", "enabled"].includes(value.toLowerCase());
  }
  return Boolean(value);
}

export default function UserNotificationsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const statusQuery = useQuery({
    queryKey: queryKeys.user.notificationStatus(),
    queryFn: userApi.getNotificationStatus,
  });

  const testNotification = useMutation({
    mutationFn: (body: { title: string; message: string }) =>
      userApi.testNotification(body),
    onSuccess: async () => {
      message.success("테스트 알림 전송 요청 완료");
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.notificationStatus(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const status = asRecord(statusQuery.data);
  const channels = extractRows(status?.channels ?? statusQuery.data).filter(
    (row) => {
      // Discord UI 제외 (STEP50)
      const name = String(row.channel ?? row.name ?? row.type ?? "").toUpperCase();
      return !name.includes("DISCORD");
    },
  );

  return (
    <UserPageShell
      title="알림"
      description="채널 상태 · 이벤트 카탈로그 · 테스트 (Discord 제외)"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <UnimplementedNotice
          feature="알림 인박스·읽음·구독"
          reason="사용자 알림함 API가 없습니다. 채널 상태 조회와 테스트 전송만 가능합니다."
          relatedApis={[
            "GET /api/v1/notification/status",
            "POST /api/v1/notification/test",
            "TODO: GET /api/v1/notification/inbox",
          ]}
        />

        {statusQuery.error ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(statusQuery.error).message}
          />
        ) : null}

        <Card
          title="알림 채널 상태"
          size="small"
          loading={statusQuery.isLoading}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              GET /notification/status
            </Typography.Text>
          }
        >
          {channels.length === 0 ? (
            <Typography.Text type="secondary">
              등록된 채널 정보가 없습니다
            </Typography.Text>
          ) : (
            <Row gutter={[12, 12]}>
              {channels.map((channel, index) => {
                const name = cell(
                  channel.channel ??
                    channel.name ??
                    channel.type ??
                    `channel-${index}`,
                );
                const enabled = channelEnabled(channel);
                return (
                  <Col xs={24} sm={12} md={8} key={`${name}-${index}`}>
                    <Card size="small" type="inner" title={name}>
                      <Space orientation="vertical" size={4}>
                        <Tag color={enabled ? "success" : "default"}>
                          {enabled ? "enabled" : "disabled"}
                        </Tag>
                        <Descriptions column={1} size="small">
                          {Object.entries(channel)
                            .filter(
                              ([key]) =>
                                ![
                                  "channel",
                                  "name",
                                  "type",
                                  "enabled",
                                  "is_enabled",
                                  "active",
                                ].includes(key),
                            )
                            .slice(0, 4)
                            .map(([key, value]) => (
                              <Descriptions.Item key={key} label={key}>
                                {cell(value)}
                              </Descriptions.Item>
                            ))}
                        </Descriptions>
                      </Space>
                    </Card>
                  </Col>
                );
              })}
            </Row>
          )}
        </Card>

        <Card size="small" title="알림 이벤트 (예정 포함)">
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
            ]}
          />
        </Card>

        <Card
          title="테스트 전송"
          size="small"
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              POST /notification/test
            </Typography.Text>
          }
        >
          <Form
            layout="vertical"
            initialValues={{
              title: "Stock Platform 테스트 알림",
              message: "User Web 알림 연결 테스트입니다.",
            }}
            onFinish={(values: { title: string; message: string }) => {
              testNotification.mutate(values);
            }}
            style={{ maxWidth: 480 }}
          >
            <Form.Item
              name="title"
              label="제목"
              rules={[{ required: true, message: "제목을 입력하세요" }]}
            >
              <Input maxLength={200} />
            </Form.Item>
            <Form.Item
              name="message"
              label="내용"
              rules={[{ required: true, message: "내용을 입력하세요" }]}
            >
              <Input.TextArea rows={3} maxLength={1000} />
            </Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={testNotification.isPending}
            >
              테스트 전송
            </Button>
          </Form>
          {testNotification.data ? (
            <Alert
              style={{ marginTop: 12 }}
              type="info"
              showIcon
              title="전송 결과"
              description={
                <Typography.Paragraph
                  copyable
                  style={{ marginBottom: 0, fontSize: 12 }}
                >
                  {JSON.stringify(testNotification.data)}
                </Typography.Paragraph>
              }
            />
          ) : null}
        </Card>
      </Space>
    </UserPageShell>
  );
}
