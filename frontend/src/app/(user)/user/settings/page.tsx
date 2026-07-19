"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  Descriptions,
  Row,
  Space,
  Tag,
  Typography,
} from "antd";

import { PageContainer } from "@/components/common/PageContainer";
import { env } from "@/config/env";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
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

export default function UserSettingsPage() {
  const healthQuery = useQuery({
    queryKey: queryKeys.user.health(),
    queryFn: userApi.getHealth,
  });

  const killQuery = useQuery({
    queryKey: queryKeys.user.killSwitch(),
    queryFn: userApi.getKillSwitch,
  });

  const notificationQuery = useQuery({
    queryKey: queryKeys.user.notificationStatus(),
    queryFn: userApi.getNotificationStatus,
  });

  const kiwoomQuery = useQuery({
    queryKey: queryKeys.user.kiwoomConfig(),
    queryFn: userApi.getKiwoomConfiguration,
  });

  const health = asRecord(healthQuery.data);
  const kill = asRecord(killQuery.data);
  const kiwoom = asRecord(kiwoomQuery.data);
  const channels = extractRows(
    asRecord(notificationQuery.data)?.channels ?? notificationQuery.data,
  );

  const killActive = Boolean(
    kill?.active ?? kill?.enabled ?? kill?.is_active ?? kill?.kill_switch_enabled,
  );

  return (
    <PageContainer
      title="설정"
      description="운영 상태 · 연결 정보 (읽기 전용)"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <UnimplementedNotice
          feature="사용자 개인 설정 CRUD"
          reason="Backend에 preferences/settings 사용자 API가 없습니다. 서버 설정은 Admin 환경설정으로만 관리됩니다. 아래는 조회 가능한 운영·연결 상태입니다."
          relatedApis={[
            "GET /health",
            "GET /api/v1/risk/kill-switch",
            "GET /api/v1/notification/status",
            "GET /api/v1/kiwoom/configuration",
            "TODO: GET/PUT /api/v1/user/preferences",
          ]}
        />

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Card
              title="Frontend 환경"
              size="small"
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  NEXT_PUBLIC_*
                </Typography.Text>
              }
            >
              <Descriptions column={1} size="small">
                <Descriptions.Item label="APP_NAME">
                  {env.APP_NAME}
                </Descriptions.Item>
                <Descriptions.Item label="API_BASE_URL">
                  {env.API_BASE_URL}
                </Descriptions.Item>
                <Descriptions.Item label="API_PREFIX">
                  {env.API_PREFIX}
                </Descriptions.Item>
                <Descriptions.Item label="AUTH_MODE">
                  {env.AUTH_MODE}
                </Descriptions.Item>
              </Descriptions>
            </Card>
          </Col>

          <Col xs={24} lg={12}>
            <Card
              title="시스템 Health"
              size="small"
              loading={healthQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /health
                </Typography.Text>
              }
            >
              {healthQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title={toApiError(healthQuery.error).message}
                />
              ) : (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="status">
                    <Tag
                      color={
                        String(health?.status ?? "").toLowerCase() === "ok" ||
                        String(health?.status ?? "").toLowerCase() === "healthy"
                          ? "success"
                          : "default"
                      }
                    >
                      {cell(health?.status)}
                    </Tag>
                  </Descriptions.Item>
                  {Object.entries(health ?? {})
                    .filter(([key]) => key !== "status")
                    .slice(0, 6)
                    .map(([key, value]) => (
                      <Descriptions.Item key={key} label={key}>
                        {cell(value)}
                      </Descriptions.Item>
                    ))}
                </Descriptions>
              )}
            </Card>
          </Col>

          <Col xs={24} lg={12}>
            <Card
              title="Kill Switch"
              size="small"
              loading={killQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /risk/kill-switch
                </Typography.Text>
              }
            >
              {killQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title={toApiError(killQuery.error).message}
                />
              ) : (
                <>
                  <Tag color={killActive ? "error" : "success"}>
                    {killActive ? "ACTIVE" : "INACTIVE"}
                  </Tag>
                  <Descriptions
                    column={1}
                    size="small"
                    style={{ marginTop: 12 }}
                  >
                    {Object.entries(kill ?? {})
                      .slice(0, 8)
                      .map(([key, value]) => (
                        <Descriptions.Item key={key} label={key}>
                          {cell(value)}
                        </Descriptions.Item>
                      ))}
                  </Descriptions>
                </>
              )}
            </Card>
          </Col>

          <Col xs={24} lg={12}>
            <Card
              title="키움 설정"
              size="small"
              loading={kiwoomQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /kiwoom/configuration
                </Typography.Text>
              }
            >
              {kiwoomQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title={toApiError(kiwoomQuery.error).message}
                />
              ) : (
                <Descriptions column={1} size="small">
                  {Object.entries(kiwoom ?? {})
                    .slice(0, 10)
                    .map(([key, value]) => (
                      <Descriptions.Item key={key} label={key}>
                        {cell(value)}
                      </Descriptions.Item>
                    ))}
                </Descriptions>
              )}
            </Card>
          </Col>
        </Row>

        <Card
          title="알림 채널"
          size="small"
          loading={notificationQuery.isLoading}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              GET /notification/status
            </Typography.Text>
          }
        >
          {notificationQuery.error ? (
            <Alert
              type="warning"
              showIcon
              title={toApiError(notificationQuery.error).message}
            />
          ) : channels.length === 0 ? (
            <Typography.Text type="secondary">채널 없음</Typography.Text>
          ) : (
            <Space wrap>
              {channels.map((channel, index) => {
                const name = cell(
                  channel.channel ??
                    channel.name ??
                    channel.type ??
                    `channel-${index}`,
                );
                const enabled = channelEnabled(channel);
                return (
                  <Tag
                    key={`${name}-${index}`}
                    color={enabled ? "success" : "default"}
                  >
                    {name}: {enabled ? "on" : "off"}
                  </Tag>
                );
              })}
            </Space>
          )}
        </Card>
      </Space>
    </PageContainer>
  );
}
