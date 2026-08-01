"use client";

/**
 * STEP 8-9C — Admin UPBIT LIVE UBA CRUD + Credential 등록.
 * LIVE ON / ARM / 실주문 버튼은 제공하지 않는다.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Space,
  Switch,
  Typography,
  message as antdMessage,
} from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable } from "@/features/admin/components/AdminPanels";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

export function AdminUpbitLiveUbaPanel() {
  const [messageApi, contextHolder] = antdMessage.useMessage();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [credTarget, setCredTarget] = useState<number | null>(null);
  const [editTarget, setEditTarget] = useState<Record<string, unknown> | null>(
    null,
  );
  const [createForm] = Form.useForm();
  const [credForm] = Form.useForm();
  const [editForm] = Form.useForm();

  const listQuery = useQuery({
    queryKey: ["admin", "broker-accounts", "UPBIT"],
    queryFn: () =>
      adminApi.listAdminBrokerAccounts({
        broker_code: "UPBIT",
        include_inactive: true,
        limit: 100,
      }),
  });

  const readinessQuery = useQuery({
    queryKey: ["admin", "live-ops-readiness"],
    queryFn: adminApi.getAdminLiveOpsReadiness,
  });

  const invalidate = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["admin", "broker-accounts", "UPBIT"],
    });
    await queryClient.invalidateQueries({
      queryKey: ["admin", "live-ops-readiness"],
    });
  };

  const createMutation = useMutation({
    mutationFn: adminApi.createAdminBrokerAccount,
    onSuccess: async () => {
      messageApi.success("UPBIT UBA 생성 완료 (LIVE OFF, 권장 Risk 적용)");
      setCreateOpen(false);
      createForm.resetFields();
      await invalidate();
    },
    onError: (err) => messageApi.error(toApiError(err).message),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      ubaId,
      body,
    }: {
      ubaId: number;
      body: { account_alias?: string; is_active?: boolean };
    }) => adminApi.updateAdminBrokerAccount(ubaId, body),
    onSuccess: async () => {
      messageApi.success("UBA 수정 완료");
      setEditTarget(null);
      await invalidate();
    },
    onError: (err) => messageApi.error(toApiError(err).message),
  });

  const deleteMutation = useMutation({
    mutationFn: adminApi.deleteAdminBrokerAccount,
    onSuccess: async () => {
      messageApi.success("UBA 연결 삭제 완료 (LIVE OFF 강제)");
      await invalidate();
    },
    onError: (err) => messageApi.error(toApiError(err).message),
  });

  const riskMutation = useMutation({
    mutationFn: adminApi.applyAdminBrokerRecommendedRisk,
    onSuccess: async () => {
      messageApi.success("권장 Risk 적용 (5000 / 1 / 1)");
      await invalidate();
    },
    onError: (err) => messageApi.error(toApiError(err).message),
  });

  const registerCredMutation = useMutation({
    mutationFn: ({
      ubaId,
      body,
    }: {
      ubaId: number;
      body: { access_key: string; secret_key: string };
    }) => adminApi.registerAdminBrokerCredential(ubaId, body),
    onSuccess: async () => {
      messageApi.success("Credential 등록 요청 완료 (원문 미보관 UI)");
      setCredTarget(null);
      credForm.resetFields();
      await invalidate();
    },
    onError: (err) => messageApi.error(toApiError(err).message),
  });

  const replaceCredMutation = useMutation({
    mutationFn: ({
      ubaId,
      body,
    }: {
      ubaId: number;
      body: { access_key: string; secret_key: string };
    }) => adminApi.replaceAdminBrokerCredential(ubaId, body),
    onSuccess: async () => {
      messageApi.success("Credential 교체 완료");
      setCredTarget(null);
      credForm.resetFields();
      await invalidate();
    },
    onError: (err) => messageApi.error(toApiError(err).message),
  });

  const stopTradingScheduler = useMutation({
    mutationFn: adminApi.stopRealtimeTradingScheduler,
    onSuccess: async () => {
      messageApi.success("거래 Scheduler Pause(stop) 요청 완료");
      await queryClient.invalidateQueries({
        queryKey: ["admin", "live-ops-readiness"],
      });
    },
    onError: (err) => messageApi.error(toApiError(err).message),
  });

  const rows = extractRows(listQuery.data) as Record<string, unknown>[];
  const readiness = readinessQuery.data as
    | {
        dry_run_ready?: boolean;
        blockers?: string[];
        warnings?: string[];
        schedulers?: {
          trading?: { running?: boolean | null; ok?: boolean };
          tracking?: { enabled?: boolean; ok?: boolean };
          post_fill?: { enabled?: boolean; ok?: boolean };
        };
        upbit_use_mock?: boolean;
      }
    | undefined;

  return (
    <Card
      title="UPBIT LIVE UBA (STEP 8-9C)"
      size="small"
      extra={
        <Space wrap>
          <Button onClick={() => void listQuery.refetch()}>새로고침</Button>
          <Button type="primary" onClick={() => setCreateOpen(true)}>
            UBA 생성
          </Button>
        </Space>
      }
    >
      {contextHolder}
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        title="이 패널은 UBA CRUD · Credential · 권장 Risk · Scheduler 점검만 제공합니다. LIVE ON / ARM / 실주문은 없습니다."
      />

      <Card size="small" title="Dry-run 준비 상태" style={{ marginBottom: 12 }}>
        {readinessQuery.isError ? (
          <Alert type="error" title={toApiError(readinessQuery.error).message} />
        ) : (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Typography.Text>
              dry_run_ready:{" "}
              <Typography.Text strong>
                {String(readiness?.dry_run_ready ?? "-")}
              </Typography.Text>
              {" · "}
              UPBIT_USE_MOCK={String(readiness?.upbit_use_mock ?? "-")}
            </Typography.Text>
            <Typography.Text type="secondary">
              거래 Scheduler desired=PAUSE running=
              {String(readiness?.schedulers?.trading?.running ?? "unknown")} ·
              Tracking=
              {String(readiness?.schedulers?.tracking?.enabled ?? "-")} ·
              Post-fill=
              {String(readiness?.schedulers?.post_fill?.enabled ?? "-")}
            </Typography.Text>
            {(readiness?.blockers?.length ?? 0) > 0 ? (
              <Alert
                type="warning"
                title={`Blockers: ${(readiness?.blockers ?? []).join(", ")}`}
              />
            ) : null}
            <Button
              danger
              loading={stopTradingScheduler.isPending}
              disabled={readiness?.schedulers?.trading?.running !== true}
              onClick={() => stopTradingScheduler.mutate()}
            >
              거래 Scheduler Pause (stop)
            </Button>
          </Space>
        )}
      </Card>

      <AdminDataTable
        loading={listQuery.isLoading}
        rowKey={(row) => String(row.user_broker_account_id ?? row.account_id)}
        dataSource={rows}
        columns={[
          {
            title: "UBA",
            dataIndex: "user_broker_account_id",
            width: 80,
            render: (_: unknown, row) =>
              cell(row.user_broker_account_id ?? row.account_id),
          },
          {
            title: "Owner",
            dataIndex: "user_id",
            width: 80,
            render: (_: unknown, row) => cell(row.user_id),
          },
          {
            title: "Alias",
            dataIndex: "account_name",
            render: (_: unknown, row) => cell(row.account_name),
          },
          {
            title: "Active",
            dataIndex: "is_active",
            width: 70,
            render: (_: unknown, row) => (row.is_active ? "Y" : "N"),
          },
          {
            title: "LIVE",
            dataIndex: "live_order_enabled",
            width: 70,
            render: (_: unknown, row) => (row.live_order_enabled ? "ON" : "OFF"),
          },
          {
            title: "ARM",
            dataIndex: "live_armed",
            width: 70,
            render: (_: unknown, row) => (row.live_armed ? "Y" : "N"),
          },
          {
            title: "Cred",
            key: "cred",
            width: 90,
            render: (_: unknown, row) => {
              const cred = row.credential as
                | { registered?: boolean; verification_status?: string }
                | undefined;
              return cred?.registered
                ? String(cred.verification_status ?? "Y")
                : "N";
            },
          },
          {
            title: "Risk max",
            key: "risk",
            width: 100,
            render: (_: unknown, row) => {
              const risk = row.risk as
                | { max_order_amount?: string }
                | undefined;
              return cell(risk?.max_order_amount);
            },
          },
          {
            title: "Actions",
            key: "actions",
            width: 360,
            render: (_: unknown, row) => {
              const ubaId = Number(row.user_broker_account_id ?? row.account_id);
              const registered = Boolean(
                (row.credential as { registered?: boolean } | undefined)
                  ?.registered,
              );
              return (
                <Space wrap size={4}>
                  <Button
                    size="small"
                    onClick={() => {
                      // setFieldsValue 는 Modal afterOpenChange 에서 수행
                      // (destroyOnHidden 시 Form 미연결 경고 방지)
                      setEditTarget(row);
                    }}
                  >
                    수정
                  </Button>
                  <Button
                    size="small"
                    onClick={() => setCredTarget(ubaId)}
                  >
                    {registered ? "Credential 교체" : "Credential 등록"}
                  </Button>
                  <Button
                    size="small"
                    loading={riskMutation.isPending}
                    onClick={() => riskMutation.mutate(ubaId)}
                  >
                    Risk 5000
                  </Button>
                  <Button
                    size="small"
                    danger
                    onClick={() => {
                      Modal.confirm({
                        title: "UBA 연결 삭제",
                        content:
                          "Broker 연결 행만 삭제합니다. LIVE OFF 후 unlink. 실계좌는 삭제되지 않습니다.",
                        okType: "danger",
                        onOk: () => deleteMutation.mutateAsync(ubaId),
                      });
                    }}
                  >
                    삭제
                  </Button>
                </Space>
              );
            },
          },
        ]}
      />

      <Modal
        title="UPBIT UBA 생성"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        confirmLoading={createMutation.isPending}
        forceRender
      >
        <Form
          form={createForm}
          layout="vertical"
          initialValues={{
            broker_code: "UPBIT",
            account_number: "MAIN",
            apply_recommended_risk: true,
            is_default: true,
          }}
          onFinish={(values) =>
            createMutation.mutate({
              owner_user_id: Number(values.owner_user_id),
              broker_code: "UPBIT",
              account_alias: values.account_alias,
              account_number: values.account_number,
              is_default: Boolean(values.is_default),
              apply_recommended_risk: Boolean(values.apply_recommended_risk),
            })
          }
        >
          <Form.Item
            name="owner_user_id"
            label="owner_user_id"
            rules={[{ required: true }]}
          >
            <InputNumber min={1} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="account_alias" label="별칭">
            <Input placeholder="upbit-main" />
          </Form.Item>
          <Form.Item
            name="account_number"
            label="account_ref (해시 저장)"
            rules={[{ required: true }]}
          >
            <Input placeholder="MAIN" />
          </Form.Item>
          <Form.Item
            name="apply_recommended_risk"
            label="권장 Risk(5000/1/1)"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item name="is_default" label="기본 계좌" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`UBA 수정 #${editTarget ? String(editTarget.user_broker_account_id ?? editTarget.account_id) : ""}`}
        open={editTarget != null}
        onCancel={() => setEditTarget(null)}
        onOk={() => editForm.submit()}
        confirmLoading={updateMutation.isPending}
        destroyOnHidden
        afterOpenChange={(opened) => {
          if (!opened || !editTarget) return;
          editForm.setFieldsValue({
            account_alias: String(editTarget.account_name ?? ""),
            is_active: Boolean(editTarget.is_active),
          });
        }}
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={(values) => {
            if (!editTarget) return;
            const ubaId = Number(
              editTarget.user_broker_account_id ?? editTarget.account_id,
            );
            updateMutation.mutate({
              ubaId,
              body: {
                account_alias: values.account_alias,
                is_active: values.is_active,
              },
            });
          }}
        >
          <Form.Item name="account_alias" label="별칭" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="is_active" label="활성" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`Credential ${credTarget ?? ""}`}
        open={credTarget != null}
        onCancel={() => setCredTarget(null)}
        onOk={() => credForm.submit()}
        confirmLoading={
          registerCredMutation.isPending || replaceCredMutation.isPending
        }
        forceRender
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          title="Access/Secret Key는 전송 후 Form에서 즉시 비웁니다. 서버 응답에도 원문이 없습니다."
        />
        <Form
          key={credTarget ?? "closed"}
          form={credForm}
          layout="vertical"
          onFinish={(values) => {
            if (credTarget == null) return;
            const body = {
              access_key: String(values.access_key),
              secret_key: String(values.secret_key),
            };
            const row = rows.find(
              (r) =>
                Number(r.user_broker_account_id ?? r.account_id) === credTarget,
            );
            const registered = Boolean(
              (row?.credential as { registered?: boolean } | undefined)
                ?.registered,
            );
            if (registered) {
              replaceCredMutation.mutate({ ubaId: credTarget, body });
            } else {
              registerCredMutation.mutate({ ubaId: credTarget, body });
            }
          }}
        >
          <Form.Item
            name="access_key"
            label="Access Key"
            rules={[{ required: true }]}
          >
            <Input.Password autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="secret_key"
            label="Secret Key"
            rules={[{ required: true }]}
          >
            <Input.Password autoComplete="off" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
