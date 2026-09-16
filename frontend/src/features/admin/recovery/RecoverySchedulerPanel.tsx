"use client";

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
  message as antdMessage,
} from "antd";
import { useState } from "react";

import type { RecoverySchedulerJob } from "@/features/admin/api/adminApi";
import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

function formatTs(value: string | null | undefined): string {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString("ko-KR");
  } catch {
    return String(value);
  }
}

/**
 * STEP 8-5-3 — Recovery Scheduler Job 관리 (실 API).
 */
export function RecoverySchedulerPanel() {
  const [messageApi, contextHolder] = antdMessage.useMessage();
  const queryClient = useQueryClient();
  const [editJob, setEditJob] = useState<RecoverySchedulerJob | null>(null);
  const [editForm] = Form.useForm();

  const jobsQuery = useQuery({
    queryKey: ["admin", "recovery-scheduler-jobs"],
    queryFn: () => adminApi.listRecoverySchedulerJobs(),
  });

  const runsQuery = useQuery({
    queryKey: ["admin", "recovery-scheduler-runs"],
    queryFn: () => adminApi.listRecoverySchedulerRuns({ limit: 20 }),
  });

  const statusQuery = useQuery({
    queryKey: ["admin", "recovery-scheduler-status"],
    queryFn: () => adminApi.getRecoverySchedulerStatus(),
  });

  const invalidate = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["admin", "recovery-scheduler"],
    });
    await queryClient.invalidateQueries({
      queryKey: ["admin", "recovery-scheduler-jobs"],
    });
    await queryClient.invalidateQueries({
      queryKey: ["admin", "recovery-scheduler-runs"],
    });
    await queryClient.invalidateQueries({
      queryKey: ["admin", "recovery-scheduler-status"],
    });
  };

  const toggleMutation = useMutation({
    mutationFn: async (row: RecoverySchedulerJob) => {
      if (row.is_enabled) {
        return adminApi.disableRecoverySchedulerJob(row.job_id);
      }
      return adminApi.enableRecoverySchedulerJob(row.job_id);
    },
    onSuccess: async () => {
      messageApi.success("Job 활성 상태를 변경했습니다.");
      await invalidate();
    },
    onError: (e) => messageApi.error(toApiError(e).message),
  });

  const runMutation = useMutation({
    mutationFn: (jobId: string) =>
      adminApi.runRecoverySchedulerJobNow(jobId),
    onSuccess: async (result) => {
      const row = asRecord(result);
      messageApi.success(
        `즉시 실행 완료: ${String(row?.status ?? "OK")}`,
      );
      await invalidate();
    },
    onError: (e) => messageApi.error(toApiError(e).message),
  });

  const updateMutation = useMutation({
    mutationFn: (values: {
      job_id: string;
      interval_minutes?: number;
      cron_expression?: string;
      timeout_seconds?: number;
      max_retries?: number;
      concurrency?: number;
    }) => {
      const { job_id, ...body } = values;
      return adminApi.updateRecoverySchedulerJob(job_id, body);
    },
    onSuccess: async () => {
      messageApi.success("Job 설정을 저장했습니다.");
      setEditJob(null);
      await invalidate();
    },
    onError: (e) => messageApi.error(toApiError(e).message),
  });

  const jobs = jobsQuery.data?.items ?? [];
  const runRows = extractRows(runsQuery.data);
  const runtime = asRecord(statusQuery.data);
  const pending =
    toggleMutation.isPending ||
    runMutation.isPending ||
    updateMutation.isPending;

  return (
    <Card
      size="small"
      title="Recovery Scheduler"
      extra={
        <Tag color={runtime?.running ? "green" : "default"}>
          {runtime?.running ? "APScheduler Running" : "Stopped"}
        </Tag>
      }
    >
      {contextHolder}
      <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
        키움(장 전·후 Cron, Asia/Seoul) · 업비트 Interval · Paper 정합성 · 실패
        재시도. 기존 BrokerRecoveryManager·계좌 Lock을 재사용합니다.
      </Typography.Paragraph>

      <Table<RecoverySchedulerJob>
        size="small"
        rowKey="job_id"
        loading={jobsQuery.isLoading}
        dataSource={jobs}
        pagination={false}
        scroll={{ x: 1100 }}
        columns={[
          {
            title: "작업",
            dataIndex: "display_name",
            render: (name: string, row) => (
              <Space orientation="vertical" size={0}>
                <Typography.Text strong>{name}</Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {row.job_id}
                </Typography.Text>
              </Space>
            ),
          },
          {
            title: "거래소/증권사",
            dataIndex: "broker_code",
            width: 90,
            render: (v: string) => <Tag>{v}</Tag>,
          },
          {
            title: "트리거",
            width: 160,
            render: (_: unknown, row) =>
              row.trigger_type === "CRON"
                ? `CRON ${row.cron_expression ?? ""}`
                : `INTERVAL ${row.interval_minutes ?? "-"}m`,
          },
          {
            title: "활성",
            dataIndex: "is_enabled",
            width: 70,
            render: (v: boolean) =>
              v ? <Tag color="green">ON</Tag> : <Tag>OFF</Tag>,
          },
          {
            title: "최근 상태",
            dataIndex: "last_status",
            width: 110,
            render: (v: string | null) => v ?? "-",
          },
          {
            title: "성공/실패/Skip",
            width: 140,
            render: (_: unknown, row) => {
              const s = row.last_result_summary ?? {};
              return `${s.success_count ?? "-"} / ${s.failed_count ?? "-"} / ${s.skipped_count ?? "-"}`;
            },
          },
          {
            title: "마지막 실행",
            dataIndex: "last_run_at",
            width: 160,
            render: formatTs,
          },
          {
            title: "다음 실행",
            dataIndex: "next_run_at",
            width: 160,
            render: formatTs,
          },
          {
            title: "작업",
            key: "actions",
            width: 260,
            fixed: "right",
            render: (_: unknown, row) => (
              <Space wrap size={4}>
                <Button
                  size="small"
                  disabled={pending}
                  loading={toggleMutation.isPending}
                  onClick={() => toggleMutation.mutate(row)}
                >
                  {row.is_enabled ? "비활성" : "활성"}
                </Button>
                <Button
                  size="small"
                  type="primary"
                  ghost
                  disabled={pending}
                  loading={runMutation.isPending}
                  onClick={() => runMutation.mutate(row.job_id)}
                >
                  즉시 실행
                </Button>
                <Button
                  size="small"
                  disabled={pending}
                  onClick={() => {
                    // destroyOnHidden 시 Form 연결 전 setFieldsValue 금지
                    setEditJob(row);
                  }}
                >
                  설정
                </Button>
              </Space>
            ),
          },
        ]}
      />

      {jobsQuery.isError ? (
        <Typography.Text type="danger">
          {toApiError(jobsQuery.error).message}
        </Typography.Text>
      ) : null}

      <Typography.Title level={5} style={{ marginTop: 16 }}>
        Scheduler Job 실행 이력
      </Typography.Title>
      <Table
        size="small"
        rowKey={(r) => String(asRecord(r)?.job_run_id ?? Math.random())}
        loading={runsQuery.isLoading}
        dataSource={runRows}
        pagination={false}
        columns={[
          {
            title: "번호",
            dataIndex: "job_run_id",
            width: 70,
          },
          { title: "작업", dataIndex: "job_name" },
          { title: "트리거", dataIndex: "trigger_type", width: 110 },
          { title: "상태", dataIndex: "status_code", width: 90 },
          {
            title: "시작",
            dataIndex: "started_at",
            render: formatTs,
          },
          {
            title: "요약",
            render: (_: unknown, row: unknown) => {
              const r = asRecord(row);
              const payload = asRecord(r?.result_payload);
              if (!payload) return r?.error_message ?? "-";
              return `ok=${payload.success_count ?? "-"} fail=${payload.failed_count ?? "-"} skip=${payload.skipped_count ?? "-"}`;
            },
          },
        ]}
      />

      <Form
        form={editForm}
        component={false}
        layout="vertical"
        onFinish={(values) => {
          if (!editJob) return;
          if (
            editJob.trigger_type === "INTERVAL" &&
            values.interval_minutes != null &&
            values.interval_minutes < 5
          ) {
            messageApi.error("Interval 최소 5분입니다.");
            return;
          }
          if (
            values.timeout_seconds != null &&
            values.timeout_seconds <= 0
          ) {
            messageApi.error("Timeout은 양수여야 합니다.");
            return;
          }
          updateMutation.mutate({
            job_id: editJob.job_id,
            ...values,
          });
        }}
      >
      <Modal
        title={editJob ? `설정 — ${editJob.display_name}` : "설정"}
        open={editJob !== null}
        onCancel={() => setEditJob(null)}
        onOk={() => editForm.submit()}
        confirmLoading={updateMutation.isPending}
        forceRender
        afterOpenChange={(opened) => {
          if (!opened || !editJob) return;
          editForm.setFieldsValue({
            cron_expression: editJob.cron_expression ?? undefined,
            interval_minutes: editJob.interval_minutes ?? undefined,
            timeout_seconds: editJob.timeout_seconds,
            max_retries: editJob.max_retries,
            concurrency: editJob.concurrency,
          });
        }}
      >
          {editJob?.trigger_type === "CRON" ? (
            <Form.Item
              name="cron_expression"
              label="Cron (min hour dom mon dow)"
              rules={[{ required: true, message: "Cron 필요" }]}
            >
              <Input placeholder="30 8 * * mon-fri" />
            </Form.Item>
          ) : (
            <Form.Item
              name="interval_minutes"
              label="Interval (분)"
              rules={[{ required: true, message: "Interval 필요" }]}
            >
              <InputNumber min={5} max={10080} style={{ width: "100%" }} />
            </Form.Item>
          )}
          <Form.Item name="timeout_seconds" label="Timeout (초)">
            <InputNumber min={1} max={3600} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="max_retries" label="Max Retries">
            <InputNumber min={0} max={20} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="concurrency" label="동시 실행 수">
            <InputNumber min={1} max={10} style={{ width: "100%" }} />
          </Form.Item>
      </Modal>
      </Form>
    </Card>
  );
}
