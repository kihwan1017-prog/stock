"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Form,
  InputNumber,
  Row,
  Select,
  Skeleton,
  Space,
  Switch,
  Typography,
} from "antd";
import Link from "next/link";
import { useEffect } from "react";

import { userRoutes } from "@/config/routes";
import type { UserSettingsPatch } from "@/features/user/api/userApi";
import * as userApi from "@/features/user/api/userApi";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { useThemeMode } from "@/hooks/useThemeMode";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { applyThemeFromSettings } from "@/features/user/settings/settingsHelpers";

type SettingsFormValues = UserSettingsPatch;

export default function UserSettingsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { setMode } = useThemeMode();
  const [form] = Form.useForm<SettingsFormValues>();

  const settingsQuery = useQuery({
    queryKey: queryKeys.user.settings.get(),
    queryFn: () => userApi.getUserSettings(),
  });

  const accountsQuery = useQuery({
    queryKey: queryKeys.user.userAccounts({}),
    queryFn: () => userApi.listUserAccounts(),
  });

  const watchlistQuery = useQuery({
    queryKey: queryKeys.user.watchlist(),
    queryFn: () => userApi.listWatchlist(),
  });

  useEffect(() => {
    if (!settingsQuery.data) return;
    const data = settingsQuery.data;
    form.setFieldsValue({
      theme: data.theme,
      language: data.language,
      timezone: data.timezone,
      date_format: data.date_format,
      number_format: data.number_format,
      currency: data.currency,
      default_market: data.default_market,
      default_account_id: data.default_account_id,
      default_watchlist_id: data.default_watchlist_id,
      default_dashboard: data.default_dashboard,
      items_per_page: data.items_per_page,
      ai_enabled: data.ai_enabled,
      ai_auto_summary: data.ai_auto_summary,
      ai_recommendation_enabled: data.ai_recommendation_enabled,
      notification_enabled: data.notification_enabled,
      telegram_enabled: data.telegram_enabled,
      email_enabled: data.email_enabled,
      web_enabled: data.web_enabled,
    });
    setMode(applyThemeFromSettings(data));
  }, [settingsQuery.data, form, setMode]);

  const saveMutation = useMutation({
    mutationFn: (body: UserSettingsPatch) => userApi.patchUserSettings(body),
    onSuccess: async (data) => {
      message.success("설정이 저장되었습니다.");
      queryClient.setQueryData(queryKeys.user.settings.get(), data);
      setMode(applyThemeFromSettings(data));
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.userAccounts({}),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const resetMutation = useMutation({
    mutationFn: () => userApi.resetUserSettings(),
    onSuccess: async (data) => {
      message.success("기본값으로 초기화되었습니다.");
      queryClient.setQueryData(queryKeys.user.settings.get(), data);
      form.setFieldsValue(data);
      setMode(applyThemeFromSettings(data));
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const onSave = async () => {
    const values = await form.validateFields();
    saveMutation.mutate(values);
  };

  const accountOptions =
    accountsQuery.data?.items.map((row) => ({
      value: row.account_id,
      label: `${row.account_name} (#${row.account_id})${
        row.is_default ? " · 기본" : ""
      }`,
    })) ?? [];

  const watchlistOptions =
    watchlistQuery.data?.items.map((row) => ({
      value: row.watchlist_id,
      label: `[${row.market}] ${row.symbol} ${row.symbol_name}`,
    })) ?? [];

  return (
    <UserPageShell
      title="설정"
      description="테마 · 언어 · 기본 계좌 · AI · 알림 (관리자 Settings와 분리)"
      extra={
        <Space wrap>
          <Button
            onClick={() => resetMutation.mutate()}
            loading={resetMutation.isPending}
          >
            기본값 초기화
          </Button>
          <Button
            type="primary"
            onClick={() => void onSave()}
            loading={saveMutation.isPending}
          >
            저장
          </Button>
        </Space>
      }
    >
      {settingsQuery.isLoading ? (
        <Skeleton active paragraph={{ rows: 12 }} />
      ) : settingsQuery.isError ? (
        <Alert
          type="error"
          showIcon
          message="설정을 불러오지 못했습니다."
          description={toApiError(settingsQuery.error).message}
        />
      ) : (
        <Form form={form} layout="vertical" requiredMark={false}>
          <Row gutter={[16, 16]}>
            <Col xs={24} lg={12}>
              <Card title="Appearance" size="small">
                <Form.Item name="theme" label="테마">
                  <Select
                    options={[
                      { value: "light", label: "Light" },
                      { value: "dark", label: "Dark" },
                      { value: "system", label: "System" },
                    ]}
                  />
                </Form.Item>
                <Form.Item name="language" label="언어">
                  <Select
                    options={[
                      { value: "KO", label: "한국어" },
                      { value: "EN", label: "English" },
                    ]}
                  />
                </Form.Item>
                <Form.Item name="timezone" label="타임존">
                  <Select
                    options={[
                      { value: "Asia/Seoul", label: "Asia/Seoul" },
                      { value: "UTC", label: "UTC" },
                    ]}
                  />
                </Form.Item>
                <Form.Item name="date_format" label="날짜 형식">
                  <Select
                    options={[
                      { value: "YYYY-MM-DD", label: "YYYY-MM-DD" },
                      { value: "YYYY/MM/DD", label: "YYYY/MM/DD" },
                      { value: "DD/MM/YYYY", label: "DD/MM/YYYY" },
                      { value: "MM/DD/YYYY", label: "MM/DD/YYYY" },
                    ]}
                  />
                </Form.Item>
                <Form.Item name="number_format" label="숫자 형식">
                  <Select
                    options={[
                      { value: "1,234.56", label: "1,234.56" },
                      { value: "1.234,56", label: "1.234,56" },
                    ]}
                  />
                </Form.Item>
                <Form.Item name="currency" label="통화">
                  <Select
                    options={[
                      { value: "KRW", label: "KRW" },
                      { value: "USD", label: "USD" },
                    ]}
                  />
                </Form.Item>
              </Card>
            </Col>

            <Col xs={24} lg={12}>
              <Card title="General / Portfolio" size="small">
                <Form.Item name="default_market" label="기본 시장">
                  <Select
                    options={[
                      { value: "KRX", label: "KRX" },
                      { value: "NASDAQ", label: "NASDAQ" },
                      { value: "UPBIT", label: "UPBIT" },
                    ]}
                  />
                </Form.Item>
                <Form.Item name="default_account_id" label="기본 계좌">
                  <Select
                    allowClear
                    placeholder="계좌 선택"
                    options={accountOptions}
                    loading={accountsQuery.isLoading}
                  />
                </Form.Item>
                <Form.Item
                  name="default_watchlist_id"
                  label="기본 관심종목 (핀)"
                >
                  <Select
                    allowClear
                    placeholder="관심종목 선택"
                    options={watchlistOptions}
                    loading={watchlistQuery.isLoading}
                  />
                </Form.Item>
                <Form.Item name="default_dashboard" label="기본 Dashboard">
                  <Select
                    options={[
                      { value: "Dashboard", label: "Dashboard" },
                      { value: "Portfolio", label: "Portfolio" },
                      { value: "Watchlist", label: "Watchlist" },
                      { value: "News", label: "News" },
                      { value: "AI", label: "AI" },
                      { value: "Notifications", label: "Notifications" },
                    ]}
                  />
                </Form.Item>
                <Form.Item name="items_per_page" label="페이지당 항목 수">
                  <InputNumber min={5} max={100} style={{ width: "100%" }} />
                </Form.Item>
              </Card>
            </Col>

            <Col xs={24} lg={12}>
              <Card title="AI" size="small">
                <Form.Item
                  name="ai_enabled"
                  label="AI 기능 사용"
                  valuePropName="checked"
                >
                  <Switch />
                </Form.Item>
                <Form.Item
                  name="ai_auto_summary"
                  label="공시 AI 요약"
                  valuePropName="checked"
                >
                  <Switch />
                </Form.Item>
                <Form.Item
                  name="ai_recommendation_enabled"
                  label="AI 추천"
                  valuePropName="checked"
                >
                  <Switch />
                </Form.Item>
                <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  Ollama Host 등 관리자 설정은 표시·변경하지 않습니다.
                </Typography.Paragraph>
              </Card>
            </Col>

            <Col xs={24} lg={12}>
              <Card
                title="Notification"
                size="small"
                extra={
                  <Link href={userRoutes.notifications}>이벤트별 구독 →</Link>
                }
              >
                <Form.Item
                  name="notification_enabled"
                  label="알림 사용"
                  valuePropName="checked"
                >
                  <Switch />
                </Form.Item>
                <Form.Item
                  name="web_enabled"
                  label="웹 알림"
                  valuePropName="checked"
                >
                  <Switch />
                </Form.Item>
                <Form.Item
                  name="telegram_enabled"
                  label="Telegram"
                  valuePropName="checked"
                >
                  <Switch />
                </Form.Item>
                <Form.Item
                  name="email_enabled"
                  label="Email"
                  valuePropName="checked"
                >
                  <Switch />
                </Form.Item>
                <Alert
                  type="info"
                  showIcon
                  message="이벤트별 구독은 알림 센터에서 관리합니다."
                />
              </Card>
            </Col>
          </Row>
        </Form>
      )}
    </UserPageShell>
  );
}
