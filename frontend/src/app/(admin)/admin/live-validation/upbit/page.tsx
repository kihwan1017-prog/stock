"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

const CONFIRMATION = "UPBIT-LIVE-ONE-ORDER";

export default function AdminUpbitLiveValidationPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const [preflight, setPreflight] = useState<Record<string, unknown> | null>(
    null,
  );
  const [armToken, setArmToken] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [locked, setLocked] = useState(false);

  const metaQuery = useQuery({
    queryKey: ["admin", "upbit-live-validation-meta"],
    queryFn: () => adminApi.getUpbitLiveValidationMeta(),
  });
  const runsQuery = useQuery({
    queryKey: ["admin", "upbit-live-validation-runs"],
    queryFn: () => adminApi.listUpbitLiveValidationRuns(),
    refetchInterval: 15_000,
  });
  const dashQuery = useQuery({
    queryKey: ["admin", "upbit-live-validation-dashboard"],
    queryFn: () => adminApi.getUpbitLiveValidationDashboard(),
    refetchInterval: 10_000,
  });
  const dash = asRecord(dashQuery.data);
  const counts = asRecord(dash?.counts) ?? {};
  const tracker = asRecord(dash?.tracker) ?? asRecord(metaQuery.data)?.tracker;

  const refreshMut = useMutation({
    mutationFn: (runId: string) =>
      adminApi.refreshUpbitLiveValidationRun(runId),
    onSuccess: () => {
      message.success("Broker 상태 새로고침");
      void qc.invalidateQueries({
        queryKey: ["admin", "upbit-live-validation-runs"],
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });
  const cancelMut = useMutation({
    mutationFn: (runId: string) =>
      adminApi.cancelUpbitLiveValidationRun(runId),
    onSuccess: (data) => {
      const r = asRecord(data);
      message.info(
        r?.cancel_completed
          ? "취소 완료 확인"
          : "취소 요청 접수 (CANCEL_PENDING — 완료 아님)",
      );
      void qc.invalidateQueries({
        queryKey: ["admin", "upbit-live-validation-runs"],
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const preflightMut = useMutation({
    mutationFn: adminApi.preflightUpbitLiveValidation,
    onSuccess: (data) => {
      setPreflight(asRecord(data) ?? {});
      message.success("Preflight 완료");
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const executeMut = useMutation({
    mutationFn: adminApi.executeUpbitLiveValidation,
    onSuccess: () => {
      setLocked(true);
      setArmToken("");
      message.success("실행 요청 완료 — 버튼 잠금");
      void qc.invalidateQueries({
        queryKey: ["admin", "upbit-live-validation-runs"],
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const ready = Boolean(preflight?.ready);
  const blockers = (preflight?.blockers as string[] | undefined) ?? [];
  const liveEnabled = useMemo(() => {
    const amount = Number(form.getFieldValue("amount") ?? 0);
    return (
      ready &&
      blockers.length === 0 &&
      confirmText === CONFIRMATION &&
      amount > 0 &&
      amount <= 10000 &&
      !locked &&
      !executeMut.isPending
    );
  }, [
    ready,
    blockers.length,
    confirmText,
    locked,
    executeMut.isPending,
    form,
  ]);

  const checkRows = (
    (preflight?.checks as Record<string, unknown>[] | undefined) ?? []
  ).map((c, idx) => ({ key: idx, ...c }));

  return (
    <AdminPageShell
      title="Upbit 소액 LIVE 검증"
      description="기본 DRY-RUN. 실주문은 승인·플래그·확인문구·서버 ARM state가 모두 있을 때만."
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="warning"
          showIcon
          title="실주문은 운영자 별도 승인 후에만. OUTBOX_PENDING≠Accepted, CANCEL_REQUESTED≠Canceled."
        />

        <Card title="Broker Tracking Dashboard" size="small" loading={dashQuery.isLoading}>
          <Space wrap>
            <Tag>Outbox={cell(counts.outbox_pending)}</Tag>
            <Tag>SubmitPending={cell(counts.broker_submission_pending)}</Tag>
            <Tag>Open={cell(counts.open)}</Tag>
            <Tag>Partial={cell(counts.partial)}</Tag>
            <Tag color="orange">CancelPending={cell(counts.cancel_pending)}</Tag>
            <Tag color="error">Unknown={cell(counts.unknown)}</Tag>
            <Tag color="volcano">
              ManualReview={cell(counts.manual_review_required)}
            </Tag>
            <Tag>
              Tracker=
              {String(asRecord(tracker)?.running ?? "-")}/
              {String(asRecord(tracker)?.enabled ?? "-")}
            </Tag>
          </Space>
        </Card>

        <Card title="주문 파라미터" size="small">
          <Form
            form={form}
            layout="vertical"
            initialValues={{
              market: "KRW-XRP",
              side: "BUY",
              amount: 5000,
              limit_price: 500,
            }}
            onFinish={(values) => {
              preflightMut.mutate({
                user_broker_account_id: Number(values.uba_id),
                market: String(values.market).toUpperCase(),
                side: String(values.side).toUpperCase(),
                amount: Number(values.amount),
                limit_price: Number(values.limit_price),
                arm_token: armToken || null,
              });
            }}
          >
            <Space wrap size={16}>
              <Form.Item
                name="uba_id"
                label="UBA ID"
                rules={[{ required: true }]}
              >
                <InputNumber min={1} style={{ width: 160 }} />
              </Form.Item>
              <Form.Item name="market" label="Market" rules={[{ required: true }]}>
                <Select
                  style={{ width: 160 }}
                  options={(
                    (asRecord(metaQuery.data)?.default_allowlist as
                      | string[]
                      | undefined) ?? ["KRW-XRP", "KRW-BTC", "KRW-ETH"]
                  ).map((m) => ({ value: m, label: m }))}
                />
              </Form.Item>
              <Form.Item name="side" label="Side">
                <Select
                  style={{ width: 120 }}
                  options={[
                    { value: "BUY", label: "BUY" },
                    { value: "SELL", label: "SELL" },
                  ]}
                />
              </Form.Item>
              <Form.Item name="amount" label="금액(원)">
                <InputNumber min={5000} max={10000} style={{ width: 140 }} />
              </Form.Item>
              <Form.Item name="limit_price" label="지정가">
                <InputNumber min={0.01} style={{ width: 140 }} />
              </Form.Item>
            </Space>
            <Button
              type="primary"
              htmlType="submit"
              loading={preflightMut.isPending}
            >
              Preflight / Dry-run 점검
            </Button>
          </Form>
        </Card>

        {preflight ? (
          <Card title="Preflight 결과" size="small">
            <Space wrap>
              <Tag color={ready ? "success" : "error"}>
                ready={String(ready)}
              </Tag>
              <Tag>LIVE={String(preflight.live_enabled)}</Tag>
              <Tag>ARM={String(preflight.armed)}</Tag>
              <Tag>Kill={String(preflight.kill_switch_active)}</Tag>
              <Tag>Open={String(preflight.open_order_count)}</Tag>
              <Tag>Est={cell(preflight.estimated_amount)}</Tag>
            </Space>
            <Table
              style={{ marginTop: 12 }}
              size="small"
              pagination={false}
              dataSource={checkRows}
              columns={[
                { title: "code", dataIndex: "code" },
                { title: "status", dataIndex: "status" },
                { title: "message", dataIndex: "message" },
              ]}
            />
            {blockers.length ? (
              <Alert
                style={{ marginTop: 12 }}
                type="error"
                title={`Blockers (${blockers.length})`}
                description={blockers.join(" | ")}
              />
            ) : null}
          </Card>
        ) : null}

        <Card title="LIVE 실행 (잠금)" size="small">
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="확인 문구">
              정확히 <code>{CONFIRMATION}</code>
            </Descriptions.Item>
          </Descriptions>
          <Space orientation="vertical" style={{ width: "100%", marginTop: 12 }}>
            <Alert
              type="info"
              showIcon
              title="ARM authorization"
              description="원문 token 입력이 필요 없습니다. 관리자 ARM ON 상태(UBA binding + TTL)를 서버가 검증합니다. (선택) challenge용 arm_token은 아래 필드에만 임시 입력."
            />
            <Input.Password
              placeholder="arm_token (선택·challenge, 저장하지 않음)"
              value={armToken}
              onChange={(e) => setArmToken(e.target.value)}
              disabled={locked}
              autoComplete="off"
            />
            <Input
              placeholder="confirmation_text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              disabled={locked}
            />
            <Button
              danger
              type="primary"
              disabled={!liveEnabled}
              loading={executeMut.isPending}
              onClick={() => {
                const values = form.getFieldsValue();
                executeMut.mutate({
                  user_broker_account_id: Number(values.uba_id),
                  market: String(values.market).toUpperCase(),
                  side: String(values.side).toUpperCase(),
                  amount: Number(values.amount),
                  limit_price: Number(values.limit_price),
                  arm_token: armToken.trim() ? armToken : null,
                  execute_live: true,
                  confirmation_text: confirmText,
                  preflight_id: String(preflight?.preflight_id ?? ""),
                });
              }}
            >
              LIVE 1건 실행
            </Button>
          </Space>
        </Card>

        <Card title="최근 Runs" size="small" loading={runsQuery.isLoading}>
          <Table
            size="small"
            rowKey={(r) => String(r.run_id)}
            dataSource={
              (asRecord(runsQuery.data)?.items as
                | Record<string, unknown>[]
                | undefined) ?? []
            }
            columns={[
              { title: "run_id", dataIndex: "run_id" },
              {
                title: "internal",
                dataIndex: "internal_status",
                render: (v: unknown, row: Record<string, unknown>) => {
                  const status = String(
                    v ?? row.status ?? "",
                  ).toUpperCase();
                  const broker = String(
                    row.broker_order_status ?? "",
                  ).toUpperCase();
                  if (
                    status === "CANCELED" &&
                    (broker === "NOT_SUBMITTED" || broker === "")
                  ) {
                    return <Tag>내부 폐기됨</Tag>;
                  }
                  return <Tag>{status || "-"}</Tag>;
                },
              },
              { title: "broker", dataIndex: "broker_order_status" },
              { title: "market", dataIndex: "market" },
              { title: "live", dataIndex: "execute_live" },
              { title: "order_id", dataIndex: "order_id" },
              {
                title: "actions",
                render: (_: unknown, row: Record<string, unknown>) => (
                  <Space>
                    <Button
                      size="small"
                      onClick={() =>
                        refreshMut.mutate(String(row.run_id))
                      }
                    >
                      Refresh
                    </Button>
                    <Button
                      size="small"
                      danger
                      onClick={() =>
                        cancelMut.mutate(String(row.run_id))
                      }
                    >
                      Cancel
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      </Space>
    </AdminPageShell>
  );
}
