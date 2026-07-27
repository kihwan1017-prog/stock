"use client";

import { useQuery } from "@tanstack/react-query";
import { Tag } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell } from "@/features/admin/utils/dataHelpers";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";
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

export default function AdminIndicatorsPage() {
  const historyQuery = useQuery({
    queryKey: [...queryKeys.admin.jobHistory(), JOB_NAME],
    queryFn: () =>
      adminApi.listJobHistory({ job_name: JOB_NAME, limit: 50 }),
  });

  const payload = asRecord(historyQuery.data);
  const rows = (
    Array.isArray(payload?.items) ? payload.items : []
  ) as JobHistoryRow[];

  return (
    <AdminPageShell
      title="기술지표 관리"
      description="지표 배치(indicator_daily_batch) 실행 이력 — 실 API: GET /api/v1/jobs/history"
    >
      <UnimplementedNotice
        feature="기술지표 파라미터 관리"
        reason="이동평균 기간, RSI/MACD 설정 등 지표 파라미터를 CRUD하는 API가 아직 없습니다. 지표는 코드에 고정된 기본값(MA5/20/60, RSI14, MACD 12/26/9 등)으로 계산됩니다."
        relatedApis={[
          "POST /api/v1/indicators/daily/batch/compute",
          "GET /api/v1/indicators/daily/{exchange_code}/{symbol}",
          "TODO: 지표 파라미터 설정 CRUD API",
        ]}
      />

      <AdminDataTable<JobHistoryRow>
        title={`최근 실행 이력 — job_name=${JOB_NAME}`}
        loading={historyQuery.isLoading}
        error={historyQuery.error ? toApiError(historyQuery.error) : null}
        rowKey={(row) => String(row.job_run_id)}
        dataSource={rows}
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
    </AdminPageShell>
  );
}
