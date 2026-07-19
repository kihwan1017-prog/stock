"use client";

import { Space } from "antd";

import { PageContainer } from "@/components/common/PageContainer";
import { DashboardWelcome } from "@/features/dashboard/components/DashboardWelcome";
import { FoundationChecklist } from "@/features/dashboard/components/FoundationChecklist";
import {
  SystemStatusPlaceholder,
  useApiHealthConnected,
} from "@/features/dashboard/components/SystemStatusPlaceholder";

export default function DashboardPage() {
  const apiConnected = useApiHealthConnected();

  return (
    <PageContainer
      title="Dashboard"
      description="STEP41 관리자 기초 골격 — 실제 계좌/주문/AI는 STEP42에서 연결합니다."
    >
      <Space orientation="vertical" size={24} style={{ width: "100%" }}>
        <DashboardWelcome />
        <SystemStatusPlaceholder />
        <FoundationChecklist apiConnected={apiConnected} />
      </Space>
    </PageContainer>
  );
}
