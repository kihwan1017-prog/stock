"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Form,
  InputNumber,
  Select,
  Space,
  Switch,
  Tag,
} from "antd";
import Link from "next/link";
import { useMemo, useState } from "react";

import { userRoutes } from "@/config/routes";
import type { RiskSettingsPayload, UserAccount } from "@/features/user/api/userApi";
import * as userApi from "@/features/user/api/userApi";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { asRecord } from "@/shared/utils/dataHelpers";
import { percentToRate, rateToPercent } from "@/shared/utils/riskRatePercent";

export default function UserRiskPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const [accountForm] = Form.useForm();
  const [selectedUbaId, setSelectedUbaId] = useState<number | null>(null);

  const killSwitchQuery = useQuery({
    queryKey: queryKeys.user.killSwitch(),
    queryFn: userApi.getKillSwitch,
    refetchInterval: 15_000,
  });

  const riskQuery = useQuery({
    queryKey: queryKeys.user.riskSettings(),
    queryFn: userApi.getMyRiskSettings,
  });

  const accountsQuery = useQuery({
    queryKey: queryKeys.user.userAccounts(),
    queryFn: () => userApi.listUserAccounts(),
  });

  const liveStatusQuery = useQuery({
    queryKey: queryKeys.user.liveOrderStatus(),
    queryFn: () => userApi.listMyLiveOrderStatus(),
  });
  const liveOpsQuery = useQuery({
    queryKey: ["user", "live-ops-dashboard"],
    queryFn: () => userApi.getMyLiveOpsDashboard(),
    refetchInterval: 30_000,
  });
  const postFill = asRecord(asRecord(liveOpsQuery.data)?.post_fill_verification);

  const brokerAccounts = useMemo(
    () =>
      (accountsQuery.data?.items ?? []).filter(
        (row: UserAccount) =>
          (row.account_type === "KIWOOM" || row.account_type === "UPBIT") &&
          row.is_active,
      ),
    [accountsQuery.data],
  );

  // 선택 전이면 첫 활성 브로커 계좌를 기본값으로 사용 (effect setState 회피)
  const activeUbaId =
    selectedUbaId ?? brokerAccounts[0]?.account_id ?? null;

  const accountRiskQuery = useQuery({
    queryKey: queryKeys.user.accountRiskSettings(activeUbaId ?? 0),
    queryFn: () => userApi.getAccountRiskSettings(activeUbaId!),
    enabled: activeUbaId != null && activeUbaId > 0,
  });

  const userResolved = asRecord(asRecord(riskQuery.data)?.resolved);
  const accountResolved = asRecord(asRecord(accountRiskQuery.data)?.resolved);

  const userInitialValues = useMemo(() => {
    if (!userResolved) return undefined;
    return {
      max_order_amount: Number(userResolved.max_order_amount ?? 0),
      daily_max_order_amount: Number(userResolved.daily_max_order_amount ?? 0),
      max_total_investment_amount: Number(
        userResolved.max_total_investment_amount ?? 0,
      ),
      max_position_amount: Number(userResolved.max_position_amount ?? 0),
      max_position_count: Number(userResolved.max_position_count ?? 0),
      max_position_weight_pct: rateToPercent(userResolved.max_position_weight),
      daily_max_loss_amount: Number(userResolved.daily_max_loss_amount ?? 0),
      daily_max_loss_rate_pct: rateToPercent(userResolved.daily_max_loss_rate),
      stop_loss_rate_pct: rateToPercent(userResolved.stop_loss_rate),
      take_profit_rate_pct: rateToPercent(userResolved.take_profit_rate),
      trailing_stop_rate_pct: rateToPercent(userResolved.trailing_stop_rate),
      allow_duplicate_buy: Boolean(userResolved.allow_duplicate_buy),
      auto_trading_enabled: Boolean(userResolved.auto_trading_enabled),
      buy_enabled: Boolean(userResolved.buy_enabled),
      sell_enabled: Boolean(userResolved.sell_enabled),
      sell_only: Boolean(userResolved.sell_only),
      account_paused: Boolean(userResolved.account_paused),
    };
  }, [userResolved]);

  const accountInitialValues = useMemo(() => {
    if (!accountResolved) return undefined;
    return {
      max_order_amount: Number(accountResolved.max_order_amount ?? 0),
      stop_loss_rate_pct: rateToPercent(accountResolved.stop_loss_rate),
      take_profit_rate_pct: rateToPercent(accountResolved.take_profit_rate),
      trailing_stop_rate_pct: rateToPercent(accountResolved.trailing_stop_rate),
      auto_trading_enabled: Boolean(accountResolved.auto_trading_enabled),
      buy_enabled: Boolean(accountResolved.buy_enabled),
      sell_only: Boolean(accountResolved.sell_only),
      account_paused: Boolean(accountResolved.account_paused),
    };
  }, [accountResolved]);

  const saveUser = useMutation({
    mutationFn: (body: RiskSettingsPayload) =>
      userApi.updateMyRiskSettings(body),
    onSuccess: () => {
      message.success("사용자 리스크 설정을 저장했습니다.");
      void qc.invalidateQueries({ queryKey: queryKeys.user.riskSettings() });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const saveAccount = useMutation({
    mutationFn: (body: RiskSettingsPayload) =>
      userApi.updateAccountRiskSettings(activeUbaId!, body),
    onSuccess: () => {
      message.success("계좌 리스크 설정을 저장했습니다.");
      void qc.invalidateQueries({
        queryKey: queryKeys.user.accountRiskSettings(activeUbaId ?? 0),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const killSwitch = asRecord(killSwitchQuery.data);
  const isActive = Boolean(killSwitch?.is_active ?? killSwitch?.active);
  const resolved = asRecord(asRecord(riskQuery.data)?.resolved);

  return (
    <UserPageShell
      title="내 리스크"
      description="사용자·계좌 리스크 설정과 전역 킬스위치(읽기 전용)를 관리합니다. 비율은 %로 입력하며 API에는 fraction으로 저장됩니다."
      extra={
        <Space wrap>
          <Link href={userRoutes.portfolio}>
            <Button>내 잔고·손익</Button>
          </Link>
          <Link href={userRoutes.settings}>
            <Button>설정</Button>
          </Link>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          title="적용 우선순위"
          description="계좌 설정 → 사용자 기본 → 시스템 기본. Paper 주문은 사용자 기본+시스템만 적용됩니다."
        />

        {killSwitchQuery.error ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(killSwitchQuery.error).message}
          />
        ) : null}

        <Card
          title="전역 킬스위치 (읽기 전용)"
          size="small"
          loading={killSwitchQuery.isLoading}
        >
          <Descriptions column={1} size="small">
            <Descriptions.Item label="상태">
              <Tag color={isActive ? "red" : "green"}>
                {isActive ? "발동 (거래 중지)" : "정상"}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="사유">
              {String(killSwitch?.reason ?? killSwitch?.message ?? "-")}
            </Descriptions.Item>
          </Descriptions>
          <Button
            style={{ marginTop: 12 }}
            onClick={() => void killSwitchQuery.refetch()}
            loading={killSwitchQuery.isFetching}
          >
            상태 새로고침
          </Button>
        </Card>

        <Card title="계좌 LIVE 상태 (읽기 전용)" size="small" loading={liveStatusQuery.isLoading}>
          <Alert
            type="info"
            showIcon
            title="LIVE 실주문은 관리자 LIVE ON + ARM(5분) 후에만 가능합니다. 사용자는 ON/OFF·ARM을 변경할 수 없습니다."
            style={{ marginBottom: 12 }}
          />
          <Descriptions size="small" bordered column={1}>
            {(
              (asRecord(liveStatusQuery.data)?.accounts as
                | Record<string, unknown>[]
                | undefined) ?? []
            ).map((row) => (
              <Descriptions.Item
                key={String(row.user_broker_account_id)}
                label={`${String(row.broker_code)} #${String(row.user_broker_account_id)}`}
              >
                <Tag color={row.live_order_enabled ? "green" : "default"}>
                  {row.live_order_enabled ? "LIVE ON" : "LIVE OFF"}
                </Tag>
                <Tag
                  color={row.live_armed ? "processing" : "default"}
                  style={{ marginLeft: 4 }}
                >
                  {row.live_armed ? "ARMED" : "DISARMED"}
                </Tag>
                <span style={{ marginLeft: 8, fontSize: 12 }}>
                  expires={String(row.arm_expires_at ?? "-")} / max=
                  {String(asRecord(row.risk)?.max_order_amount ?? "-")} /
                  qty={String(asRecord(row.risk)?.max_order_quantity ?? "-")} /
                  daily={String(asRecord(row.risk)?.daily_order_limit ?? "-")}
                </span>
              </Descriptions.Item>
            ))}
          </Descriptions>
          <Descriptions
            size="small"
            bordered
            column={2}
            style={{ marginTop: 12 }}
            title="Post-Fill 검증 (읽기 전용)"
          >
            <Descriptions.Item label="Pending">
              {String(postFill?.pending ?? 0)}
            </Descriptions.Item>
            <Descriptions.Item label="Waiting Snapshot">
              {String(postFill?.waiting_snapshot ?? 0)}
            </Descriptions.Item>
            <Descriptions.Item label="Mismatch">
              {String(postFill?.mismatch ?? 0)}
            </Descriptions.Item>
            <Descriptions.Item label="Expired/Failed">
              {String(
                Number(postFill?.expired ?? 0) + Number(postFill?.failed ?? 0),
              )}
            </Descriptions.Item>
          </Descriptions>
        </Card>

        <Card
          title="사용자 기본 리스크 설정"
          size="small"
          extra={
            <span style={{ fontSize: 12, color: "rgba(0,0,0,0.45)" }}>
              layers: {String(resolved?.source_layers ?? "-")}
            </span>
          }
        >
          {riskQuery.error ? (
            <Alert
              type="error"
              showIcon
              title={toApiError(riskQuery.error).message}
              style={{ marginBottom: 12 }}
            />
          ) : null}
          <Form
            key={`user-risk-${riskQuery.dataUpdatedAt}`}
            form={form}
            layout="vertical"
            disabled={riskQuery.isLoading}
            initialValues={userInitialValues}
            onFinish={(values) => {
              saveUser.mutate({
                max_order_amount: values.max_order_amount,
                daily_max_order_amount: values.daily_max_order_amount,
                max_total_investment_amount: values.max_total_investment_amount,
                max_position_amount: values.max_position_amount,
                max_position_count: values.max_position_count,
                max_position_weight: percentToRate(values.max_position_weight_pct),
                daily_max_loss_amount: values.daily_max_loss_amount,
                daily_max_loss_rate: percentToRate(values.daily_max_loss_rate_pct),
                stop_loss_rate: percentToRate(values.stop_loss_rate_pct),
                take_profit_rate: percentToRate(values.take_profit_rate_pct),
                trailing_stop_rate: percentToRate(values.trailing_stop_rate_pct),
                allow_duplicate_buy: values.allow_duplicate_buy,
                auto_trading_enabled: values.auto_trading_enabled,
                buy_enabled: values.buy_enabled,
                sell_enabled: values.sell_enabled,
                sell_only: values.sell_only,
                account_paused: values.account_paused,
              });
            }}
          >
            <Space wrap size={16} style={{ width: "100%" }}>
              <Form.Item name="max_order_amount" label="1회 최대 주문금액">
                <InputNumber min={0} style={{ width: 180 }} />
              </Form.Item>
              <Form.Item name="daily_max_order_amount" label="일일 최대 주문금액">
                <InputNumber min={0} style={{ width: 180 }} />
              </Form.Item>
              <Form.Item
                name="max_total_investment_amount"
                label="계좌 최대 투자금액"
              >
                <InputNumber min={0} style={{ width: 180 }} />
              </Form.Item>
              <Form.Item name="max_position_amount" label="종목별 최대 투자금액">
                <InputNumber min={0} style={{ width: 180 }} />
              </Form.Item>
              <Form.Item name="max_position_count" label="최대 보유 종목 수">
                <InputNumber min={0} style={{ width: 120 }} />
              </Form.Item>
              <Form.Item name="max_position_weight_pct" label="종목 최대 비중(%)">
                <InputNumber min={0} max={100} style={{ width: 120 }} />
              </Form.Item>
              <Form.Item name="daily_max_loss_amount" label="일일 최대 손실금액">
                <InputNumber min={0} style={{ width: 180 }} />
              </Form.Item>
              <Form.Item name="daily_max_loss_rate_pct" label="일일 최대 손실률(%)">
                <InputNumber min={0} max={100} style={{ width: 120 }} />
              </Form.Item>
              <Form.Item name="stop_loss_rate_pct" label="손절률(%)">
                <InputNumber min={0} max={100} style={{ width: 120 }} />
              </Form.Item>
              <Form.Item name="take_profit_rate_pct" label="익절률(%)">
                <InputNumber min={0} max={100} style={{ width: 120 }} />
              </Form.Item>
              <Form.Item name="trailing_stop_rate_pct" label="트레일링 스톱(%)">
                <InputNumber min={0} max={100} style={{ width: 120 }} />
              </Form.Item>
            </Space>
            <Space wrap size={24}>
              <Form.Item
                name="allow_duplicate_buy"
                label="중복 매수 허용"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
              <Form.Item
                name="auto_trading_enabled"
                label="자동매매 허용"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
              <Form.Item name="buy_enabled" label="매수 허용" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item
                name="sell_enabled"
                label="매도 허용"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
              <Form.Item name="sell_only" label="매도 전용" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item
                name="account_paused"
                label="일시정지"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
            </Space>
            <Button
              type="primary"
              htmlType="submit"
              loading={saveUser.isPending}
              disabled={saveUser.isPending}
            >
              사용자 설정 저장
            </Button>
          </Form>
        </Card>

        <Card title="계좌별 리스크 설정 (키움·업비트)" size="small">
          {brokerAccounts.length === 0 ? (
            <>
              <Alert
                type="warning"
                showIcon
                title="연결된 실계좌가 없습니다."
                description={
                  <Link href={userRoutes.accounts}>내 계좌에서 키움/업비트 계좌를 연결하세요.</Link>
                }
              />
              <Form form={accountForm} style={{ display: "none" }} preserve={false} />
            </>
          ) : (
            <>
              <Select
                style={{ width: 360, marginBottom: 16 }}
                value={activeUbaId ?? undefined}
                options={brokerAccounts.map((row) => ({
                  value: row.account_id,
                  label: `${row.account_type} · ${row.account_name}${
                    row.masked_account_number
                      ? ` (${row.masked_account_number})`
                      : ""
                  }`,
                }))}
                onChange={(v: number) => setSelectedUbaId(v)}
              />
              {accountRiskQuery.error ? (
                <Alert
                  type="error"
                  showIcon
                  title={toApiError(accountRiskQuery.error).message}
                  style={{ marginBottom: 12 }}
                />
              ) : null}
              <Form
                key={`account-risk-${activeUbaId}-${accountRiskQuery.dataUpdatedAt}`}
                form={accountForm}
                layout="vertical"
                initialValues={accountInitialValues}
                onFinish={(values) => {
                  if (!activeUbaId) return;
                  saveAccount.mutate({
                    max_order_amount: values.max_order_amount,
                    stop_loss_rate: percentToRate(values.stop_loss_rate_pct),
                    take_profit_rate: percentToRate(values.take_profit_rate_pct),
                    trailing_stop_rate: percentToRate(
                      values.trailing_stop_rate_pct,
                    ),
                    auto_trading_enabled: values.auto_trading_enabled,
                    buy_enabled: values.buy_enabled,
                    sell_only: values.sell_only,
                    account_paused: values.account_paused,
                  });
                }}
              >
                <Space wrap>
                  <Form.Item name="max_order_amount" label="1회 최대 주문금액">
                    <InputNumber min={0} style={{ width: 180 }} />
                  </Form.Item>
                  <Form.Item name="stop_loss_rate_pct" label="손절률(%)">
                    <InputNumber min={0} max={100} style={{ width: 120 }} />
                  </Form.Item>
                  <Form.Item name="take_profit_rate_pct" label="익절률(%)">
                    <InputNumber min={0} max={100} style={{ width: 120 }} />
                  </Form.Item>
                  <Form.Item name="trailing_stop_rate_pct" label="트레일링(%)">
                    <InputNumber min={0} max={100} style={{ width: 120 }} />
                  </Form.Item>
                  <Form.Item
                    name="auto_trading_enabled"
                    label="자동매매"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    name="buy_enabled"
                    label="매수 허용"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    name="sell_only"
                    label="매도 전용"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    name="account_paused"
                    label="일시정지"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                </Space>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={saveAccount.isPending}
                  disabled={saveAccount.isPending || !activeUbaId}
                >
                  계좌 설정 저장
                </Button>
              </Form>
            </>
          )}
        </Card>
      </Space>
    </UserPageShell>
  );
}
