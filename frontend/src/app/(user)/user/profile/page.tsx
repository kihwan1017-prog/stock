"use client";

import { Card, Descriptions, Space } from "antd";

import { PageContainer } from "@/components/common/PageContainer";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";

export default function UserProfilePage() {
  const { user } = useAuth();

  return (
    <PageContainer title="내 정보" description="로컬 개발 세션 정보 (JWT /me 없음)">
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <UnimplementedNotice
          feature="회원 프로필 /me"
          reason="Backend에 GET /me · 회원 프로필 API가 없습니다. 아래는 AUTH_MODE=disabled 로컬 세션입니다."
        />
        <Card title="로컬 세션">
          <Descriptions column={1} size="small">
            <Descriptions.Item label="id">{user?.id ?? "-"}</Descriptions.Item>
            <Descriptions.Item label="username">{user?.username ?? "-"}</Descriptions.Item>
            <Descriptions.Item label="displayName">
              {user?.displayName ?? "-"}
            </Descriptions.Item>
            <Descriptions.Item label="roles">
              {(user?.roles ?? []).join(", ") || "-"}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      </Space>
    </PageContainer>
  );
}
