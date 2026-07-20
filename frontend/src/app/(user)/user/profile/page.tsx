"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Avatar,
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  Row,
  Select,
  Skeleton,
  Space,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { userRoutes } from "@/config/routes";
import { useAuth } from "@/features/auth/hooks/useAuth";
import type {
  ConnectedService,
  UpdateUserProfileRequest,
} from "@/features/user/api/userApi";
import * as userApi from "@/features/user/api/userApi";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const STATUS_COLOR: Record<string, string> = {
  CONNECTED: "green",
  NOT_CONNECTED: "default",
  ERROR: "red",
  EXPIRED: "orange",
  VERIFYING: "blue",
  DISABLED: "default",
};

export default function UserProfilePage() {
  const { message, modal } = App.useApp();
  const { logout } = useAuth();
  const queryClient = useQueryClient();
  const [profileForm] = Form.useForm<UpdateUserProfileRequest>();
  const [passwordForm] = Form.useForm();
  const [dirty, setDirty] = useState(false);

  const profileQuery = useQuery({
    queryKey: queryKeys.user.profile.detail(),
    queryFn: () => userApi.getUserProfile(),
  });

  const sessionsQuery = useQuery({
    queryKey: queryKeys.user.profile.sessions(),
    queryFn: () => userApi.listUserSessions(),
  });

  const connectionsQuery = useQuery({
    queryKey: queryKeys.user.profile.connections(),
    queryFn: () => userApi.getProfileConnections(),
  });

  const summaryQuery = useQuery({
    queryKey: queryKeys.user.profile.accountsSummary(),
    queryFn: () => userApi.getProfileAccountsSummary(),
  });

  useEffect(() => {
    const data = profileQuery.data;
    if (!data) return;
    profileForm.setFieldsValue({
      display_name: data.display_name ?? undefined,
      nickname: data.nickname ?? undefined,
      profile_image_url: data.profile_image_url ?? undefined,
      bio: data.bio ?? undefined,
      locale: data.locale,
    });
    setDirty(false);
  }, [profileQuery.data, profileForm]);

  const updateMutation = useMutation({
    mutationFn: (body: UpdateUserProfileRequest) =>
      userApi.updateUserProfile(body),
    onSuccess: async (data) => {
      message.success("프로필이 저장되었습니다.");
      queryClient.setQueryData(queryKeys.user.profile.detail(), data);
      setDirty(false);
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const passwordMutation = useMutation({
    mutationFn: userApi.changeUserPassword,
    onSuccess: async (result) => {
      passwordForm.resetFields();
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.profile.detail(),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.profile.sessions(),
      });
      if (result.current_session_kept) {
        message.success(
          `비밀번호가 변경되었습니다. 다른 기기 ${result.revoked_session_count}개 세션이 종료되었습니다.`,
        );
      } else {
        message.success("비밀번호가 변경되었습니다. 다시 로그인해 주세요.");
        await logout();
      }
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const revokeSessionMutation = useMutation({
    mutationFn: (sessionId: string) => userApi.revokeUserSession(sessionId),
    onSuccess: async (result) => {
      message.success("세션이 종료되었습니다.");
      if (result.was_current) {
        await logout();
        return;
      }
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.profile.sessions(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const revokeOthersMutation = useMutation({
    mutationFn: () => userApi.revokeUserSessions({ exclude_current: true }),
    onSuccess: async (result) => {
      message.success(`다른 기기 ${result.revoked_count}개 세션을 종료했습니다.`);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.profile.sessions(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const revokeAllMutation = useMutation({
    mutationFn: () => userApi.revokeUserSessions({ exclude_current: false }),
    onSuccess: async () => {
      message.success("모든 세션이 종료되었습니다.");
      await logout();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const disconnectTelegramMutation = useMutation({
    mutationFn: () => userApi.disconnectTelegramConnection(),
    onSuccess: async () => {
      message.success("Telegram 연결이 해제되었습니다.");
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.profile.connections(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const profile = profileQuery.data;
  const summary = summaryQuery.data ?? connectionsQuery.data?.accounts_summary;
  const connections = connectionsQuery.data?.connections ?? [];

  const avatarLabel = useMemo(() => {
    const name = profile?.display_name || profile?.nickname || profile?.username;
    return (name || "?").slice(0, 1).toUpperCase();
  }, [profile]);

  const confirmRevoke = (sessionId: string, isCurrent: boolean) => {
    modal.confirm({
      title: isCurrent ? "현재 기기에서 로그아웃할까요?" : "이 세션을 종료할까요?",
      content: isCurrent
        ? "로그아웃 후 로그인 화면으로 이동합니다."
        : "해당 기기의 로그인 세션이 즉시 만료됩니다.",
      okText: "종료",
      okButtonProps: { danger: true },
      onOk: () => revokeSessionMutation.mutateAsync(sessionId),
    });
  };

  return (
    <UserPageShell
      title="My Page"
      description="프로필 · 보안 · 로그인 세션 · 연결 계정"
      extra={
        <Button danger onClick={() => void logout()}>
          로그아웃
        </Button>
      }
    >
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        {profileQuery.isError ? (
          <Alert
            type="error"
            showIcon
            message="프로필을 불러오지 못했습니다."
            description={toApiError(profileQuery.error).message}
          />
        ) : null}

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={14}>
            <Card
              title="기본 정보"
              size="small"
              loading={profileQuery.isLoading}
              extra={
                <Button
                  type="primary"
                  disabled={!dirty}
                  loading={updateMutation.isPending}
                  onClick={() =>
                    void profileForm.validateFields().then((values) => {
                      updateMutation.mutate(values);
                    })
                  }
                >
                  저장
                </Button>
              }
            >
              {profile ? (
                <Space direction="vertical" style={{ width: "100%" }} size={12}>
                  <Space>
                    <Avatar size={48} src={profile.profile_image_url || undefined}>
                      {avatarLabel}
                    </Avatar>
                    <div>
                      <Typography.Text strong>
                        {profile.display_name || profile.username}
                      </Typography.Text>
                      <br />
                      <Typography.Text type="secondary">
                        @{profile.username}
                      </Typography.Text>
                    </div>
                  </Space>
                  <Descriptions column={1} size="small">
                    <Descriptions.Item label="이메일">
                      {profile.email_full || profile.email || "-"}
                    </Descriptions.Item>
                    <Descriptions.Item label="상태">
                      <Tag color={profile.status === "ACTIVE" ? "green" : "default"}>
                        {profile.status}
                      </Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="이메일 인증">
                      {profile.email_verified ? "완료" : "미인증"}
                    </Descriptions.Item>
                    <Descriptions.Item label="가입일">
                      {dayjs(profile.created_at).format("YYYY-MM-DD HH:mm")}
                    </Descriptions.Item>
                    <Descriptions.Item label="최근 로그인">
                      {profile.last_login_at
                        ? dayjs(profile.last_login_at).format("YYYY-MM-DD HH:mm")
                        : "-"}
                    </Descriptions.Item>
                  </Descriptions>
                  <Form
                    form={profileForm}
                    layout="vertical"
                    onValuesChange={() => setDirty(true)}
                  >
                    <Form.Item name="display_name" label="이름">
                      <Input maxLength={100} />
                    </Form.Item>
                    <Form.Item name="nickname" label="닉네임">
                      <Input maxLength={50} />
                    </Form.Item>
                    <Form.Item name="locale" label="언어">
                      <Select
                        options={[
                          { value: "KO", label: "한국어" },
                          { value: "EN", label: "English" },
                        ]}
                      />
                    </Form.Item>
                    <Form.Item name="profile_image_url" label="프로필 이미지 URL">
                      <Input placeholder="https://..." />
                    </Form.Item>
                    <Form.Item name="bio" label="소개">
                      <Input.TextArea rows={2} maxLength={500} />
                    </Form.Item>
                  </Form>
                  <Typography.Text type="secondary">
                    이메일 변경·2FA·회원 탈퇴는 후속 STEP에서 지원합니다.{" "}
                    <Link href={userRoutes.settings}>환경설정</Link>
                  </Typography.Text>
                </Space>
              ) : (
                <Skeleton active />
              )}
            </Card>
          </Col>

          <Col xs={24} lg={10}>
            <Card title="보안 · 비밀번호 변경" size="small">
              <Form
                form={passwordForm}
                layout="vertical"
                onFinish={(values) => {
                  if (values.new_password !== values.new_password_confirmation) {
                    message.error("새 비밀번호 확인이 일치하지 않습니다.");
                    return;
                  }
                  passwordMutation.mutate({
                    current_password: values.current_password,
                    new_password: values.new_password,
                    new_password_confirmation: values.new_password_confirmation,
                  });
                }}
              >
                <Form.Item
                  name="current_password"
                  label="현재 비밀번호"
                  rules={[{ required: true }]}
                >
                  <Input.Password autoComplete="current-password" />
                </Form.Item>
                <Form.Item
                  name="new_password"
                  label="새 비밀번호"
                  rules={[{ required: true, min: 8 }]}
                  extra="최소 8자 · 영문/숫자/특수문자 중 2종류 이상"
                >
                  <Input.Password autoComplete="new-password" />
                </Form.Item>
                <Form.Item
                  name="new_password_confirmation"
                  label="새 비밀번호 확인"
                  rules={[{ required: true }]}
                >
                  <Input.Password autoComplete="new-password" />
                </Form.Item>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={passwordMutation.isPending}
                  block
                >
                  비밀번호 변경
                </Button>
              </Form>
              {profile?.last_password_changed_at ? (
                <Typography.Paragraph
                  type="secondary"
                  style={{ marginTop: 12, marginBottom: 0 }}
                >
                  마지막 변경:{" "}
                  {dayjs(profile.last_password_changed_at).format(
                    "YYYY-MM-DD HH:mm",
                  )}
                </Typography.Paragraph>
              ) : null}
            </Card>
          </Col>
        </Row>

        <Card
          title="로그인 세션"
          size="small"
          loading={sessionsQuery.isLoading}
          extra={
            <Space wrap>
              <Button
                onClick={() =>
                  modal.confirm({
                    title: "다른 모든 기기에서 로그아웃할까요?",
                    onOk: () => revokeOthersMutation.mutateAsync(),
                  })
                }
                loading={revokeOthersMutation.isPending}
              >
                다른 모든 기기 로그아웃
              </Button>
              <Button
                danger
                onClick={() =>
                  modal.confirm({
                    title: "모든 기기에서 로그아웃할까요?",
                    content: "현재 기기도 포함됩니다.",
                    okButtonProps: { danger: true },
                    onOk: () => revokeAllMutation.mutateAsync(),
                  })
                }
                loading={revokeAllMutation.isPending}
              >
                모든 기기 로그아웃
              </Button>
            </Space>
          }
        >
          {sessionsQuery.isError ? (
            <Alert
              type="warning"
              showIcon
              message={toApiError(sessionsQuery.error).message}
            />
          ) : (sessionsQuery.data?.items.length ?? 0) === 0 ? (
            <Alert type="info" showIcon message="활성 세션이 없습니다." />
          ) : (
            <Space direction="vertical" style={{ width: "100%" }} size={10}>
              {sessionsQuery.data?.items.map((row) => (
                <Card key={row.session_id} size="small" type="inner">
                  <Space
                    style={{ width: "100%", justifyContent: "space-between" }}
                    wrap
                  >
                    <Space direction="vertical" size={0}>
                      <Space>
                        <Typography.Text strong>
                          {row.device_name}
                        </Typography.Text>
                        {row.is_current ? (
                          <Badge status="processing" text="현재 기기" />
                        ) : null}
                      </Space>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {row.browser_name || "-"} · {row.operating_system || "-"} ·{" "}
                        {row.ip_address_masked || "-"}
                      </Typography.Text>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        최근 사용{" "}
                        {dayjs(row.last_used_at).format("YYYY-MM-DD HH:mm")} · 만료{" "}
                        {dayjs(row.expires_at).format("YYYY-MM-DD HH:mm")}
                      </Typography.Text>
                    </Space>
                    <Button
                      danger
                      size="small"
                      onClick={() =>
                        confirmRevoke(row.session_id, row.is_current)
                      }
                    >
                      로그아웃
                    </Button>
                  </Space>
                </Card>
              ))}
            </Space>
          )}
        </Card>

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={10}>
            <Card
              title="계정 소유권 요약"
              size="small"
              loading={summaryQuery.isLoading}
              extra={<Link href={userRoutes.account}>계좌 관리</Link>}
            >
              {summary ? (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="Paper">
                    {summary.paper_accounts.count}개
                    {summary.paper_accounts.default_account_id
                      ? ` · 기본 #${summary.paper_accounts.default_account_id}`
                      : ""}
                  </Descriptions.Item>
                  <Descriptions.Item label="키움">
                    {summary.kiwoom_accounts.count}개 ·{" "}
                    {summary.kiwoom_accounts.connected ? "연결됨" : "미연결"}
                  </Descriptions.Item>
                  <Descriptions.Item label="업비트">
                    {summary.upbit_accounts.count}개 ·{" "}
                    {summary.upbit_accounts.connected ? "연결됨" : "미연결"}
                  </Descriptions.Item>
                  <Descriptions.Item label="전체">
                    {summary.total_accounts}개
                  </Descriptions.Item>
                </Descriptions>
              ) : (
                <Skeleton active paragraph={{ rows: 3 }} />
              )}
            </Card>
          </Col>
          <Col xs={24} lg={14}>
            <Card
              title="연결 계정"
              size="small"
              loading={connectionsQuery.isLoading}
            >
              <Space direction="vertical" style={{ width: "100%" }} size={10}>
                {connections.map((conn: ConnectedService) => (
                  <Card key={conn.connection_type} size="small" type="inner">
                    <Space
                      style={{ width: "100%", justifyContent: "space-between" }}
                      wrap
                    >
                      <Space direction="vertical" size={0}>
                        <Space>
                          <Typography.Text strong>
                            {conn.display_name}
                          </Typography.Text>
                          <Tag color={STATUS_COLOR[conn.status] || "default"}>
                            {conn.status}
                          </Tag>
                          {conn.mode ? <Tag>{conn.mode}</Tag> : null}
                        </Space>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {conn.account_masked || "마스킹 정보 없음"}
                          {conn.last_verified_at
                            ? ` · 확인 ${dayjs(conn.last_verified_at).format("YYYY-MM-DD HH:mm")}`
                            : ""}
                        </Typography.Text>
                        {conn.note ? (
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            {conn.note}
                          </Typography.Text>
                        ) : null}
                      </Space>
                      <Space>
                        {conn.manage_path ? (
                          <Link href={conn.manage_path}>관리</Link>
                        ) : null}
                        {conn.connection_type === "TELEGRAM" &&
                        conn.can_disconnect ? (
                          <Button
                            size="small"
                            danger
                            onClick={() =>
                              modal.confirm({
                                title: "Telegram 연결을 해제할까요?",
                                onOk: () =>
                                  disconnectTelegramMutation.mutateAsync(),
                              })
                            }
                          >
                            연결 해제
                          </Button>
                        ) : null}
                      </Space>
                    </Space>
                  </Card>
                ))}
              </Space>
            </Card>
          </Col>
        </Row>
      </Space>
    </UserPageShell>
  );
}
