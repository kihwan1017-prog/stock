"use client";

import { useQuery } from "@tanstack/react-query";
import { Space } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminBatchPage() {
  const jobs = useQuery({
    queryKey: queryKeys.admin.jobs(),
    queryFn: adminApi.listJobs,
  });
  const pipeline = useQuery({
    queryKey: queryKeys.admin.pipelineLatest(),
    queryFn: adminApi.getLatestPipeline,
  });
  const reports = useQuery({
    queryKey: queryKeys.admin.dailyReports(),
    queryFn: () => adminApi.listDailyReports({ limit: 20 }),
  });

  const jobRows = Array.isArray(jobs.data)
    ? (jobs.data as Record<string, unknown>[])
    : extractRows(jobs.data);

  return (
    <AdminPageShell title="배치 관리" description="jobs · pipelines/latest · daily-reports">
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <AdminDataTable
          title="등록 Job (GET /jobs)"
          loading={jobs.isLoading}
          error={jobs.error ? toApiError(jobs.error) : null}
          rowKey={(r) => cell(r.name ?? JSON.stringify(r))}
          columns={[
            { title: "name", dataIndex: "name", sorter: true },
            { title: "group", dataIndex: "group" },
            { title: "description", dataIndex: "description", ellipsis: true },
          ]}
          dataSource={jobRows}
        />
        <AdminJsonCard
          title="GET /pipelines/latest"
          loading={pipeline.isLoading}
          error={pipeline.error ? toApiError(pipeline.error) : null}
          data={pipeline.data}
        />
        <AdminDataTable
          title="GET /daily-reports"
          loading={reports.isLoading}
          error={reports.error ? toApiError(reports.error) : null}
          rowKey={(r) => cell(r.report_date ?? JSON.stringify(r))}
          columns={[
            { title: "date", dataIndex: "report_date", sorter: true },
            { title: "exchange", dataIndex: "exchange_code" },
            { title: "status", dataIndex: "status" },
          ]}
          dataSource={extractRows(reports.data)}
        />
      </Space>
    </AdminPageShell>
  );
}
