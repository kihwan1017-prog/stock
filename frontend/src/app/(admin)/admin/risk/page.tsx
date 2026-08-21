"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  InputNumber,
  Space,
  Switch,
  Tag,
} from "antd";
import { useMemo, useState } from "react";
import Link from "next/link";

import { adminRoutes } from "@/config/routes";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { asRecord, cell, extractRows } from "@/shared/utils/dataHelpers";
import { percentToRate, rateToPercent } from "@/shared/utils/riskRatePercent";

export default function AdminRiskPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [systemForm] = Form.useForm();
  const [userForm] = Form.useForm();
  const [targetUserId, setTargetUserId] = useState<number>(1);

  const kill = useQuery({
    queryKey: queryKeys.admin.killSwitch(),
    queryFn: adminApi.getKillSwitch,
  });
  const daily = useQuery({
    queryKey: queryKeys.admin.dailyLoss(),
    queryFn: adminApi.getDailyLossStatus,
  });
  const policies = useQuery({
    queryKey: queryKeys.admin.riskPolicies(),
    queryFn: adminApi.listRiskPolicies,
  });
  const dash = useQuery({
    queryKey: queryKeys.dashboard.risk(),
    queryFn: () => adminApi.getRiskDashboard(),
  });
  const systemRisk = useQuery({
    queryKey: queryKeys.admin.systemRiskSettings(),
    queryFn: adminApi.getSystemRiskSettings,
  });
  const userRisk = useQuery({
    queryKey: queryKeys.admin.userRiskSettings(targetUserId),
    queryFn: () => adminApi.getAdminUserRiskSettings(targetUserId),
    enabled: targetUserId > 0,
  });
  const liveAccounts = useQuery({
    queryKey: queryKeys.admin.liveOrderAccounts(targetUserId),
    queryFn: () => adminApi.listAdminLiveOrderAccounts(targetUserId),
    enabled: targetUserId > 0,
  });

  const systemResolved = asRecord(asRecord(systemRisk.data)?.resolved);
  const userResolved = asRecord(asRecord(userRisk.data)?.resolved);

  const systemInitialValues = useMemo(() => {
    if (!systemResolved) return undefined;
    return {
      max_order_amount: Number(systemResolved.max_order_amount ?? 0),
      daily_max_order_amount: Number(systemResolved.daily_max_order_amount ?? 0),
      max_total_investment_amount: Number(
        systemResolved.max_total_investment_amount ?? 0,
      ),
      max_position_count: Number(systemResolved.max_position_count ?? 0),
      stop_loss_rate_pct: rateToPercent(systemResolved.stop_loss_rate),
      take_profit_rate_pct: rateToPercent(systemResolved.take_profit_rate),
      trailing_stop_rate_pct: rateToPercent(systemResolved.trailing_stop_rate),
      auto_trading_enabled: Boolean(systemResolved.auto_trading_enabled),
      buy_enabled: Boolean(systemResolved.buy_enabled),
      sell_only: Boolean(systemResolved.sell_only),
    };
  }, [systemResolved]);

  const userInitialValues = useMemo(() => {
    if (!userResolved) return undefined;
    return {
      max_order_amount: Number(userResolved.max_order_amount ?? 0),
      stop_loss_rate_pct: rateToPercent(userResolved.stop_loss_rate),
      take_profit_rate_pct: rateToPercent(userResolved.take_profit_rate),
      auto_trading_enabled: Boolean(userResolved.auto_trading_enabled),
      buy_enabled: Boolean(userResolved.buy_enabled),
      sell_only: Boolean(userResolved.sell_only),
      account_paused: Boolean(userResolved.account_paused),
    };
  }, [userResolved]);

  const activate = useMutation({
    mutationFn: () => adminApi.activateKillSwitch(),
    onSuccess: () => {
      message.success("Kill Switch 활성화");
      void qc.invalidateQueries({ queryKey: queryKeys.admin.killSwitch() });
    },
    onError: (e) => message.error(toApiError(e).message),
  });
  const deactivate = useMutation({
    mutationFn: () => adminApi.deactivateKillSwitch(),
    onSuccess: () => {
      message.success("Kill Switch 해제");
      void qc.invalidateQueries({ queryKey: queryKeys.admin.killSwitch() });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const saveSystem = useMutation({
    mutationFn: adminApi.updateSystemRiskSettings,
    onSuccess: () => {
      message.success("시스템 리스크 정책 저장");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.systemRiskSettings(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const saveUser = useMutation({
    mutationFn: (body: adminApi.AdminRiskSettingsPayload) =>
      adminApi.updateAdminUserRiskSettings(targetUserId, body),
    onSuccess: () => {
      message.success("사용자 리스크 설정 저장");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.userRiskSettings(targetUserId),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const setFlags = useMutation({
    mutationFn: (body: {
      buy_enabled?: boolean;
      sell_only?: boolean;
      auto_trading_enabled?: boolean;
    }) => adminApi.setAdminUserTradingFlags(targetUserId, body),
    onSuccess: () => {
      message.success("거래 플래그 반영");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.userRiskSettings(targetUserId),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  // M4-C2-APPLY: LIVE/ARM mutation은 /admin/accounts canonical만. 여기서는 한도·status만.
  const saveLiveLimits = useMutation({
    mutationFn: (args: {
      ubaId: number;
      body: {
        max_order_amount?: number;
        max_order_quantity?: number;
        daily_order_limit?: number;
        daily_max_loss_amount?: number;
      };
    }) => adminApi.updateAdminLiveRiskLimits(args.ubaId, args.body),
    onSuccess: () => {
      message.success("계좌 LIVE 한도 저장");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.liveOrderAccounts(targetUserId),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const liveAccountRows = extractRows(
    asRecord(liveAccounts.data)?.accounts ?? liveAccounts.data,
  );

  return (
    <AdminPageShell
      title="리스크 관리"
      description="Kill Switch와 시스템/회원 리스크 설정의 canonical 화면입니다. 거래 운영 현황은 조회 전용 요약입니다."
      extra={
        <Space wrap>
          <Button danger loading={activate.isPending} onClick={() => activate.mutate()}>
            Kill Switch ON
          </Button>
          <Button loading={deactivate.isPending} onClick={() => deactivate.mutate()}>
            Kill Switch OFF
          </Button>
          <Link href={adminRoutes.operationsDashboard}>거래 운영 현황</Link>
          <Link href={adminRoutes.operations}>시스템 운영</Link>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          message="Account Safety vs Strategy Autotrading"
          description="Account Daily Drawdown(계좌 전체 MTM)과 Strategy Daily Loss(자동매매 소유만)는 분리됩니다. ENTRY는 Strategy Daily Loss + Account Hard Safety(Kill 등) 모두 PASS 필요. GET /api/v1/risk/daily-loss/strategy-owned"
        />
        <AdminJsonCard
          title="GET /risk/kill-switch"
          loading={kill.isLoading}
          error={kill.error ? toApiError(kill.error) : null}
          data={kill.data}
        />
        <AdminJsonCard
          title="GET /risk/daily-loss/status"
          loading={daily.isLoading}
          error={daily.error ? toApiError(daily.error) : null}
          data={daily.data}
        />

        <Card title="시스템 기본 리스크 정책" size="small">
          <Form
            key={`system-risk-${systemRisk.dataUpdatedAt}`}
            form={systemForm}
            layout="vertical"
            disabled={systemRisk.isLoading}
            initialValues={systemInitialValues}
            onFinish={(values) => {
              saveSystem.mutate({
                max_order_amount: values.max_order_amount,
                daily_max_order_amount: values.daily_max_order_amount,
                max_total_investment_amount: values.max_total_investment_amount,
                max_position_count: values.max_position_count,
                stop_loss_rate: percentToRate(values.stop_loss_rate_pct),
                take_profit_rate: percentToRate(values.take_profit_rate_pct),
                trailing_stop_rate: percentToRate(values.trailing_stop_rate_pct),
                auto_trading_enabled: values.auto_trading_enabled,
                buy_enabled: values.buy_enabled,
                sell_only: values.sell_only,
              });
            }}
          >
            <Space wrap>
              <Form.Item name="max_order_amount" label="1회 최대 주문금액">
                <InputNumber min={0} style={{ width: 160 }} />
              </Form.Item>
              <Form.Item name="daily_max_order_amount" label="일일 최대 주문금액">
                <InputNumber min={0} style={{ width: 160 }} />
              </Form.Item>
              <Form.Item
                name="max_total_investment_amount"
                label="최대 투자금액"
              >
                <InputNumber min={0} style={{ width: 160 }} />
              </Form.Item>
              <Form.Item name="max_position_count" label="최대 보유 수">
                <InputNumber min={0} style={{ width: 120 }} />
              </Form.Item>
              <Form.Item name="stop_loss_rate_pct" label="손절(%)">
                <InputNumber min={0} max={100} style={{ width: 100 }} />
              </Form.Item>
              <Form.Item name="take_profit_rate_pct" label="익절(%)">
                <InputNumber min={0} max={100} style={{ width: 100 }} />
              </Form.Item>
              <Form.Item name="trailing_stop_rate_pct" label="트레일링(%)">
                <InputNumber min={0} max={100} style={{ width: 100 }} />
              </Form.Item>
              <Form.Item
                name="auto_trading_enabled"
                label="자동매매"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
              <Form.Item name="buy_enabled" label="매수" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item name="sell_only" label="매도 전용" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Space>
            <Button
              type="primary"
              htmlType="submit"
              loading={saveSystem.isPending}
              disabled={saveSystem.isPending}
            >
              시스템 정책 저장
            </Button>
          </Form>
        </Card>

        <Card title="회원별 리스크·거래 플래그" size="small">
          <Space style={{ marginBottom: 12 }}>
            <span>user_id</span>
            <InputNumber
              min={1}
              value={targetUserId}
              onChange={(v) => setTargetUserId(Number(v ?? 1))}
            />
            <Button onClick={() => void userRisk.refetch()} loading={userRisk.isFetching}>
              조회
            </Button>
            <Button
              danger
              loading={setFlags.isPending}
              onClick={() => setFlags.mutate({ buy_enabled: false })}
            >
              매수 차단
            </Button>
            <Button
              loading={setFlags.isPending}
              onClick={() => setFlags.mutate({ sell_only: true, buy_enabled: false })}
            >
              매도 전용
            </Button>
            <Button
              loading={setFlags.isPending}
              onClick={() => setFlags.mutate({ auto_trading_enabled: false })}
            >
              자동매매 중지
            </Button>
          </Space>
          <Form
            key={`user-risk-${targetUserId}-${userRisk.dataUpdatedAt}`}
            form={userForm}
            layout="vertical"
            initialValues={userInitialValues}
            onFinish={(values) => {
              saveUser.mutate({
                max_order_amount: values.max_order_amount,
                stop_loss_rate: percentToRate(values.stop_loss_rate_pct),
                take_profit_rate: percentToRate(values.take_profit_rate_pct),
                auto_trading_enabled: values.auto_trading_enabled,
                buy_enabled: values.buy_enabled,
                sell_only: values.sell_only,
                account_paused: values.account_paused,
              });
            }}
          >
            <Space wrap>
              <Form.Item name="max_order_amount" label="1회 최대 주문금액">
                <InputNumber min={0} style={{ width: 160 }} />
              </Form.Item>
              <Form.Item name="stop_loss_rate_pct" label="손절(%)">
                <InputNumber min={0} max={100} style={{ width: 100 }} />
              </Form.Item>
              <Form.Item name="take_profit_rate_pct" label="익절(%)">
                <InputNumber min={0} max={100} style={{ width: 100 }} />
              </Form.Item>
              <Form.Item
                name="auto_trading_enabled"
                label="자동매매"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
              <Form.Item name="buy_enabled" label="매수" valuePropName="checked">
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

        <Card
          title="계좌 LIVE/ARM 상태 · 한도 (조회 + 한도만)"
          size="small"
          extra={
            <Link href={adminRoutes.accounts}>계좌 LIVE 제어</Link>
          }
        >
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            title="LIVE/ARM 및 Trading Scheduler 제어는 계좌 관리에서 수행합니다."
            description="이 화면은 상태 조회와 LIVE 리스크 한도 재적용만 제공합니다. Kill Switch는 위쪽 Risk 제어를 사용하세요."
          />
          <AdminDataTable
            title={`GET /admin/live-order/users/${targetUserId}/accounts`}
            loading={liveAccounts.isLoading}
            error={
              liveAccounts.error ? toApiError(liveAccounts.error) : null
            }
            rowKey={(r) =>
              String(r.user_broker_account_id ?? r.account_id ?? JSON.stringify(r))
            }
            columns={[
              {
                title: "UBA",
                dataIndex: "user_broker_account_id",
              },
              { title: "broker", dataIndex: "broker_code" },
              { title: "alias", dataIndex: "account_alias" },
              {
                title: "LIVE",
                key: "live",
                render: (_: unknown, row: Record<string, unknown>) => (
                  <Tag color={row.live_order_enabled ? "green" : "default"}>
                    {row.live_order_enabled ? "ON" : "OFF"}
                  </Tag>
                ),
              },
              {
                title: "ARM",
                key: "arm",
                render: (_: unknown, row: Record<string, unknown>) => {
                  const armed = Boolean(row.live_armed);
                  const expires = cell(row.arm_expires_at);
                  return (
                    <span style={{ fontSize: 12 }}>
                      {armed ? `ARMED (~${expires})` : "DISARMED"}
                    </span>
                  );
                },
              },
              {
                title: "한도",
                key: "limits",
                render: (_: unknown, row: Record<string, unknown>) => {
                  const risk = asRecord(row.risk) ?? {};
                  return (
                    <Button
                      size="small"
                      loading={saveLiveLimits.isPending}
                      onClick={() =>
                        saveLiveLimits.mutate({
                          ubaId: Number(row.user_broker_account_id),
                          body: {
                            max_order_amount: Number(
                              risk.max_order_amount ?? 50000,
                            ),
                            max_order_quantity: Number(
                              risk.max_order_quantity ?? 100,
                            ),
                            daily_order_limit: Number(
                              risk.daily_order_limit ?? 20,
                            ),
                            daily_max_loss_amount: Number(
                              risk.daily_max_loss_amount ?? 30000,
                            ),
                          },
                        })
                      }
                    >
                      한도 재적용
                    </Button>
                  );
                },
              },
              {
                title: "max_amount",
                key: "max_amount",
                render: (_: unknown, row: Record<string, unknown>) =>
                  cell(asRecord(row.risk)?.max_order_amount),
              },
              {
                title: "max_qty",
                key: "max_qty",
                render: (_: unknown, row: Record<string, unknown>) =>
                  cell(asRecord(row.risk)?.max_order_quantity),
              },
              {
                title: "daily_orders (legacy)",
                key: "daily_orders",
                render: (_: unknown, row: Record<string, unknown>) =>
                  cell(asRecord(row.risk)?.daily_order_limit),
              },
              {
                title: "submit/filled V2",
                key: "order_limit_v2",
                render: (_: unknown, row: Record<string, unknown>) => {
                  const risk = asRecord(row.risk) ?? {};
                  const submit = risk.daily_submit_limit;
                  const filled = risk.daily_filled_entry_limit;
                  if (submit == null && filled == null) {
                    return (
                      <span style={{ fontSize: 11, color: "#888" }}>
                        recommended 5/1 (not applied)
                      </span>
                    );
                  }
                  return (
                    <span style={{ fontSize: 12 }}>
                      submit {cell(submit)} / filled {cell(filled)}
                    </span>
                  );
                },
              },
              {
                title: "daily_loss",
                key: "daily_loss",
                render: (_: unknown, row: Record<string, unknown>) =>
                  cell(asRecord(row.risk)?.daily_max_loss_amount),
              },
            ]}
            dataSource={liveAccountRows}
          />
        </Card>

        <AdminDataTable
          title="GET /risk-policies"
          loading={policies.isLoading}
          error={policies.error ? toApiError(policies.error) : null}
          rowKey={(r) => cell(r.policy_id ?? r.policy_name ?? JSON.stringify(r))}
          columns={[
            { title: "policy_id", dataIndex: "policy_id", sorter: true },
            { title: "name", dataIndex: "policy_name" },
            { title: "mode", dataIndex: "position_sizing_mode" },
            { title: "stop_loss", dataIndex: "stop_loss_ratio" },
          ]}
          dataSource={extractRows(policies.data)}
        />
        <AdminJsonCard
          title="GET /dashboard/risk"
          loading={dash.isLoading}
          error={dash.error ? toApiError(dash.error) : null}
          data={dash.data}
        />
      </Space>
    </AdminPageShell>
  );
}
