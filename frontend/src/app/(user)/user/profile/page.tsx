"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Row,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";

import { ChangePasswordForm } from "@/features/auth/components/ChangePasswordForm";
import { fetchCurrentUser } from "@/features/auth/api/authApi";
import { useAuth } from "@/features/auth/hooks/useAuth";
import {
  displayRoleLabel,
  primaryProductRole,
} from "@/features/auth/utils/roles";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import * as userApi from "@/features/user/api/userApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";

function tableRowKey(row: Record<string, unknown>, fields: string[]): string {
  for (const field of fields) {
    const value = row[field];
    if (value !== null && value !== undefined && value !== "") {
      return String(value);
    }
  }
  try {
    return JSON.stringify(row);
  } catch {
    return "unknown-row";
  }
}

export default function UserProfilePage() {
  const { user: sessionUser, logout, accessToken } = useAuth();

  const meQuery = useQuery({
    queryKey: queryKeys.auth.me(),
    queryFn: fetchCurrentUser,
  });

  const paperAccountsQuery = useQuery({
    queryKey: queryKeys.user.paperAccounts(),
    queryFn: () => userApi.listPaperAccounts({ limit: 20 }),
  });

  const brokerQuery = useQuery({
    queryKey: queryKeys.user.brokerAccount(),
    queryFn: userApi.getBrokerAccount,
    retry: false,
  });

  const profile = meQuery.data ?? sessionUser;
  const errorMessage = meQuery.error ? toApiError(meQuery.error).message : null;
  const paperRows = extractRows(paperAccountsQuery.data);
  const broker = asRecord(brokerQuery.data);
  const productRole = primaryProductRole(profile?.roles);

  return (
    <UserPageShell
      title="My Page"
      description="프로필 · JWT 세션 · 비밀번호 변경 · RBAC 역할"
      extra={
        <Button danger onClick={() => void logout()}>
          로그아웃
        </Button>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        {errorMessage ? (
          <Alert type="warning" showIcon title={errorMessage} />
        ) : null}

        <Alert
          type="info"
          showIcon
          title={`제품 역할: ${productRole}`}
          description="Backend 시드 역할은 admin / operator / viewer 입니다. trader는 operator에 매핑됩니다. viewer는 매매·자동매매·전략 메뉴가 제한됩니다."
        />

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Card
              title="계정"
              size="small"
              loading={meQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /auth/me
                </Typography.Text>
              }
            >
              <Descriptions column={1} size="small">
                <Descriptions.Item label="id">
                  {profile?.id ?? "-"}
                </Descriptions.Item>
                <Descriptions.Item label="username">
                  {profile?.username ?? "-"}
                </Descriptions.Item>
                <Descriptions.Item label="email">
                  {profile?.email ?? "-"}
                </Descriptions.Item>
                <Descriptions.Item label="displayName">
                  {profile?.displayName ?? "-"}
                </Descriptions.Item>
                <Descriptions.Item label="roles">
                  <Space wrap size={[4, 4]}>
                    {(profile?.roles ?? []).length === 0 ? (
                      <Typography.Text type="secondary">-</Typography.Text>
                    ) : (
                      (profile?.roles ?? []).map((role) => (
                        <Tag key={role}>{displayRoleLabel(role)}</Tag>
                      ))
                    )}
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="permissions">
                  <Space wrap size={[4, 4]}>
                    {(profile?.permissions ?? []).length === 0 ? (
                      <Typography.Text type="secondary">-</Typography.Text>
                    ) : (
                      (profile?.permissions ?? []).slice(0, 12).map((perm) => (
                        <Tag key={perm}>{perm}</Tag>
                      ))
                    )}
                    {(profile?.permissions?.length ?? 0) > 12 ? (
                      <Tag>+{(profile?.permissions?.length ?? 0) - 12}</Tag>
                    ) : null}
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="JWT">
                  {accessToken ? (
                    <Typography.Text code style={{ fontSize: 11 }}>
                      {accessToken.slice(0, 18)}… (access)
                    </Typography.Text>
                  ) : (
                    "-"
                  )}
                </Descriptions.Item>
              </Descriptions>
            </Card>
          </Col>

          <Col xs={24} lg={12}>
            <ChangePasswordForm />
          </Col>
        </Row>

        <Card
          title="Paper 계좌"
          size="small"
          loading={paperAccountsQuery.isLoading}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              GET /paper-accounts
            </Typography.Text>
          }
        >
          {/* TODO: 회원별 계좌 소유권 API */}
          <UnimplementedNotice
            feature="회원별 계좌 소유권"
            reason="사용자 스코프 계좌 목록 API가 없어 전역 Paper 계좌를 표시합니다."
            relatedApis={[
              "GET /api/v1/paper-accounts",
              "TODO: GET /api/v1/user/accounts",
            ]}
          />
          {paperAccountsQuery.error ? (
            <Alert
              style={{ marginTop: 12 }}
              type="warning"
              showIcon
              title={toApiError(paperAccountsQuery.error).message}
            />
          ) : (
            <Table
              style={{ marginTop: 12 }}
              size="small"
              pagination={false}
              rowKey={(row) =>
                tableRowKey(row, ["account_id", "id", "account_name"])
              }
              dataSource={paperRows.slice(0, 10)}
              locale={{ emptyText: "Paper 계좌 없음" }}
              columns={[
                {
                  title: "ID",
                  dataIndex: "account_id",
                  width: 80,
                  render: (v, row) => cell(v ?? row.id),
                },
                {
                  title: "이름",
                  dataIndex: "account_name",
                  render: (v, row) => cell(v ?? row.name),
                },
                {
                  title: "현금",
                  dataIndex: "cash_balance",
                  render: (v, row) =>
                    cell(v ?? row.cash ?? row.available_cash),
                },
                {
                  title: "통화",
                  dataIndex: "currency_code",
                  width: 80,
                  render: cell,
                },
              ]}
            />
          )}
        </Card>

        <Card
          title="브로커 계좌"
          size="small"
          loading={brokerQuery.isLoading}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              GET /broker/account
            </Typography.Text>
          }
        >
          {brokerQuery.error ? (
            <Alert
              type="info"
              showIcon
              title={toApiError(brokerQuery.error).message}
              description="브로커 연동이 없거나 권한이 없을 수 있습니다."
            />
          ) : (
            <Descriptions column={1} size="small">
              {Object.entries(broker ?? {})
                .slice(0, 12)
                .map(([key, value]) => (
                  <Descriptions.Item key={key} label={key}>
                    {cell(value)}
                  </Descriptions.Item>
                ))}
            </Descriptions>
          )}
        </Card>
      </Space>
    </UserPageShell>
  );
}
