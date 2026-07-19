"use client";

import { useQuery } from "@tanstack/react-query";
import { Space } from "antd";

import { PageContainer } from "@/components/common/PageContainer";
import { JsonPanel } from "@/features/user/components/JsonPanel";
import * as userApi from "@/features/user/api/userApi";
import { queryKeys } from "@/lib/query/queryKeys";
import { toApiError } from "@/lib/api/apiError";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";

export default function UserNotificationsPage() {
  const status = useQuery({
    queryKey: queryKeys.user.notificationStatus(),
    queryFn: userApi.getNotificationStatus,
  });

  return (
    <PageContainer title="알림" description="알림 채널 상태만 조회 가능">
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <UnimplementedNotice
          feature="알림 인박스·읽음·구독"
          reason="사용자 알림함 GET API가 없습니다. Telegram/Slack/Discord 채널 상태·테스트용 API만 있습니다."
          relatedApis={[
            "GET /api/v1/notification/status",
            "POST /api/v1/notification/test",
          ]}
        />
        <JsonPanel
          title="GET /api/v1/notification/status"
          loading={status.isLoading}
          error={status.error ? toApiError(status.error) : null}
          data={status.data}
        />
      </Space>
    </PageContainer>
  );
}
