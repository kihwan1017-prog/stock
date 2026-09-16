"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  InputNumber,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";
import Link from "next/link";

import { adminRoutes } from "@/config/routes";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { MetricProgress, StatusSummaryCard } from "@/features/admin/ops-ux";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { asRecord, cell, extractRows } from "@/shared/utils/dataHelpers";
import { percentToRate, rateToPercent } from "@/shared/utils/riskRatePercent";

const EXIT_MODE_OPTIONS = [
  { value: "INHERIT", label: "상위 설정 사용" },
  { value: "ENABLED", label: "사용" },
  { value: "DISABLED", label: "사용 안 함" },
];

export default function AdminRiskPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [systemForm] = Form.useForm();
  const [userForm] = Form.useForm();
  const [ubaExitForm] = Form.useForm();
  const [targetUserId, setTargetUserId] = useState<number>(1);
  const [targetUbaId, setTargetUbaId] = useState<number>(1380);

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
  const ubaRisk = useQuery({
    queryKey: ["admin", "accountRiskSettings", targetUbaId],
    queryFn: () => adminApi.getAdminAccountRiskSettings(targetUbaId),
    enabled: targetUbaId > 0,
  });

  const systemResolved = asRecord(asRecord(systemRisk.data)?.resolved);
  const userResolved = asRecord(asRecord(userRisk.data)?.resolved);
  const ubaStored = asRecord(asRecord(ubaRisk.data)?.stored);
  const ubaResolved = asRecord(asRecord(ubaRisk.data)?.resolved);
  const ubaExitProtection = asRecord(ubaResolved?.exit_protection);

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

  const ubaExitInitialValues = useMemo(() => {
    const stored = ubaStored ?? {};
    const maxHoldSeconds =
      stored.max_hold_seconds != null
        ? Number(stored.max_hold_seconds)
        : null;
    return {
      stop_loss_mode: String(stored.stop_loss_mode ?? "INHERIT"),
      take_profit_mode: String(stored.take_profit_mode ?? "INHERIT"),
      trailing_stop_mode: String(stored.trailing_stop_mode ?? "INHERIT"),
      stop_loss_rate_pct: rateToPercent(stored.stop_loss_rate),
      take_profit_rate_pct: rateToPercent(stored.take_profit_rate),
      trailing_stop_rate_pct: rateToPercent(stored.trailing_stop_rate),
      trailing_activation_rate_pct: rateToPercent(
        stored.trailing_activation_rate,
      ),
      max_hold_mode: String(stored.max_hold_mode ?? "INHERIT"),
      // UI는 시간(h) — 저장 시 seconds로 변환
      max_hold_hours:
        maxHoldSeconds != null && Number.isFinite(maxHoldSeconds)
          ? maxHoldSeconds / 3600
          : null,
    };
  }, [ubaStored]);

  const activate = useMutation({
    mutationFn: () => adminApi.activateKillSwitch(),
    onSuccess: () => {
      message.success("긴급 중지(Kill Switch) 활성화");
      void qc.invalidateQueries({ queryKey: queryKeys.admin.killSwitch() });
    },
    onError: (e) => message.error(toApiError(e).message),
  });
  const deactivate = useMutation({
    mutationFn: () => adminApi.deactivateKillSwitch(),
    onSuccess: () => {
      message.success("긴급 중지(Kill Switch) 해제");
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

  const saveUbaExit = useMutation({
    mutationFn: (body: adminApi.AdminRiskSettingsPayload) =>
      adminApi.updateAdminAccountRiskSettings(targetUbaId, body),
    onSuccess: () => {
      message.success("UBA REAL exit protection 저장");
      void qc.invalidateQueries({
        queryKey: ["admin", "accountRiskSettings", targetUbaId],
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
        daily_submit_limit?: number | null;
        daily_filled_entry_limit?: number | null;
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

  // Order Limit V2 draft — 저장 버튼 누르기 전까지 DB 미반영 (recommended 5/1 자동적용 금지)
  const [v2Drafts, setV2Drafts] = useState<
    Record<number, { submit?: number | null; filled?: number | null }>
  >({});

  const saveOrderLimitV2 = useMutation({
    mutationFn: (args: {
      ubaId: number;
      daily_submit_limit: number;
      daily_filled_entry_limit: number;
    }) =>
      adminApi.updateAdminLiveRiskLimits(args.ubaId, {
        daily_submit_limit: args.daily_submit_limit,
        daily_filled_entry_limit: args.daily_filled_entry_limit,
      }),
    onSuccess: (_data, vars) => {
      message.success(
        `UBA ${vars.ubaId} Order Limit V2 저장 (submit=${vars.daily_submit_limit}, filled=${vars.daily_filled_entry_limit})`,
      );
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.liveOrderAccounts(targetUserId),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const liveAccountRows = extractRows(
    asRecord(liveAccounts.data)?.accounts ?? liveAccounts.data,
  );

  const killActive =
    String(asRecord(kill.data)?.status ?? "").toUpperCase() === "ACTIVE";
  const dailyRec = asRecord(daily.data);
  const dailyUsed = Number(dailyRec?.used_loss ?? dailyRec?.current_loss ?? 0);
  const dailyLimit = Number(
    dailyRec?.limit ?? dailyRec?.max_loss ?? systemResolved?.daily_max_order_amount ?? 0,
  );
  const maxOrder = Number(systemResolved?.max_order_amount ?? 0);
  const maxPos = Number(systemResolved?.max_position_count ?? 0);
  const maxInvest = Number(systemResolved?.max_total_investment_amount ?? 0);

  return (
    <AdminPageShell
      title="리스크"
      description="현재 위험 상태와 한도를 먼저 확인한 뒤, 아래에서 정책 값을 변경합니다. LIVE/ARM 제어는 계좌·안전 제어 화면이 PRIMARY입니다."
      extra={
        <Space wrap>
          <Button danger loading={activate.isPending} onClick={() => activate.mutate()}>
            긴급 중지 켜기
          </Button>
          <Button loading={deactivate.isPending} onClick={() => deactivate.mutate()}>
            긴급 중지 끄기
          </Button>
          <Link href={adminRoutes.liveValidationUpbit}>안전 제어 →</Link>
          <Link href={adminRoutes.accounts}>계좌 →</Link>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <StatusSummaryCard
          title="긴급 중지"
          statusLabel={killActive ? "거래 차단 중" : "정상 (꺼짐)"}
          tone={killActive ? "error" : "success"}
          description={
            killActive
              ? "Kill Switch가 켜져 있어 신규 주문이 차단될 수 있습니다."
              : "Kill Switch가 꺼진 상태입니다. 실제 주문은 LIVE·ARM·계좌 상태를 함께 확인하세요."
          }
          href={adminRoutes.liveValidationUpbit}
          linkLabel="안전 제어에서 거래 가능 여부 확인 →"
        />

        <Card size="small" title="현재 한도 (시스템 정책)">
          <Space orientation="vertical" size={8} style={{ width: "100%" }}>
            {dailyLimit > 0 ? (
              <MetricProgress
                label="일일 손실 한도"
                used={Number.isFinite(dailyUsed) ? Math.abs(dailyUsed) : 0}
                limit={dailyLimit}
                formatValue={(n) => `${Math.round(n).toLocaleString("ko-KR")}원`}
              />
            ) : (
              <Alert
                type="info"
                showIcon
                title="일일 손실 사용량"
                description="일일 손실 한도 수치가 아직 없습니다. 아래 정책에서 설정값을 확인하세요."
              />
            )}
            <MetricProgress
              label="1회 최대 주문"
              used={0}
              limit={maxOrder > 0 ? maxOrder : 1}
              formatValue={(n) =>
                maxOrder > 0 ? `${Math.round(n).toLocaleString("ko-KR")}원` : "—"
              }
            />
            <MetricProgress
              label="최대 투자금액"
              used={0}
              limit={maxInvest > 0 ? maxInvest : 1}
              formatValue={(n) =>
                maxInvest > 0 ? `${Math.round(n).toLocaleString("ko-KR")}원` : "—"
              }
            />
            <MetricProgress
              label="최대 보유 종목 수"
              used={0}
              limit={maxPos > 0 ? maxPos : 1}
              formatValue={(n) => (maxPos > 0 ? String(n) : "—")}
            />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              사용량은 가능한 API 값만 표시합니다. 잔여 한도·실시간 exposure는 자동매매·보유자산
              화면에서 확인하세요.
            </Typography.Text>
          </Space>
        </Card>

        <Alert
          type="info"
          showIcon
          title="계좌 안전 vs 전략 자동매매"
          description="계좌 일일 최대 손실(계좌 전체 평가)과 전략 일일 손실(자동매매 소유만)은 분리됩니다. 신규 매수는 전략 일일 손실 + 계좌 하드 안전(긴급 중지 등) 모두 통과해야 합니다."
        />
        <AdminJsonCard
          title="긴급 중지 상세 (고급)"
          loading={kill.isLoading}
          error={kill.error ? toApiError(kill.error) : null}
          data={kill.data}
        />
        <AdminJsonCard
          title="일일 손실 상태 상세 (고급)"
          loading={daily.isLoading}
          error={daily.error ? toApiError(daily.error) : null}
          data={daily.data}
        />

        <Card title="시스템 기본 리스크 정책 설정" size="small">
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

        <Card title="UBA REAL Exit Protection (tri-state)" size="small">
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            title="NULL rate ≠ 비활성. 모드로 REAL executor를 제어합니다."
            description="DISABLED면 SYSTEM DEFAULT(5%/10%/3%)가 있어도 REAL SL/TP/Trailing을 쓰지 않습니다. Shadow 수집은 별도입니다."
          />
          <Space wrap style={{ marginBottom: 12 }}>
            <span>uba_id</span>
            <InputNumber
              min={1}
              value={targetUbaId}
              onChange={(v) => setTargetUbaId(Number(v ?? 1380))}
            />
            <Button onClick={() => void ubaRisk.refetch()} loading={ubaRisk.isFetching}>
              조회
            </Button>
            {ubaExitProtection ? (
              <Typography.Text type="secondary">
                effective SL={String(asRecord(ubaExitProtection.stop_loss)?.mode ?? "—")} /
                TP={String(asRecord(ubaExitProtection.take_profit)?.mode ?? "—")} /
                TR={String(asRecord(ubaExitProtection.trailing_stop)?.mode ?? "—")} /
                MH={String(asRecord(ubaExitProtection.max_hold)?.mode ?? "—")}
              </Typography.Text>
            ) : null}
          </Space>
          <Form
            key={`uba-exit-${targetUbaId}-${ubaRisk.dataUpdatedAt}`}
            form={ubaExitForm}
            layout="vertical"
            initialValues={ubaExitInitialValues}
            onFinish={(values) => {
              const maxHoldHours =
                values.max_hold_hours != null
                  ? Number(values.max_hold_hours)
                  : null;
              saveUbaExit.mutate({
                stop_loss_mode: values.stop_loss_mode,
                take_profit_mode: values.take_profit_mode,
                trailing_stop_mode: values.trailing_stop_mode,
                stop_loss_rate:
                  values.stop_loss_mode === "ENABLED"
                    ? percentToRate(values.stop_loss_rate_pct)
                    : null,
                take_profit_rate:
                  values.take_profit_mode === "ENABLED"
                    ? percentToRate(values.take_profit_rate_pct)
                    : null,
                trailing_stop_rate:
                  values.trailing_stop_mode === "ENABLED"
                    ? percentToRate(values.trailing_stop_rate_pct)
                    : null,
                trailing_activation_rate: percentToRate(
                  values.trailing_activation_rate_pct,
                ),
                max_hold_mode: values.max_hold_mode,
                max_hold_seconds:
                  values.max_hold_mode === "ENABLED" &&
                  maxHoldHours != null &&
                  Number.isFinite(maxHoldHours)
                    ? Math.round(maxHoldHours * 3600)
                    : null,
              });
            }}
          >
            <Space wrap align="start">
              <Form.Item name="stop_loss_mode" label="손절 설정 방식">
                <Select options={EXIT_MODE_OPTIONS} style={{ width: 160 }} />
              </Form.Item>
              <Form.Item
                noStyle
                shouldUpdate={(prev, cur) => prev.stop_loss_mode !== cur.stop_loss_mode}
              >
                {({ getFieldValue }) => (
                  <Form.Item name="stop_loss_rate_pct" label="손절(%)">
                    <InputNumber
                      min={0}
                      max={100}
                      style={{ width: 100 }}
                      disabled={getFieldValue("stop_loss_mode") !== "ENABLED"}
                    />
                  </Form.Item>
                )}
              </Form.Item>
              <Form.Item name="take_profit_mode" label="익절 설정 방식">
                <Select options={EXIT_MODE_OPTIONS} style={{ width: 160 }} />
              </Form.Item>
              <Form.Item
                noStyle
                shouldUpdate={(prev, cur) =>
                  prev.take_profit_mode !== cur.take_profit_mode
                }
              >
                {({ getFieldValue }) => (
                  <Form.Item name="take_profit_rate_pct" label="익절(%)">
                    <InputNumber
                      min={0}
                      max={100}
                      style={{ width: 100 }}
                      disabled={getFieldValue("take_profit_mode") !== "ENABLED"}
                    />
                  </Form.Item>
                )}
              </Form.Item>
              <Form.Item name="trailing_stop_mode" label="트레일링 설정 방식">
                <Select options={EXIT_MODE_OPTIONS} style={{ width: 160 }} />
              </Form.Item>
              <Form.Item
                noStyle
                shouldUpdate={(prev, cur) =>
                  prev.trailing_stop_mode !== cur.trailing_stop_mode
                }
              >
                {({ getFieldValue }) => (
                  <Form.Item name="trailing_stop_rate_pct" label="트레일링(%)">
                    <InputNumber
                      min={0}
                      max={100}
                      style={{ width: 100 }}
                      disabled={getFieldValue("trailing_stop_mode") !== "ENABLED"}
                    />
                  </Form.Item>
                )}
              </Form.Item>
              <Form.Item
                name="trailing_activation_rate_pct"
                label="트레일링 활성(%)"
                tooltip="수익이 이 %에 도달해야 트레일링이 무장됩니다. 비우면 레거시(any profit)."
              >
                <InputNumber min={0} max={100} step={0.1} style={{ width: 100 }} />
              </Form.Item>
              <Form.Item name="max_hold_mode" label="최대보유 설정 방식">
                <Select options={EXIT_MODE_OPTIONS} style={{ width: 160 }} />
              </Form.Item>
              <Form.Item
                noStyle
                shouldUpdate={(prev, cur) => prev.max_hold_mode !== cur.max_hold_mode}
              >
                {({ getFieldValue }) => (
                  <Form.Item
                    name="max_hold_hours"
                    label="최대보유(시간)"
                    tooltip="저장 시 초(seconds)로 변환됩니다."
                  >
                    <InputNumber
                      min={0}
                      step={0.5}
                      style={{ width: 100 }}
                      disabled={getFieldValue("max_hold_mode") !== "ENABLED"}
                    />
                  </Form.Item>
                )}
              </Form.Item>
            </Space>
            <Button
              type="primary"
              htmlType="submit"
              loading={saveUbaExit.isPending}
              disabled={saveUbaExit.isPending}
            >
              UBA Exit Protection 저장
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
            title="LIVE/ARM 및 거래 스케줄러 제어는 계좌 관리에서 수행합니다."
            description="이 화면은 상태 조회와 실거래 리스크 한도 재적용만 제공합니다. 긴급 중지(Kill Switch)는 위쪽 리스크 제어를 사용하세요."
          />
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            title="주문 한도: 레거시 V1 vs V2"
            description={
              "레거시 일일 주문 한도 = 당일 생성 건수(제출 후 취소 포함). " +
              "V2 제출/체결진입 한도 = 전략 소유 제출·체결진입 분리. " +
              "권장 5/1은 표시만 하며 자동 저장하지 않습니다. " +
              "V2는 계좌에 값을 명시한 뒤 다음 KRX 가능일부터 선택됩니다. " +
              "UBA1381 확인 시 user_id=61로 조회하세요."
            }
          />
          <AdminDataTable
            title="계좌 LIVE/ARM · 한도 현황"
            loading={liveAccounts.isLoading}
            error={
              liveAccounts.error ? toApiError(liveAccounts.error) : null
            }
            rowKey={(r) =>
              String(r.user_broker_account_id ?? r.account_id ?? JSON.stringify(r))
            }
            columns={[
              {
                title: "계좌(UBA)",
                dataIndex: "user_broker_account_id",
              },
              { title: "거래소/증권사", dataIndex: "broker_code" },
              { title: "별칭", dataIndex: "account_alias" },
              {
                title: "실거래(LIVE)",
                key: "live",
                render: (_: unknown, row: Record<string, unknown>) => (
                  <Tag color={row.live_order_enabled ? "green" : "default"}>
                    {row.live_order_enabled ? "켜짐" : "꺼짐"}
                  </Tag>
                ),
              },
              {
                title: "자동주문 승인(ARM)",
                key: "arm",
                render: (_: unknown, row: Record<string, unknown>) => {
                  const armed = Boolean(row.live_armed);
                  const expires = cell(row.arm_expires_at);
                  return (
                    <span style={{ fontSize: 12 }}>
                      {armed ? `승인됨 (~${expires})` : "해제"}
                    </span>
                  );
                },
              },
              {
                title: "한도(레거시 재적용)",
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
                      레거시 한도 재적용
                    </Button>
                  );
                },
              },
              {
                title: "최대 주문금액",
                key: "max_amount",
                render: (_: unknown, row: Record<string, unknown>) =>
                  cell(asRecord(row.risk)?.max_order_amount),
              },
              {
                title: "최대 주문수량",
                key: "max_qty",
                render: (_: unknown, row: Record<string, unknown>) =>
                  cell(asRecord(row.risk)?.max_order_quantity),
              },
              {
                title: "일일 주문 한도 (V1 레거시)",
                key: "daily_orders",
                render: (_: unknown, row: Record<string, unknown>) =>
                  cell(asRecord(row.risk)?.daily_order_limit),
              },
              {
                title: "주문 한도 V2 (제출 / 체결진입)",
                key: "order_limit_v2",
                width: 320,
                render: (_: unknown, row: Record<string, unknown>) => {
                  const ubaId = Number(row.user_broker_account_id);
                  const risk = asRecord(row.risk) ?? {};
                  const storedSubmit = risk.daily_submit_limit;
                  const storedFilled = risk.daily_filled_entry_limit;
                  const recommended = asRecord(risk.order_limit_v2_recommended);
                  const recSubmit = Number(
                    recommended?.daily_submit_limit ?? 5,
                  );
                  const recFilled = Number(
                    recommended?.daily_filled_entry_limit ?? 1,
                  );
                  const draft = v2Drafts[ubaId] ?? {};
                  const submitValue =
                    draft.submit !== undefined
                      ? draft.submit
                      : storedSubmit == null
                        ? null
                        : Number(storedSubmit);
                  const filledValue =
                    draft.filled !== undefined
                      ? draft.filled
                      : storedFilled == null
                        ? null
                        : Number(storedFilled);
                  const optedIn = Boolean(risk.order_limit_v2_opted_in);
                  return (
                    <Space orientation="vertical" size={4} style={{ width: "100%" }}>
                      <span style={{ fontSize: 11 }}>
                        stored:{" "}
                        {storedSubmit == null ? "NULL" : String(storedSubmit)} /{" "}
                        {storedFilled == null ? "NULL" : String(storedFilled)}
                        {optedIn ? " (opted-in)" : " (not opted-in → V1)"}
                      </span>
                      <span style={{ fontSize: 11, color: "#888" }}>
                        recommended {recSubmit}/{recFilled} — 자동적용 없음
                      </span>
                      <span style={{ fontSize: 11, color: "#666" }}>
                        today: {cell(risk.order_limit_policy_version_today)} ·
                        eligible:{" "}
                        {cell(
                          risk.order_limit_policy_version_on_or_after_min_date,
                        )}
                      </span>
                      <Space wrap size={4}>
                        <InputNumber
                          size="small"
                          min={0}
                          placeholder={`submit(${recSubmit})`}
                          value={submitValue ?? undefined}
                          onChange={(v) =>
                            setV2Drafts((prev) => ({
                              ...prev,
                              [ubaId]: {
                                ...prev[ubaId],
                                submit: v == null ? null : Number(v),
                              },
                            }))
                          }
                          style={{ width: 90 }}
                        />
                        <InputNumber
                          size="small"
                          min={0}
                          placeholder={`filled(${recFilled})`}
                          value={filledValue ?? undefined}
                          onChange={(v) =>
                            setV2Drafts((prev) => ({
                              ...prev,
                              [ubaId]: {
                                ...prev[ubaId],
                                filled: v == null ? null : Number(v),
                              },
                            }))
                          }
                          style={{ width: 90 }}
                        />
                        <Button
                          size="small"
                          type="primary"
                          loading={saveOrderLimitV2.isPending}
                          disabled={
                            submitValue == null ||
                            filledValue == null ||
                            Number.isNaN(Number(submitValue)) ||
                            Number.isNaN(Number(filledValue))
                          }
                          onClick={() => {
                            // placeholder만 채운 경우: 입력값 없으면 recommended로 저장하지 않음
                            // 명시 Input 값이 있을 때만 저장
                            const submit =
                              submitValue != null
                                ? Number(submitValue)
                                : NaN;
                            const filled =
                              filledValue != null
                                ? Number(filledValue)
                                : NaN;
                            if (
                              Number.isNaN(submit) ||
                              Number.isNaN(filled)
                            ) {
                              message.warning(
                                "V2 저장은 submit/filled 값을 모두 입력해야 합니다 (권장 5/1은 자동 미적용).",
                              );
                              return;
                            }
                            saveOrderLimitV2.mutate({
                              ubaId,
                              daily_submit_limit: submit,
                              daily_filled_entry_limit: filled,
                            });
                          }}
                        >
                          V2 저장
                        </Button>
                      </Space>
                    </Space>
                  );
                },
              },
              {
                title: "일일 최대 손실",
                key: "daily_loss",
                render: (_: unknown, row: Record<string, unknown>) =>
                  cell(asRecord(row.risk)?.daily_max_loss_amount),
              },
            ]}
            dataSource={liveAccountRows}
          />
        </Card>

        <AdminDataTable
          title="리스크 정책 목록"
          loading={policies.isLoading}
          error={policies.error ? toApiError(policies.error) : null}
          rowKey={(r) => cell(r.policy_id ?? r.policy_name ?? JSON.stringify(r))}
          columns={[
            { title: "정책번호", dataIndex: "policy_id", sorter: true },
            { title: "정책명", dataIndex: "policy_name" },
            { title: "포지션 산정 방식", dataIndex: "position_sizing_mode" },
            { title: "손절 비율", dataIndex: "stop_loss_ratio" },
          ]}
          dataSource={extractRows(policies.data)}
        />
        <AdminJsonCard
          title="대시보드 리스크 요약"
          loading={dash.isLoading}
          error={dash.error ? toApiError(dash.error) : null}
          data={dash.data}
        />
      </Space>
    </AdminPageShell>
  );
}
