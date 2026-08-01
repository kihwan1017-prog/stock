"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import type { IndicatorParameterRecord } from "@/features/admin/api/adminApi";
import { AdminDataTable } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const JOB_NAME = "indicator_daily_batch";

interface JobHistoryRow {
  job_run_id: number;
  job_name: string;
  job_group?: string;
  trigger_type?: string;
  status_code: string;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
  error_message?: string | null;
}

function parseJsonObject(raw: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return null;
  } catch {
    return null;
  }
}

export default function AdminIndicatorsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [editTarget, setEditTarget] = useState<IndicatorParameterRecord | null>(
    null,
  );
  const [createOpen, setCreateOpen] = useState(false);
  const [previewResult, setPreviewResult] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [form] = Form.useForm();
  const [createForm] = Form.useForm();

  const paramsQuery = useQuery({
    queryKey: queryKeys.admin.indicatorParameters(),
    queryFn: () => adminApi.listIndicatorParameters(),
  });

  const historyQuery = useQuery({
    queryKey: [...queryKeys.admin.jobHistory(), JOB_NAME],
    queryFn: () =>
      adminApi.listJobHistory({ job_name: JOB_NAME, limit: 50 }),
  });

  const invalidateParams = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.admin.indicatorParameters(),
    });
  };

  const previewMut = useMutation({
    mutationFn: adminApi.previewIndicatorParameter,
    onSuccess: (data) => {
      setValidationError(null);
      setPreviewResult(JSON.stringify(data, null, 2));
      message.success("파라미터 검증 통과 (Preview)");
    },
    onError: (error) => {
      setPreviewResult(null);
      setValidationError(toApiError(error).message);
    },
  });

  const createMut = useMutation({
    mutationFn: adminApi.createIndicatorParameter,
    onSuccess: () => {
      message.success("지표 파라미터가 등록되었습니다.");
      setCreateOpen(false);
      createForm.resetFields();
      setPreviewResult(null);
      setValidationError(null);
      invalidateParams();
    },
    onError: (error) => setValidationError(toApiError(error).message),
  });

  const updateMut = useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: number;
      body: Parameters<typeof adminApi.updateIndicatorParameter>[1];
    }) => adminApi.updateIndicatorParameter(id, body),
    onSuccess: () => {
      message.success("지표 파라미터가 수정되었습니다.");
      setEditTarget(null);
      setPreviewResult(null);
      setValidationError(null);
      invalidateParams();
    },
    onError: (error) => setValidationError(toApiError(error).message),
  });

  const paramRows = paramsQuery.data?.items ?? [];
  const systemDefaults = paramsQuery.data?.system_defaults ?? {};
  const activeVersions = useMemo(
    () => paramRows.filter((row) => row.is_active),
    [paramRows],
  );

  const historyPayload = historyQuery.data as { items?: JobHistoryRow[] } | undefined;
  const historyRows = Array.isArray(historyPayload?.items)
    ? historyPayload.items
    : [];

  const deactivateMutation = useMutation({
    mutationFn: (id: number) =>
      adminApi.updateIndicatorParameter(id, { is_active: false }),
    onSuccess: () => {
      message.success("비활성화됨 — 시스템 기본값 적용 가능");
      invalidateParams();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const restoreDefaultsMutation = useMutation({
    mutationFn: () => adminApi.restoreIndicatorParameterDefaults(),
    onSuccess: () => {
      message.success("활성 DB 파라미터 해제 — 시스템 기본값 복원");
      invalidateParams();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const openEdit = (row: IndicatorParameterRecord) => {
    setEditTarget(row);
    setPreviewResult(null);
    setValidationError(null);
    form.setFieldsValue({
      parameter_payload: JSON.stringify(row.parameter_payload, null, 2),
      is_active: row.is_active,
    });
  };

  const buildPayloadFromForm = (
    values: Record<string, unknown>,
  ): Record<string, unknown> | null => {
    const raw = String(values.parameter_payload ?? "").trim();
    const parsed = parseJsonObject(raw);
    if (!parsed) {
      setValidationError("parameter_payload는 JSON 객체여야 합니다.");
      return null;
    }
    return parsed;
  };

  return (
    <AdminPageShell
      title="기술지표 관리"
      description="지표 파라미터 CRUD · indicator_daily_batch 실행 이력"
    >
      <Card
        size="small"
        title="지표 파라미터 관리"
        style={{ marginBottom: 16 }}
        extra={
          <Space wrap>
            <Button
              loading={restoreDefaultsMutation.isPending}
              onClick={() => restoreDefaultsMutation.mutate()}
            >
              시스템 기본값 복원
            </Button>
            <Button type="primary" onClick={() => setCreateOpen(true)}>
              파라미터 등록
            </Button>
          </Space>
        }
      >
        {paramsQuery.error ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(paramsQuery.error).message}
            style={{ marginBottom: 12 }}
          />
        ) : null}

        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            title="시스템 기본값"
            description={
              <pre style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap" }}>
                {JSON.stringify(systemDefaults, null, 2)}
              </pre>
            }
          />

          <Typography.Text type="secondary">
            활성 버전 {activeVersions.length}건 / 전체 {paramRows.length}건
          </Typography.Text>

          <AdminDataTable<IndicatorParameterRecord>
            title="파라미터 설정"
            loading={paramsQuery.isLoading}
            error={paramsQuery.error ? toApiError(paramsQuery.error) : null}
            rowKey={(row) => String(row.indicator_parameter_config_id)}
            dataSource={paramRows}
            pagination={{ pageSize: 10, showSizeChanger: false }}
            columns={[
              { title: "ID", dataIndex: "indicator_parameter_config_id", width: 70 },
              { title: "지표", dataIndex: "indicator_code", width: 100 },
              { title: "시장", dataIndex: "market_type", width: 90 },
              { title: "TF", dataIndex: "timeframe", width: 70 },
              { title: "Ver", dataIndex: "version", width: 60 },
              {
                title: "활성",
                dataIndex: "is_active",
                width: 80,
                render: (value: boolean) =>
                  value ? <Tag color="success">ACTIVE</Tag> : <Tag>OFF</Tag>,
              },
              {
                title: "payload",
                dataIndex: "parameter_payload",
                render: (value: Record<string, unknown>) => (
                  <Typography.Text code style={{ fontSize: 11 }}>
                    {JSON.stringify(value)}
                  </Typography.Text>
                ),
              },
              {
                title: "작업",
                key: "actions",
                width: 160,
                render: (_, row) => (
                  <Space size={4}>
                    <Button size="small" onClick={() => openEdit(row)}>
                      수정
                    </Button>
                    {row.is_active ? (
                      <Button
                        size="small"
                        loading={deactivateMutation.isPending}
                        onClick={() =>
                          deactivateMutation.mutate(
                            row.indicator_parameter_config_id,
                          )
                        }
                      >
                        비활성
                      </Button>
                    ) : null}
                  </Space>
                ),
              },
            ]}
          />
        </Space>
      </Card>

      <AdminDataTable<JobHistoryRow>
        title={`최근 실행 이력 — job_name=${JOB_NAME}`}
        loading={historyQuery.isLoading}
        error={historyQuery.error ? toApiError(historyQuery.error) : null}
        rowKey={(row) => String(row.job_run_id)}
        dataSource={historyRows}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: "ID", dataIndex: "job_run_id", width: 80 },
          {
            title: "트리거",
            dataIndex: "trigger_type",
            width: 100,
            render: cell,
          },
          {
            title: "상태",
            dataIndex: "status_code",
            width: 110,
            render: (value: string) => (
              <Tag
                color={
                  value === "SUCCESS"
                    ? "green"
                    : value === "FAILED"
                      ? "red"
                      : value === "RUNNING"
                        ? "processing"
                        : "default"
                }
              >
                {value}
              </Tag>
            ),
          },
          {
            title: "시작",
            dataIndex: "started_at",
            render: cell,
          },
          {
            title: "종료",
            dataIndex: "finished_at",
            render: cell,
          },
          {
            title: "소요(ms)",
            dataIndex: "duration_ms",
            width: 100,
            render: cell,
          },
          {
            title: "오류",
            dataIndex: "error_message",
            render: (value?: string | null) => value ?? "-",
          },
        ]}
      />

      <Modal
        title={
          editTarget
            ? `파라미터 수정 — ${editTarget.indicator_code} v${editTarget.version}`
            : "파라미터 등록"
        }
        open={createOpen || editTarget != null}
        onCancel={() => {
          setCreateOpen(false);
          setEditTarget(null);
          setPreviewResult(null);
          setValidationError(null);
        }}
        footer={null}
        destroyOnHidden
        width={640}
      >
        <Form
          form={editTarget ? form : createForm}
          layout="vertical"
          initialValues={
            editTarget
              ? undefined
              : {
                  market_type: "STOCK",
                  timeframe: "1D",
                  activate: true,
                  indicator_code: "RSI",
                  parameter_payload: '{\n  "period": 14\n}',
                }
          }
          onFinish={(values) => {
            const payload = buildPayloadFromForm(values);
            if (!payload) return;
            if (editTarget) {
              updateMut.mutate({
                id: editTarget.indicator_parameter_config_id,
                body: {
                  parameter_payload: payload,
                  is_active: values.is_active as boolean,
                },
              });
            } else {
              createMut.mutate({
                indicator_code: values.indicator_code as string,
                market_type: values.market_type as string,
                timeframe: values.timeframe as string,
                parameter_payload: payload,
                activate: values.activate as boolean,
              });
            }
          }}
        >
          {!editTarget ? (
            <>
              <Form.Item
                name="indicator_code"
                label="indicator_code"
                rules={[{ required: true }]}
              >
                <Select
                  options={[
                    { value: "MA", label: "MA" },
                    { value: "RSI", label: "RSI" },
                    { value: "MACD", label: "MACD" },
                    { value: "BB", label: "BB" },
                  ]}
                />
              </Form.Item>
              <Form.Item name="market_type" label="market_type">
                <Select
                  options={[
                    { value: "STOCK", label: "STOCK" },
                    { value: "CRYPTO", label: "CRYPTO" },
                  ]}
                />
              </Form.Item>
              <Form.Item name="timeframe" label="timeframe">
                <Input />
              </Form.Item>
              <Form.Item name="activate" label="등록 후 활성화" valuePropName="checked">
                <Switch />
              </Form.Item>
            </>
          ) : (
            <Form.Item name="is_active" label="활성" valuePropName="checked">
              <Switch />
            </Form.Item>
          )}

          <Form.Item
            name="parameter_payload"
            label="parameter_payload (JSON)"
            rules={[{ required: true }]}
          >
            <Input.TextArea rows={8} />
          </Form.Item>

          {validationError ? (
            <Alert
              type="error"
              showIcon
              title="검증 오류"
              description={validationError}
              style={{ marginBottom: 12 }}
            />
          ) : null}

          {previewResult ? (
            <Alert
              type="success"
              showIcon
              title="Preview 결과"
              description={
                <pre style={{ margin: 0, fontSize: 11, whiteSpace: "pre-wrap" }}>
                  {previewResult}
                </pre>
              }
              style={{ marginBottom: 12 }}
            />
          ) : null}

          <Space wrap>
            <Button
              onClick={() => {
                const values = (editTarget ? form : createForm).getFieldsValue();
                const payload = buildPayloadFromForm(values);
                if (!payload) return;
                previewMut.mutate({
                  indicator_code: (editTarget?.indicator_code ??
                    values.indicator_code) as string,
                  market_type: (editTarget?.market_type ??
                    values.market_type) as string,
                  timeframe: (editTarget?.timeframe ??
                    values.timeframe) as string,
                  parameter_payload: payload,
                });
              }}
              loading={previewMut.isPending}
            >
              Preview 검증
            </Button>
            <Button
              type="primary"
              htmlType="submit"
              loading={createMut.isPending || updateMut.isPending}
            >
              저장
            </Button>
          </Space>
        </Form>
      </Modal>
    </AdminPageShell>
  );
}
