"use client";

import { Space } from "antd";

import { PageContainer } from "@/components/common/PageContainer";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";

export default function UserDisclosuresPage() {
  return (
    <PageContainer title="공시" description="DART 조회 API 없음">
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <UnimplementedNotice
          feature="공시 목록·상세 조회"
          reason="Backend DART API는 동기화(POST /api/v1/dart/sync, /dart/corps/sync)만 있고, 사용자가 볼 GET 조회 API가 없습니다. 추측으로 화면을 만들지 않았습니다."
          relatedApis={["POST /api/v1/dart/sync", "POST /api/v1/dart/corps/sync"]}
        />
      </Space>
    </PageContainer>
  );
}
