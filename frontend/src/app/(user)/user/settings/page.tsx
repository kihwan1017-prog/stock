"use client";

import { Space } from "antd";

import { PageContainer } from "@/components/common/PageContainer";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";

export default function UserSettingsPage() {
  return (
    <PageContainer title="설정" description="사용자 설정 API 없음">
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <UnimplementedNotice
          feature="사용자 설정 CRUD"
          reason="Backend에 preferences/settings 사용자 API가 없습니다. 서버 설정은 환경변수(관리자)로만 관리됩니다."
        />
      </Space>
    </PageContainer>
  );
}
