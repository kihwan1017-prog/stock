"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Badge,
  Button,
  Card,
  Drawer,
  Empty,
  Input,
  Select,
  Skeleton,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import {
  DeleteOutlined,
  StarFilled,
  StarOutlined,
  InboxOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import { useMemo, useState } from "react";

import type {
  NotificationSubscriptionItem,
  UserNotificationFilter,
  UserNotificationItem,
} from "@/features/user/api/userApi";
import * as userApi from "@/features/user/api/userApi";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const SEVERITY_COLOR: Record<string, string> = {
  INFO: "blue",
  SUCCESS: "green",
  WARNING: "orange",
  ERROR: "red",
  CRITICAL: "magenta",
};

export default function UserNotificationsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [eventType, setEventType] = useState<string | undefined>();
  const [severity, setSeverity] = useState<string | undefined>();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [archived, setArchived] = useState(false);
  const [starredOnly, setStarredOnly] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showSubscriptions, setShowSubscriptions] = useState(false);

  const listParams: UserNotificationFilter = useMemo(
    () => ({
      event_type: eventType,
      severity,
      unread_only: unreadOnly || undefined,
      archived,
      starred: starredOnly || undefined,
      keyword: keyword || undefined,
      page,
      page_size: 20,
    }),
    [eventType, severity, unreadOnly, archived, starredOnly, keyword, page],
  );

  const listQuery = useQuery({
    queryKey: queryKeys.user.notifications.list(listParams),
    queryFn: () => userApi.listUserNotifications(listParams),
    refetchInterval: 45_000,
  });

  const unreadQuery = useQuery({
    queryKey: queryKeys.user.notifications.unreadCount(),
    queryFn: () => userApi.getNotificationUnreadCount(),
    refetchInterval: 30_000,
  });

  const detailQuery = useQuery({
    queryKey: queryKeys.user.notifications.detail(selectedId ?? 0),
    queryFn: () => userApi.getUserNotificationDetail(selectedId as number),
    enabled: selectedId != null,
  });

  const subscriptionsQuery = useQuery({
    queryKey: queryKeys.user.notifications.subscriptions(),
    queryFn: () => userApi.listNotificationSubscriptions(),
    enabled: showSubscriptions,
  });

  const invalidate = async (notificationId?: number) => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.user.notifications.list(listParams),
    });
    await queryClient.invalidateQueries({
      queryKey: queryKeys.user.notifications.unreadCount(),
    });
    if (notificationId != null) {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.notifications.detail(notificationId),
      });
    }
  };

  const readMutation = useMutation({
    mutationFn: (id: number) => userApi.markNotificationRead(id),
    onSuccess: async (_d, id) => invalidate(id),
    onError: (e) => message.error(toApiError(e).message),
  });

  const readAllMutation = useMutation({
    mutationFn: () => userApi.readAllNotifications(),
    onSuccess: async (result) => {
      message.success(`읽음 처리 ${result.updated_count}건`);
      await invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const archiveMutation = useMutation({
    mutationFn: async ({
      id,
      archived: next,
    }: {
      id: number;
      archived: boolean;
    }) =>
      next
        ? userApi.archiveNotification(id)
        : userApi.unarchiveNotification(id),
    onSuccess: async (_d, v) => invalidate(v.id),
    onError: (e) => message.error(toApiError(e).message),
  });

  const starMutation = useMutation({
    mutationFn: async ({
      id,
      starred,
    }: {
      id: number;
      starred: boolean;
    }) =>
      starred
        ? userApi.starNotification(id)
        : userApi.unstarNotification(id),
    onSuccess: async (_d, v) => invalidate(v.id),
    onError: (e) => message.error(toApiError(e).message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => userApi.deleteUserNotification(id),
    onSuccess: async (_d, id) => {
      message.success("삭제되었습니다.");
      if (selectedId === id) setSelectedId(null);
      await invalidate(id);
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const subscriptionMutation = useMutation({
    mutationFn: (body: NotificationSubscriptionItem) =>
      userApi.updateNotificationSubscription(body),
    onSuccess: async () => {
      message.success("구독 설정이 저장되었습니다.");
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.notifications.subscriptions(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const openDetail = (item: UserNotificationItem) => {
    setSelectedId(item.notification_id);
    if (!item.is_read) {
      readMutation.mutate(item.notification_id);
    }
  };

  const items = listQuery.data?.items ?? [];
  const total = listQuery.data?.total_count ?? 0;
  const hasNext = listQuery.data?.has_next ?? false;

  return (
    <UserPageShell
      title="알림 센터"
      description="인박스 · 읽음 · 보관 · 구독 (Telegram은 구독 설정 경유)"
      extra={
        <Space wrap>
          <Badge count={unreadQuery.data?.unread_count ?? 0} size="small">
            <Tag>미읽음</Tag>
          </Badge>
          <Button onClick={() => readAllMutation.mutate()} loading={readAllMutation.isPending}>
            전체 읽음
          </Button>
          <Button onClick={() => setShowSubscriptions(true)}>구독 관리</Button>
          <Button
            onClick={() => {
              void listQuery.refetch();
              void unreadQuery.refetch();
            }}
          >
            새로고침
          </Button>
        </Space>
      }
    >
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            allowClear
            placeholder="유형"
            style={{ width: 180 }}
            value={eventType}
            onChange={(v) => {
              setEventType(v);
              setPage(1);
            }}
            options={[
              { value: "AI_ANALYSIS_COMPLETE", label: "AI 추천" },
              { value: "NEWS", label: "뉴스" },
              { value: "DISCLOSURE", label: "공시" },
              { value: "ORDER", label: "주문" },
              { value: "RISK", label: "리스크" },
              { value: "SYSTEM", label: "시스템" },
            ]}
          />
          <Select
            allowClear
            placeholder="심각도"
            style={{ width: 140 }}
            value={severity}
            onChange={(v) => {
              setSeverity(v);
              setPage(1);
            }}
            options={[
              { value: "INFO", label: "INFO" },
              { value: "SUCCESS", label: "SUCCESS" },
              { value: "WARNING", label: "WARNING" },
              { value: "ERROR", label: "ERROR" },
              { value: "CRITICAL", label: "CRITICAL" },
            ]}
          />
          <Button
            type={unreadOnly ? "primary" : "default"}
            onClick={() => {
              setUnreadOnly((p) => !p);
              setPage(1);
            }}
          >
            미읽음만
          </Button>
          <Button
            type={starredOnly ? "primary" : "default"}
            onClick={() => {
              setStarredOnly((p) => !p);
              setPage(1);
            }}
          >
            중요만
          </Button>
          <Button
            type={archived ? "primary" : "default"}
            icon={<InboxOutlined />}
            onClick={() => {
              setArchived((p) => !p);
              setPage(1);
            }}
          >
            보관함
          </Button>
          <Input.Search
            allowClear
            placeholder="검색"
            style={{ width: 220 }}
            value={keywordInput}
            onChange={(e) => setKeywordInput(e.target.value)}
            onSearch={(v) => {
              setKeyword(v.trim());
              setPage(1);
            }}
          />
        </Space>
      </Card>

      {listQuery.isLoading ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : listQuery.isError ? (
        <Alert
          type="error"
          showIcon
          message="알림을 불러오지 못했습니다."
          description={toApiError(listQuery.error).message}
        />
      ) : items.length === 0 ? (
        <Empty description="알림이 없습니다." />
      ) : (
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          {items.map((item) => (
            <Card
              key={item.notification_id}
              size="small"
              hoverable
              onClick={() => openDetail(item)}
              style={{
                opacity: item.is_read ? 0.85 : 1,
                borderLeft: item.is_read
                  ? undefined
                  : "3px solid #1677ff",
              }}
              title={
                <Space wrap>
                  <Typography.Text strong={!item.is_read}>
                    {item.title}
                  </Typography.Text>
                  <Tag color={SEVERITY_COLOR[item.severity] || "default"}>
                    {item.severity}
                  </Tag>
                  <Tag>{item.category || item.event_type}</Tag>
                  {!item.is_read && <Tag color="blue">미읽음</Tag>}
                </Space>
              }
              extra={
                <Space onClick={(e) => e.stopPropagation()}>
                  <Button
                    type="text"
                    icon={
                      item.is_starred ? <StarFilled /> : <StarOutlined />
                    }
                    onClick={() =>
                      starMutation.mutate({
                        id: item.notification_id,
                        starred: !item.is_starred,
                      })
                    }
                  />
                  <Button
                    type="text"
                    icon={<DeleteOutlined />}
                    onClick={() =>
                      deleteMutation.mutate(item.notification_id)
                    }
                  />
                </Space>
              }
            >
              <Typography.Paragraph
                type="secondary"
                ellipsis={{ rows: 2 }}
                style={{ marginBottom: 4 }}
              >
                {item.message}
              </Typography.Paragraph>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {dayjs(item.created_at).format("YYYY-MM-DD HH:mm")}
              </Typography.Text>
            </Card>
          ))}
          <Space>
            <Button
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              이전
            </Button>
            <Typography.Text>
              {page}페이지 · 총 {total}건
            </Typography.Text>
            <Button disabled={!hasNext} onClick={() => setPage((p) => p + 1)}>
              다음
            </Button>
          </Space>
        </Space>
      )}

      <Drawer
        title="알림 상세"
        open={selectedId != null}
        onClose={() => setSelectedId(null)}
        width={480}
        destroyOnClose
      >
        {detailQuery.isLoading ? (
          <Skeleton active />
        ) : detailQuery.data ? (
          <Space direction="vertical" style={{ width: "100%" }} size={12}>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {detailQuery.data.title}
            </Typography.Title>
            <Space wrap>
              <Tag color={SEVERITY_COLOR[detailQuery.data.severity]}>
                {detailQuery.data.severity}
              </Tag>
              <Tag>{detailQuery.data.event_type}</Tag>
            </Space>
            <Typography.Paragraph>{detailQuery.data.message}</Typography.Paragraph>
            <Typography.Text type="secondary">
              {dayjs(detailQuery.data.created_at).format("YYYY-MM-DD HH:mm:ss")}
            </Typography.Text>
            <Space wrap>
              <Button
                onClick={() =>
                  archiveMutation.mutate({
                    id: detailQuery.data.notification_id,
                    archived: !detailQuery.data.is_archived,
                  })
                }
              >
                {detailQuery.data.is_archived ? "보관 해제" : "보관"}
              </Button>
              <Button
                icon={
                  detailQuery.data.is_starred ? (
                    <StarFilled />
                  ) : (
                    <StarOutlined />
                  )
                }
                onClick={() =>
                  starMutation.mutate({
                    id: detailQuery.data.notification_id,
                    starred: !detailQuery.data.is_starred,
                  })
                }
              >
                중요
              </Button>
              <Button
                danger
                onClick={() =>
                  deleteMutation.mutate(detailQuery.data.notification_id)
                }
              >
                삭제
              </Button>
            </Space>
          </Space>
        ) : null}
      </Drawer>

      <Drawer
        title="알림 구독"
        open={showSubscriptions}
        onClose={() => setShowSubscriptions(false)}
        width={560}
      >
        {subscriptionsQuery.isLoading ? (
          <Skeleton active />
        ) : (
          <Table
            size="small"
            rowKey="event_type"
            pagination={false}
            dataSource={subscriptionsQuery.data?.items ?? []}
            columns={[
              { title: "이벤트", dataIndex: "event_type" },
              {
                title: "사용",
                dataIndex: "enabled",
                render: (value: boolean, row: NotificationSubscriptionItem) => (
                  <Switch
                    checked={value}
                    onChange={(checked) =>
                      subscriptionMutation.mutate({
                        ...row,
                        enabled: checked,
                      })
                    }
                  />
                ),
              },
              {
                title: "웹",
                dataIndex: "web_enabled",
                render: (value: boolean, row: NotificationSubscriptionItem) => (
                  <Switch
                    checked={value}
                    onChange={(checked) =>
                      subscriptionMutation.mutate({
                        ...row,
                        web_enabled: checked,
                      })
                    }
                  />
                ),
              },
              {
                title: "Telegram",
                dataIndex: "telegram_enabled",
                render: (value: boolean, row: NotificationSubscriptionItem) => (
                  <Switch
                    checked={value}
                    onChange={(checked) =>
                      subscriptionMutation.mutate({
                        ...row,
                        telegram_enabled: checked,
                      })
                    }
                  />
                ),
              },
            ]}
          />
        )}
        <Alert
          style={{ marginTop: 16 }}
          type="info"
          showIcon
          message="Telegram은 Notification Center 구독을 거쳐 발송됩니다."
        />
      </Drawer>
    </UserPageShell>
  );
}
