"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Form,
  InputNumber,
  Space,
  Switch,
} from "antd";
import { useEffect, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

function rateToPercent(value: unknown): number | undefined {
  if (value == null || value === "") return undefined;
  const n = Number(value);
  if (Number.isNaN(n)) return undefined;
  return Number((n * 100).toFixed(4));
}

function percentToRate(value: number | null | undefined): number | null {
  if (value == null) return null;
  return Number((value / 100).toFixed(6));
}

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

  useEffect(() => {
    const resolved = asRecord(asRecord(systemRisk.data)?.resolved);
    if (!resolved) return;
    systemForm.setFieldsValue({
      max_order_amount: Number(resolved.max_order_amount ?? 0),
      daily_max_order_amount: Number(resolved.daily_max_order_amount ?? 0),
      max_total_investment_amount: Number(
        resolved.max_total_investment_amount ?? 0,
      ),
      max_position_count: Number(resolved.max_position_count ?? 0),
      stop_loss_rate_pct: rateToPercent(resolved.stop_loss_rate),
      take_profit_rate_pct: rateToPercent(resolved.take_profit_rate),
      trailing_stop_rate_pct: rateToPercent(resolved.trailing_stop_rate),
      auto_trading_enabled: Boolean(resolved.auto_trading_enabled),
      buy_enabled: Boolean(resolved.buy_enabled),
      sell_only: Boolean(resolved.sell_only),
    });
  }, [systemRisk.data, systemForm]);

  useEffect(() => {
    const resolved = asRecord(asRecord(userRisk.data)?.resolved);
    if (!resolved) return;
    userForm.setFieldsValue({
      max_order_amount: Number(resolved.max_order_amount ?? 0),
      stop_loss_rate_pct: rateToPercent(resolved.stop_loss_rate),
      take_profit_rate_pct: rateToPercent(resolved.take_profit_rate),
      auto_trading_enabled: Boolean(resolved.auto_trading_enabled),
      buy_enabled: Boolean(resolved.buy_enabled),
      sell_only: Boolean(resolved.sell_only),
      account_paused: Boolean(resolved.account_paused),
    });
  }, [userRisk.data, userForm]);

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

  const toggleLive = useMutation({
    mutationFn: (args: { ubaId: number; enabled: boolean }) =>
      adminApi.setAdminLiveOrderEnabled(args.ubaId, args.enabled),
    onSuccess: (_, vars) => {
      message.success(vars.enabled ? "LIVE 승인 ON" : "LIVE 승인 OFF");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.liveOrderAccounts(targetUserId),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

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

  // STEP 8-8 — ARM / DISARM (5분 토큰)
  const armLive = useMutation({
    mutationFn: (ubaId: number) => adminApi.armAdminLiveOrder(ubaId),
    onSuccess: (data) => {
      const token = String(asRecord(data)?.arm_token ?? "");
      message.success(
        token
          ? `ARM 완료 — token 앞 8자: ${token.slice(0, 8)}…`
          : "ARM 완료",
      );
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.liveOrderAccounts(targetUserId),
      });
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.liveOpsDashboard(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });
  const disarmLive = useMutation({
    mutationFn: (args: { ubaId: number; turnLiveOff?: boolean }) =>
      adminApi.disarmAdminLiveOrder(args.ubaId, {
        turn_live_off: args.turnLiveOff ?? false,
        reason: "MANUAL",
      }),
    onSuccess: () => {
      message.success("DISARM 완료");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.liveOrderAccounts(targetUserId),
      });
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.liveOpsDashboard(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const liveAccountRows = extractRows(
    asRecord(liveAccounts.data)?.accounts ?? liveAccounts.data,
  );

  return (
    <AdminPageShell
      title="Risk 관리"
      description="kill-switch · 시스템/회원 리스크 설정 · daily-loss · risk-policies"
      extra={
        <Space>
          <Button danger loading={activate.isPending} onClick={() => activate.mutate()}>
            Kill Switch ON
          </Button>
          <Button loading={deactivate.isPending} onClick={() => deactivate.mutate()}>
            Kill Switch OFF
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
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

        <Card title="시스템 기본 리스크 정책" size="small" loading={systemRisk.isLoading}>
          <Form
            form={systemForm}
            layout="vertical"
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
            form={userForm}
            layout="vertical"
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

        <Card title="STEP 8-7/8-8 — 계좌 LIVE 승인·ARM·한도" size="small">
          <p style={{ marginBottom: 12 }}>
            LIVE ON만으로는 주문 불가합니다. 관리자 ARM(기본 5분) + arm_token이
            있어야 실주문이 허용되며, 만료 시 자동 LIVE OFF됩니다.
          </p>
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
                  <Switch
                    checked={Boolean(row.live_order_enabled)}
                    loading={toggleLive.isPending}
                    onChange={(enabled) =>
                      toggleLive.mutate({
                        ubaId: Number(row.user_broker_account_id),
                        enabled,
                      })
                    }
                  />
                ),
              },
              {
                title: "ARM",
                key: "arm",
                render: (_: unknown, row: Record<string, unknown>) => {
                  const armed = Boolean(row.live_armed);
                  const expires = cell(row.arm_expires_at);
                  return (
                    <Space orientation="vertical" size={4}>
                      <span style={{ fontSize: 12 }}>
                        {armed ? `ARMED (~${expires})` : "DISARMED"}
                      </span>
                      <Space size={4} wrap>
                        <Button
                          size="small"
                          type="primary"
                          disabled={!row.live_order_enabled}
                          loading={armLive.isPending}
                          onClick={() =>
                            armLive.mutate(
                              Number(row.user_broker_account_id),
                            )
                          }
                        >
                          ARM
                        </Button>
                        <Button
                          size="small"
                          danger
                          loading={disarmLive.isPending}
                          onClick={() =>
                            disarmLive.mutate({
                              ubaId: Number(row.user_broker_account_id),
                              turnLiveOff: false,
                            })
                          }
                        >
                          DISARM
                        </Button>
                      </Space>
                    </Space>
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
                title: "daily_orders",
                key: "daily_orders",
                render: (_: unknown, row: Record<string, unknown>) =>
                  cell(asRecord(row.risk)?.daily_order_limit),
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
