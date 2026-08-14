"use client";

/**
 * STEP 12-1 — AI Candidate -> Strategy Request 승인 게이트 (사용자).
 * Candidate를 즉시 Strategy로 승격하지 않고, 관리자 심사를 위한 Strategy
 * Request를 생성한다. Strategy Draft 생성·Backtest·실거래 승인은
 * 여기서 다루지 않는다(STEP12-2 이후).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Drawer,
  Empty,
  Input,
  InputNumber,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";

import * as userApi from "@/features/user/api/userApi";
import type { StrategyRequestItem } from "@/features/user/api/userApi";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { STRATEGY_REQUEST_STATUS_COLOR } from "@/shared/utils/strategyStatusColors";

const ELIGIBLE_STATUSES = new Set(["PROMOTED", "ACTIVE_REVIEW"]);

const STATUS_COLOR = STRATEGY_REQUEST_STATUS_COLOR;

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : undefined;
}

export default function UserStrategyRequestsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [candidateId, setCandidateId] = useState<number | null>(null);
  const [requestNote, setRequestNote] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [cancelReason, setCancelReason] = useState("");

  const lifecycleQuery = useQuery({
    queryKey: queryKeys.user.strategyRequests.candidateLifecycle(
      candidateId ?? 0,
    ),
    queryFn: () => userApi.getUserAiCandidateLifecycle(candidateId as number),
    enabled: candidateId != null && candidateId > 0,
    retry: false,
  });

  const listQuery = useQuery({
    queryKey: queryKeys.user.strategyRequests.list(),
    queryFn: () => userApi.listStrategyRequests({ limit: 50 }),
  });

  const detailQuery = useQuery({
    queryKey: queryKeys.user.strategyRequests.detail(selectedId ?? 0),
    queryFn: () => userApi.getStrategyRequest(selectedId as number),
    enabled: selectedId != null,
  });

  const invalidateList = async () => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.user.strategyRequests.list(),
    });
  };

  const createMutation = useMutation({
    mutationFn: () =>
      userApi.createStrategyRequest({
        candidate_id: candidateId as number,
        request_note: requestNote.trim() || undefined,
      }),
    onSuccess: async (result) => {
      message.success(
        `Strategy Request #${result.strategy_request_id} 생성됨 — 관리자 심사 대기`,
      );
      setRequestNote("");
      setSelectedId(result.strategy_request_id);
      await invalidateList();
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const cancelMutation = useMutation({
    mutationFn: (id: number) =>
      userApi.cancelStrategyRequest(id, {
        reason: cancelReason.trim() || undefined,
      }),
    onSuccess: async () => {
      message.success("Strategy Request를 취소했습니다.");
      setCancelReason("");
      await invalidateList();
      if (selectedId != null) {
        await queryClient.invalidateQueries({
          queryKey: queryKeys.user.strategyRequests.detail(selectedId),
        });
      }
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const lifecycle = asRecord(lifecycleQuery.data);
  const lifecycleStatus =
    typeof lifecycle?.lifecycle_status === "string"
      ? lifecycle.lifecycle_status
      : undefined;
  const isEligible =
    lifecycleStatus != null && ELIGIBLE_STATUSES.has(lifecycleStatus);

  const items = listQuery.data?.items ?? [];
  const detail = detailQuery.data;

  return (
    <UserPageShell
      title="전략 요청"
      description="AI Candidate를 즉시 전략으로 승격하지 않고, 관리자 심사를 위한 Strategy Request를 생성합니다. 이 화면에서 전략이 자동 배포되거나 주문이 실행되지 않습니다."
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="warning"
          showIcon
          title="Strategy Request는 사람(관리자)의 승인이 있어야 다음 단계로 진행됩니다. 승인 자체가 실거래 승인을 의미하지 않습니다."
        />

        <Card size="small" title="Candidate 조회 & 전략 요청">
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Space wrap>
              <Space.Compact>
                <Input style={{ width: 110 }} value="candidate_id" disabled />
                <InputNumber
                  min={1}
                  placeholder="Candidate ID"
                  value={candidateId ?? undefined}
                  onChange={(v) =>
                    setCandidateId(typeof v === "number" ? v : null)
                  }
                />
              </Space.Compact>
              <Button
                onClick={() => void lifecycleQuery.refetch()}
                loading={lifecycleQuery.isFetching}
                disabled={candidateId == null}
              >
                Candidate 조회
              </Button>
            </Space>

            {lifecycleQuery.isError && (
              <Alert
                type="error"
                showIcon
                title={toApiError(lifecycleQuery.error).message}
              />
            )}

            {lifecycle && (
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Space wrap>
                  <Typography.Text strong>
                    Candidate #{String(lifecycle.candidate_id ?? candidateId)}
                  </Typography.Text>
                  <Tag color={isEligible ? "success" : "default"}>
                    {lifecycleStatus ?? "UNKNOWN"}
                  </Tag>
                  <Tag>{String(lifecycle.health_status ?? "-")}</Tag>
                </Space>
                {!isEligible && (
                  <Alert
                    type="info"
                    showIcon
                    title="ACTIVE 상태(PROMOTED/ACTIVE_REVIEW) Candidate만 전략 요청이 가능합니다."
                  />
                )}
                <Input.TextArea
                  rows={3}
                  placeholder="요청 사유(선택)"
                  value={requestNote}
                  onChange={(e) => setRequestNote(e.target.value)}
                  maxLength={1000}
                />
                <Button
                  type="primary"
                  disabled={!isEligible}
                  loading={createMutation.isPending}
                  onClick={() => createMutation.mutate()}
                >
                  전략 요청
                </Button>
              </Space>
            )}
          </Space>
        </Card>

        <Card size="small" title="내 전략 요청 목록" loading={listQuery.isLoading}>
          {listQuery.isError ? (
            <Alert type="error" title={toApiError(listQuery.error).message} />
          ) : items.length === 0 ? (
            <Empty description="전략 요청 이력이 없습니다." />
          ) : (
            <Table<StrategyRequestItem>
              size="small"
              rowKey={(row) => row.strategy_request_id}
              dataSource={items}
              pagination={{ pageSize: 10 }}
              onRow={(row) => ({
                onClick: () => setSelectedId(row.strategy_request_id),
              })}
              columns={[
                { title: "ID", dataIndex: "strategy_request_id", width: 80 },
                { title: "Candidate", dataIndex: "candidate_id", width: 100 },
                {
                  title: "상태",
                  dataIndex: "status",
                  width: 140,
                  render: (value: string) => (
                    <Tag color={STATUS_COLOR[value] ?? "default"}>
                      {value}
                    </Tag>
                  ),
                },
                { title: "요청일시", dataIndex: "requested_at" },
              ]}
            />
          )}
        </Card>
      </Space>

      <Drawer
        title={
          detail ? `Strategy Request #${detail.strategy_request_id}` : "상세"
        }
        open={selectedId != null}
        onClose={() => setSelectedId(null)}
        size={480}
        destroyOnHidden
      >
        {detailQuery.isLoading ? (
          <Typography.Text type="secondary">불러오는 중…</Typography.Text>
        ) : detail ? (
          <Space orientation="vertical" size={10} style={{ width: "100%" }}>
            <Space wrap>
              <Tag color={STATUS_COLOR[detail.status] ?? "default"}>
                {detail.status}
              </Tag>
              <Tag>Candidate #{detail.candidate_id}</Tag>
            </Space>
            <Typography.Text type="secondary">
              요청 시점 Candidate 상태:{" "}
              {detail.candidate_lifecycle_status_snapshot}
            </Typography.Text>
            {detail.request_note && (
              <Typography.Paragraph>
                <Typography.Text strong>요청 사유</Typography.Text>
                <br />
                {detail.request_note}
              </Typography.Paragraph>
            )}
            {detail.review_note && (
              <Typography.Paragraph>
                <Typography.Text strong>심사 의견</Typography.Text>
                <br />
                {detail.review_note}
              </Typography.Paragraph>
            )}
            <Typography.Text type="secondary">
              요청: {detail.requested_at}
              {detail.reviewed_at ? ` · 심사: ${detail.reviewed_at}` : ""}
              {detail.cancelled_at ? ` · 취소: ${detail.cancelled_at}` : ""}
            </Typography.Text>

            {detail.status === "PENDING_REVIEW" && (
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Input.TextArea
                  rows={2}
                  placeholder="취소 사유(선택)"
                  value={cancelReason}
                  onChange={(e) => setCancelReason(e.target.value)}
                  maxLength={1000}
                />
                <Button
                  danger
                  loading={cancelMutation.isPending}
                  onClick={() =>
                    cancelMutation.mutate(detail.strategy_request_id)
                  }
                >
                  요청 취소
                </Button>
              </Space>
            )}
          </Space>
        ) : null}
      </Drawer>
    </UserPageShell>
  );
}
