"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, Col, Row, Typography } from "antd";

import { StatusBadge } from "@/components/common/StatusBadge";
import type { HealthResponse } from "@/lib/api/apiTypes";
import { rootClient } from "@/lib/api/rootClient";
import { queryKeys } from "@/lib/query/queryKeys";
import { formatDateTime } from "@/utils/format";

async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await rootClient.get<HealthResponse>("/health");
  return data;
}

export function SystemStatusPlaceholder() {
  const healthQuery = useQuery({
    queryKey: queryKeys.system.health(),
    queryFn: fetchHealth,
  });

  const apiConnected = healthQuery.isSuccess;
  const apiStatus = healthQuery.isLoading
    ? "unknown"
    : healthQuery.isSuccess
      ? "healthy"
      : "error";

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} md={8}>
        <Card title="API 연결 상태" loading={healthQuery.isLoading}>
          <StatusBadge
            status={apiStatus}
            label={apiConnected ? "연결됨" : healthQuery.isLoading ? "확인 중" : "연결 실패"}
          />
          {healthQuery.data ? (
            <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
              status: {healthQuery.data.status}
              {healthQuery.data.timestamp
                ? ` · ${formatDateTime(healthQuery.data.timestamp)}`
                : null}
            </Typography.Paragraph>
          ) : null}
          {healthQuery.isError ? (
            <Typography.Paragraph type="danger" style={{ marginTop: 12, marginBottom: 0 }}>
              GET /health 요청 실패
            </Typography.Paragraph>
          ) : null}
        </Card>
      </Col>
      <Col xs={24} md={8}>
        <Card title="인증 상태">
          <StatusBadge status="healthy" label="BACKEND AUTH (JWT)" />
        </Card>
      </Col>
      <Col xs={24} md={8}>
        <Card title="현재 모드">
          <Typography.Text>JWT Backend Auth</Typography.Text>
          <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            회원가입·로그인 후 Access/Refresh Token 으로 API를 호출합니다.
          </Typography.Paragraph>
        </Card>
      </Col>
    </Row>
  );
}

export function useApiHealthConnected(): boolean {
  const healthQuery = useQuery({
    queryKey: queryKeys.system.health(),
    queryFn: fetchHealth,
  });
  return healthQuery.isSuccess;
}
