"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { JOB_STATUS_COLOR } from "@/features/admin/market/jobStatusColors";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

export { JOB_STATUS_COLOR };

/** 재시도/취소/만료Claim 해제 등 사유 입력이 필요한 액션을 위한 공용 모달 */
function useReasonPrompt() {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [onConfirm, setOnConfirm] = useState<((reason: string) => void) | null>(
    null,
  );

  const prompt = (handler: (reason: string) => void) => {
    setReason("");
    setOnConfirm(() => handler);
    setOpen(true);
  };

  const modal = (
    <Modal
      title="사유 입력"
      open={open}
      onCancel={() => setOpen(false)}
      onOk={() => {
        if (reason.trim().length < 3) return;
        onConfirm?.(reason.trim());
        setOpen(false);
      }}
      okText="확인"
    >
      <Input.TextArea
        rows={3}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="최소 3자 이상 입력하세요"
      />
    </Modal>
  );

  return { prompt, modal };
}

/** STEP 8-5-15 — 영속 Market Session Job Admin 패널 (DB Source of Truth) */
export function MarketSessionJobsPanel() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string | undefined>(
    undefined,
  );
  const { prompt, modal } = useReasonPrompt();

  const jobsQuery = useQuery({
    queryKey: ["admin", "market-session-jobs", statusFilter],
    queryFn: () =>
      adminApi.listAdminMarketSessionJobs({
        exchange_code: "KRX",
        status_code: statusFilter,
        limit: 100,
      }),
  });

  const healthQuery = useQuery({
    queryKey: ["admin", "market-session-jobs-health"],
    queryFn: () => adminApi.getAdminMarketSessionJobHealth(),
    refetchInterval: 15_000,
  });

  const invalidateAll = async () => {
    await qc.invalidateQueries({ queryKey: ["admin", "market-session-jobs"] });
    await qc.invalidateQueries({
      queryKey: ["admin", "market-session-jobs-health"],
    });
  };

  const reconcileMut = useMutation({
    mutationFn: (reason: string) =>
      adminApi.reconcileAdminMarketSessionJobs({ reason }),
    onSuccess: invalidateAll,
  });

  const runNowMut = useMutation({
    mutationFn: (vars: { jobId: number; reason: string }) =>
      adminApi.runNowAdminMarketSessionJob(vars.jobId, vars.reason),
    onSuccess: invalidateAll,
  });

  const retryMut = useMutation({
    mutationFn: (vars: { jobId: number; reason: string }) =>
      adminApi.retryAdminMarketSessionJob(vars.jobId, vars.reason),
    onSuccess: invalidateAll,
  });

  const cancelMut = useMutation({
    mutationFn: (vars: { jobId: number; reason: string }) =>
      adminApi.cancelAdminMarketSessionJob(vars.jobId, vars.reason),
    onSuccess: invalidateAll,
  });

  const releaseMut = useMutation({
    mutationFn: (vars: { jobId: number; reason: string }) =>
      adminApi.releaseStaleClaimAdminMarketSessionJob(vars.jobId, vars.reason),
    onSuccess: invalidateAll,
  });

  const rows = extractRows(jobsQuery.data);
  const health = asRecord(healthQuery.data);
  const scheduler = asRecord(health?.scheduler);
  const busy =
    reconcileMut.isPending ||
    runNowMut.isPending ||
    retryMut.isPending ||
    cancelMut.isPending ||
    releaseMut.isPending;

  return (
    <Card
      size="small"
      title="영속 Market Session Job (STEP 8-5-15)"
      extra={
        <Space>
          <Select
            allowClear
            placeholder="상태 필터"
            style={{ width: 160 }}
            value={statusFilter}
            onChange={(v) => setStatusFilter(v)}
            options={Object.keys(JOB_STATUS_COLOR).map((v) => ({
              value: v,
              label: v,
            }))}
          />
          <Button
            loading={jobsQuery.isFetching || healthQuery.isFetching}
            onClick={() => {
              void jobsQuery.refetch();
              void healthQuery.refetch();
            }}
          >
            새로고침
          </Button>
          <Button
            type="primary"
            disabled={busy}
            loading={reconcileMut.isPending}
            onClick={() =>
              prompt((reason) => reconcileMut.mutate(reason))
            }
          >
            Reconcile
          </Button>
        </Space>
      }
    >
      {healthQuery.isError ? (
        <Alert
          type="error"
          showIcon
          message="Health 조회 실패"
          description={toApiError(healthQuery.error).message}
          style={{ marginBottom: 12 }}
        />
      ) : null}
      {reconcileMut.isError ? (
        <Alert
          type="error"
          showIcon
          message="Reconcile 실패"
          description={toApiError(reconcileMut.error).message}
          style={{ marginBottom: 12 }}
          closable
        />
      ) : null}

      <Descriptions size="small" bordered column={4} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="Due">{cell(health?.due_count)}</Descriptions.Item>
        <Descriptions.Item label="Running">
          {cell(health?.running_count)}
        </Descriptions.Item>
        <Descriptions.Item label="Failed">
          {cell(health?.failed_count)}
        </Descriptions.Item>
        <Descriptions.Item label="Superseded">
          {cell(health?.superseded_count)}
        </Descriptions.Item>
        <Descriptions.Item label="평균 Lag(초)">
          {cell(health?.average_lag_seconds)}
        </Descriptions.Item>
        <Descriptions.Item label="Scheduler 동작중">
          {scheduler?.running ? (
            <Tag color="green">Y</Tag>
          ) : (
            <Tag color="red">N</Tag>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="다음 Dispatch">
          {cell(scheduler?.dispatch_next_run_at)}
        </Descriptions.Item>
        <Descriptions.Item label="다음 Reconcile">
          {cell(scheduler?.reconcile_next_run_at)}
        </Descriptions.Item>
      </Descriptions>

      <Table
        size="small"
        rowKey={(r) => String(asRecord(r)?.job_id ?? Math.random())}
        loading={jobsQuery.isLoading}
        dataSource={rows}
        pagination={{ pageSize: 15 }}
        columns={[
          { title: "ID", dataIndex: "job_id", width: 70, render: cell },
          { title: "날짜", dataIndex: "market_date", width: 110, render: cell },
          { title: "Job Type", dataIndex: "job_type", render: cell },
          { title: "Rev", dataIndex: "calendar_revision", width: 60, render: cell },
          {
            title: "상태",
            dataIndex: "status_code",
            render: (v) => (
              <Tag color={JOB_STATUS_COLOR[String(v)] ?? "default"}>
                {cell(v)}
              </Tag>
            ),
          },
          {
            title: "실행 예정",
            dataIndex: "scheduled_for",
            render: (v) => cell(v),
          },
          {
            title: "Attempt",
            key: "attempt",
            width: 90,
            render: (_, row) => {
              const r = asRecord(row);
              return `${cell(r?.attempt_count)}/${cell(r?.max_attempts)}`;
            },
          },
          {
            title: "Claim",
            dataIndex: "claimed_by",
            render: (v) => cell(v),
          },
          {
            title: "오류",
            dataIndex: "last_error_summary",
            render: (v) => cell(v),
          },
          {
            title: "작업",
            key: "actions",
            render: (_, row) => {
              const r = asRecord(row);
              const jobId = Number(r?.job_id);
              const status = String(r?.status_code ?? "");
              const isTerminal = [
                "SUCCEEDED",
                "SKIPPED",
                "SUPERSEDED",
                "CANCELLED",
              ].includes(status);
              return (
                <Space wrap>
                  <Button
                    size="small"
                    disabled={busy}
                    onClick={() =>
                      prompt((reason) =>
                        runNowMut.mutate({ jobId, reason }),
                      )
                    }
                  >
                    즉시 실행
                  </Button>
                  {["FAILED", "SKIPPED", "RETRY_PENDING", "EXPIRED"].includes(
                    status,
                  ) ? (
                    <Button
                      size="small"
                      disabled={busy}
                      onClick={() =>
                        prompt((reason) =>
                          retryMut.mutate({ jobId, reason }),
                        )
                      }
                    >
                      재시도
                    </Button>
                  ) : null}
                  {status === "EXPIRED" || status === "CLAIMED" ? (
                    <Button
                      size="small"
                      disabled={busy}
                      onClick={() =>
                        prompt((reason) =>
                          releaseMut.mutate({ jobId, reason }),
                        )
                      }
                    >
                      Claim 해제
                    </Button>
                  ) : null}
                  {!isTerminal ? (
                    <Button
                      size="small"
                      danger
                      disabled={busy}
                      onClick={() =>
                        Modal.confirm({
                          title: "취소 확인",
                          content: `Job #${jobId} 를 취소합니다.`,
                          onOk: () =>
                            prompt((reason) =>
                              cancelMut.mutate({ jobId, reason }),
                            ),
                        })
                      }
                    >
                      취소
                    </Button>
                  ) : null}
                </Space>
              );
            },
          },
        ]}
      />
      {[runNowMut, retryMut, cancelMut, releaseMut].map((mut, idx) =>
        mut.isError ? (
          <Typography.Text type="danger" key={idx}>
            {toApiError(mut.error).message}
          </Typography.Text>
        ) : null,
      )}
      {modal}
    </Card>
  );
}
