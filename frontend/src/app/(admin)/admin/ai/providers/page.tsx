"use client";

/**
 * STEP 11-3 — AI Provider 관리 (설정·Credential Vault).
 * 자동 enable / 자동 AI 호출 없음. Secret 재노출 금지.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { useEffect, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminAiProvidersPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [editForm] = Form.useForm();

  const listQuery = useQuery({
    queryKey: queryKeys.admin.aiProviderConfigurations(),
    queryFn: adminApi.listAiProviderConfigurations,
  });

  const items = extractRows(asRecord(listQuery.data)?.items);
  const selected = items.find((r) => Number(r.id) === selectedId) ?? null;

  // Form은 selected 있을 때만 마운트 → 연결 후 값 주입 (미연결 setFieldsValue 경고 방지)
  useEffect(() => {
    if (!selected) return;
    editForm.setFieldsValue({
      display_name: selected.display_name,
      model: selected.model,
      // endpoint는 masked만 오므로 빈 값 = 기존 유지
      endpoint: "",
      priority: selected.priority,
      timeout_sec: selected.timeout_sec,
      retry_max: selected.retry_max,
      max_tokens: selected.max_tokens,
      temperature: selected.temperature,
    });
  }, [selected, editForm]);

  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: ["admin", "ai-provider-configurations"],
    });

  const requireReason = () => {
    if (!reason.trim()) {
      message.error("변경 reason이 필요합니다");
      return false;
    }
    return true;
  };

  const upsertMut = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      adminApi.upsertAiProviderConfiguration(body),
    onSuccess: () => {
      message.success("설정 저장됨 (자동 enable/test 없음)");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const storeCredMut = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      adminApi.storeAiProviderCredential(selectedId!, body),
    onSuccess: () => {
      message.success("Credential 저장됨 (PENDING, 자동 검증 없음)");
      setApiKey("");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const verifyMut = useMutation({
    mutationFn: () =>
      adminApi.verifyAiProviderCredential(selectedId!, {
        reason,
      }),
    onSuccess: () => {
      message.success("검증 요청 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const enableMut = useMutation({
    mutationFn: () =>
      adminApi.enableAiProvider(selectedId!, {
        reason,
        confirm: true,
      }),
    onSuccess: () => {
      message.success("Provider enabled (자동 test 없음)");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const disableMut = useMutation({
    mutationFn: () =>
      adminApi.disableAiProvider(selectedId!, { reason }),
    onSuccess: () => {
      message.success("Provider disabled");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const reloadMut = useMutation({
    mutationFn: () =>
      adminApi.reloadAiProviderRegistry(selectedId!, { reason }),
    onSuccess: () => {
      message.success("Registry reload 요청됨");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const testMut = useMutation({
    mutationFn: () =>
      adminApi.testAiProvider(String(selected?.provider_code ?? "mock"), {
        prompt: "Return exactly: OK",
        max_tokens: 16,
      }),
    onSuccess: (data) => {
      message.success("Test 완료 (수동)");
      console.info("ai provider test result", data);
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const openEdit = (row: Record<string, unknown>) => {
    setSelectedId(Number(row.id));
  };

  return (
    <AdminPageShell
      title="AI Provider 관리"
      description="설정·Credential Vault · Enable은 명시적 승인만 (자동 AI 호출 없음)"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card size="small" title="변경 Reason (필수)">
          <Input.TextArea
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="운영 변경 사유"
          />
        </Card>

        <Card size="small" title="Provider 목록" loading={listQuery.isLoading}>
          <Table
            size="small"
            rowKey="id"
            dataSource={items}
            pagination={false}
            onRow={(row) => ({
              onClick: () => openEdit(row as Record<string, unknown>),
            })}
            columns={[
              { title: "Provider", dataIndex: "provider_code" },
              {
                title: "Enabled",
                dataIndex: "enabled",
                render: (v) => (v ? <Tag color="success">ON</Tag> : <Tag>OFF</Tag>),
              },
              {
                title: "Default",
                dataIndex: "is_default",
                render: (v) => (v ? <Tag color="blue">DEFAULT</Tag> : "—"),
              },
              { title: "Priority", dataIndex: "priority", width: 80 },
              { title: "Model", dataIndex: "model", ellipsis: true },
              { title: "Endpoint", dataIndex: "endpoint", ellipsis: true },
              {
                title: "Credential",
                dataIndex: "credential",
                render: (c) => {
                  const rec = asRecord(c);
                  return rec?.status ? (
                    <Tag>{String(rec.status)}</Tag>
                  ) : (
                    "—"
                  );
                },
              },
              {
                title: "Drift",
                dataIndex: "config_drift",
                render: (v) => (v ? <Tag color="warning">YES</Tag> : "NO"),
              },
              {
                title: "Reload?",
                dataIndex: "reload_required",
                render: (v) => (v ? "Y" : "N"),
              },
            ]}
          />
        </Card>

        {selected && (
          <Card
            size="small"
            title={`상세: ${cell(selected.provider_code)} (#${selectedId})`}
          >
            <Space orientation="vertical" style={{ width: "100%" }} size={12}>
              <Form
                form={editForm}
                layout="vertical"
                onFinish={(values) => {
                  if (!requireReason()) return;
                  const body: Record<string, unknown> = {
                    provider_code: selected.provider_code,
                    reason,
                    expected_version: selected.config_version,
                    ...values,
                  };
                  // 빈 endpoint는 기존 값 유지 (삭제 금지)
                  if (!String(values.endpoint ?? "").trim()) {
                    delete body.endpoint;
                  }
                  upsertMut.mutate(body);
                }}
              >
                <Form.Item name="display_name" label="Display Name">
                  <Input />
                </Form.Item>
                <Form.Item name="model" label="Model">
                  <Input />
                </Form.Item>
                <Form.Item
                  name="endpoint"
                  label="Endpoint (비우면 기존 유지)"
                  extra="마스킹된 기존 값은 표시하지 않습니다"
                >
                  <Input placeholder="https://..." />
                </Form.Item>
                <Space wrap>
                  <Form.Item name="priority" label="Priority">
                    <InputNumber />
                  </Form.Item>
                  <Form.Item name="timeout_sec" label="Timeout">
                    <InputNumber min={1} max={600} />
                  </Form.Item>
                  <Form.Item name="retry_max" label="Retry">
                    <InputNumber min={0} max={10} />
                  </Form.Item>
                  <Form.Item name="max_tokens" label="Max Tokens">
                    <InputNumber min={1} max={128000} />
                  </Form.Item>
                  <Form.Item name="temperature" label="Temperature">
                    <InputNumber min={0} max={2} step={0.1} />
                  </Form.Item>
                </Space>
                <Button type="primary" htmlType="submit" loading={upsertMut.isPending}>
                  설정 저장
                </Button>
              </Form>

              <Typography.Paragraph type="secondary">
                Credential Status:{" "}
                {cell(asRecord(selected.credential)?.status) || "없음"} / fingerprint:{" "}
                {cell(asRecord(selected.credential)?.fingerprint_prefix) || "—"}
              </Typography.Paragraph>

              <Input.Password
                placeholder="새 API Key (빈 값 저장 시 기존 삭제 안 함 — 저장 버튼만 새 값일 때)"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                visibilityToggle
              />
              <Space wrap>
                <Button
                  disabled={!apiKey.trim()}
                  loading={storeCredMut.isPending}
                  onClick={() => {
                    if (!requireReason() || !selectedId) return;
                    storeCredMut.mutate({ reason, api_key: apiKey });
                  }}
                >
                  Credential 저장
                </Button>
                <Button
                  loading={verifyMut.isPending}
                  onClick={() => {
                    if (!requireReason()) return;
                    Modal.confirm({
                      title: "Credential 검증",
                      content:
                        "외부 AI 저비용 호출이 발생할 수 있습니다. 계속할까요?",
                      onOk: () => verifyMut.mutate(),
                    });
                  }}
                >
                  Verify
                </Button>
                <Button
                  type="primary"
                  danger={!selected.enabled}
                  onClick={() => {
                    if (!requireReason()) return;
                    if (selected.enabled) {
                      disableMut.mutate();
                      return;
                    }
                    Modal.confirm({
                      title: "Provider Enable",
                      content:
                        "Enable만 수행합니다. 자동 Test/주문/전략 연결은 없습니다.",
                      onOk: () => enableMut.mutate(),
                    });
                  }}
                >
                  {selected.enabled ? "Disable" : "Enable"}
                </Button>
                <Button
                  loading={reloadMut.isPending}
                  onClick={() => {
                    if (!requireReason()) return;
                    reloadMut.mutate();
                  }}
                >
                  Registry Reload
                </Button>
                <Button
                  onClick={() => {
                    if (!requireReason() || !selectedId) return;
                    Modal.confirm({
                      title: "Default Provider 변경",
                      content: "이 Provider를 기본값으로 설정합니다.",
                      onOk: () =>
                        adminApi
                          .setDefaultAiProvider(selectedId, {
                            reason,
                            confirm: true,
                          })
                          .then(() => {
                            message.success("Default 변경됨");
                            invalidate();
                          })
                          .catch((e) => message.error(toApiError(e).message)),
                    });
                  }}
                >
                  Set Default
                </Button>
                <Button
                  loading={testMut.isPending}
                  onClick={() => {
                    Modal.confirm({
                      title: "수동 Provider Test",
                      content: (
                        <div>
                          <div>Provider: {cell(selected.provider_code)}</div>
                          <div>Model: {cell(selected.model)}</div>
                          <div>Max Tokens: 16</div>
                          <div>외부 비용이 발생할 수 있습니다.</div>
                        </div>
                      ),
                      onOk: () => testMut.mutate(),
                    });
                  }}
                >
                  수동 Test
                </Button>
              </Space>
            </Space>
          </Card>
        )}
      </Space>
    </AdminPageShell>
  );
}
