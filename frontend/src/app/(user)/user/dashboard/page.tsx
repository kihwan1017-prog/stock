"use client";

import { useQuery } from "@tanstack/react-query";
import { Col, Row, Space, Typography } from "antd";

import { PageContainer } from "@/components/common/PageContainer";
import { JsonPanel } from "@/features/user/components/JsonPanel";
import * as userApi from "@/features/user/api/userApi";
import { queryKeys } from "@/lib/query/queryKeys";
import { toApiError } from "@/lib/api/apiError";

export default function UserDashboardPage() {
  const health = useQuery({
    queryKey: queryKeys.system.health(),
    queryFn: userApi.getHealth,
  });
  const systemDash = useQuery({
    queryKey: queryKeys.system.dashboard(),
    queryFn: () => userApi.getSystemDashboard({ exchange_code: "KRX" }),
  });
  const summary = useQuery({
    queryKey: queryKeys.dashboard.summary(),
    queryFn: userApi.getDashboardSummary,
  });
  const killSwitch = useQuery({
    queryKey: queryKeys.user.killSwitch(),
    queryFn: userApi.getKillSwitch,
  });

  return (
    <PageContainer
      title="Dashboard"
      description="기존 API(/health, /system/dashboard, /dashboard/summary, kill-switch)를 연결한 투자자 요약 화면입니다."
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          회원 전용 「내 대시보드」 API는 없습니다. 운영/시스템 API를 그대로 표시합니다.
        </Typography.Paragraph>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <JsonPanel
              title="GET /health"
              loading={health.isLoading}
              error={health.error ? toApiError(health.error) : null}
              data={health.data}
            />
          </Col>
          <Col xs={24} lg={12}>
            <JsonPanel
              title="GET /api/v1/risk/kill-switch"
              loading={killSwitch.isLoading}
              error={killSwitch.error ? toApiError(killSwitch.error) : null}
              data={killSwitch.data}
            />
          </Col>
          <Col xs={24} lg={12}>
            <JsonPanel
              title="GET /api/v1/system/dashboard"
              loading={systemDash.isLoading}
              error={systemDash.error ? toApiError(systemDash.error) : null}
              data={systemDash.data}
            />
          </Col>
          <Col xs={24} lg={12}>
            <JsonPanel
              title="GET /api/v1/dashboard/summary"
              loading={summary.isLoading}
              error={summary.error ? toApiError(summary.error) : null}
              data={summary.data}
            />
          </Col>
        </Row>
      </Space>
    </PageContainer>
  );
}
