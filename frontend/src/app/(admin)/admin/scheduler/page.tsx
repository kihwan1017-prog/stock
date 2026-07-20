"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Input, Space, Tag } from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { PermissionButton } from "@/features/auth/components/PermissionButton";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminSchedulerPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [jobName, setJobName] = useState("");

  const jobs = useQuery({
    queryKey: queryKeys.admin.jobs(),
    queryFn: adminApi.listJobs,
  });
  const history = useQuery({
    queryKey: queryKeys.admin.jobHistory(),
    queryFn: () => adminApi.listJobHistory({ limit: 50 }),
  });

  const execute = useMutation({
    mutationFn: (name: string) => adminApi.executeJob(name),
    onSuccess: () => {
      message.success("잡 실행 요청 완료");
      void qc.invalidateQueries({ queryKey: queryKeys.admin.jobHistory() });
    },
    onError: (e) => {
      const err = toApiError(e);
      if (err.message.toLowerCase().includes("timeout")) {
        message.error(
          "요청 시간 초과 — AI/동기화 잡은 서버에서 계속 실행 중일 수 있습니다. history를 확인하세요.",
        );
        void qc.invalidateQueries({ queryKey: queryKeys.admin.jobHistory() });
        return;
      }
      message.error(err.message);
    },
  });
  const runNow = useMutation({
    mutationFn: (name: string) => adminApi.runSchedulerNow(name),
    onSuccess: () => message.success("scheduler-admin run-now 완료"),
    onError: (e) => message.error(toApiError(e).message),
  });

  const jobRows = extractRows(jobs.data).length
    ? extractRows(jobs.data)
    : Array.isArray(jobs.data)
      ? (jobs.data as Record<string, unknown>[])
      : [];

  return (
    <AdminPageShell
      title="Scheduler 관리"
      description="jobs · jobs/history · scheduler-admin/run-now (AI 잡은 최대 ~3분 대기)"
      extra={
        <Space>
          <Input
            placeholder="job_name"
            value={jobName}
            onChange={(e) => setJobName(e.target.value)}
            style={{ width: 200 }}
          />
          <PermissionButton
            permission="ops:execute"
            type="primary"
            disabled={!jobName}
            loading={execute.isPending}
            onClick={() => execute.mutate(jobName)}
          >
            Execute
          </PermissionButton>
          <Button
            disabled={!jobName}
            loading={runNow.isPending}
            onClick={() => runNow.mutate(jobName)}
          >
            Run Now (Admin)
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <AdminDataTable
          title="GET /jobs"
          loading={jobs.isLoading}
          error={jobs.error ? toApiError(jobs.error) : null}
          rowKey={(r) => cell(r.name ?? JSON.stringify(r))}
          columns={[
            { title: "name", dataIndex: "name", sorter: true },
            { title: "group", dataIndex: "group" },
            { title: "description", dataIndex: "description", ellipsis: true },
            {
              title: "실행",
              render: (_, row) => (
                <PermissionButton
                  permission="ops:execute"
                  size="small"
                  onClick={() => {
                    const name = String(row.name ?? "");
                    setJobName(name);
                    if (name) execute.mutate(name);
                  }}
                >
                  실행
                </PermissionButton>
              ),
            },
          ]}
          dataSource={jobRows}
        />
        <AdminDataTable
          title="GET /jobs/history"
          loading={history.isLoading}
          error={history.error ? toApiError(history.error) : null}
          rowKey={(r) => cell(r.job_run_id ?? JSON.stringify(r))}
          columns={[
            { title: "job", dataIndex: "job_name" },
            {
              title: "status",
              dataIndex: "status_code",
              render: (v) => {
                const code = String(v ?? "").toUpperCase();
                return (
                  <Tag
                    color={
                      code === "FAILED"
                        ? "error"
                        : code === "SUCCESS"
                          ? "success"
                          : "processing"
                    }
                  >
                    {cell(v)}
                  </Tag>
                );
              },
            },
            { title: "started", dataIndex: "started_at" },
            { title: "finished", dataIndex: "finished_at" },
            { title: "error", dataIndex: "error_message", ellipsis: true },
          ]}
          dataSource={extractRows(history.data)}
        />
      </Space>
    </AdminPageShell>
  );
}
