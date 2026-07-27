"use client";

/**
 * STEP 11-12 — Candidate Promotion Gateway.
 * Create/Validate/Dry-run/Approve ≠ Candidate INSERT.
 * Commit(confirm) 만 Candidate 등록. 매매·전략·주문 아님.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Input,
  InputNumber,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const REFERENCE_DISCLAIMER =
  "Candidate Promotion은 검토된 AI 결과를 기존 후보 엔진에 수동 등록하는 관리 작업이며, " +
  "매수·매도·전략·주문 승인이 아닙니다. Commit 완료 시에만 Candidate가 생성됩니다.";

export default function AdminAiCandidatePromotionsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [queueId, setQueueId] = useState<number | null>(1);
  const [warningAck, setWarningAck] = useState(false);
  const [commitConfirm, setCommitConfirm] = useState(false);
  const [dryPreview, setDryPreview] = useState("");

  const listQuery = useQuery({
    queryKey: queryKeys.admin.aiCandidatePromotions(),
    queryFn: () => adminApi.listAiCandidatePromotions(),
  });
  const items = extractRows(asRecord(listQuery.data)?.items);

  const detailQuery = useQuery({
    queryKey: ["admin", "ai-candidate-promotion", selectedId],
    queryFn: () => adminApi.getAiCandidatePromotion(selectedId!),
    enabled: selectedId != null,
  });
  const detail = asRecord(asRecord(detailQuery.data)?.promotion) ?? {};

  const historyQuery = useQuery({
    queryKey: ["admin", "ai-candidate-promotion-history", selectedId],
    queryFn: () => adminApi.getAiCandidatePromotionHistory(selectedId!),
    enabled: selectedId != null,
  });
  const historyItems = extractRows(asRecord(historyQuery.data)?.items);

  const dashQuery = useQuery({
    queryKey: ["admin", "ai-candidate-promotion-dashboard"],
    queryFn: adminApi.getAiCandidatePromotionDashboard,
  });
  const dash = asRecord(dashQuery.data) ?? {};
  const statusCounts = asRecord(dash.status_counts) ?? {};

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.admin.aiCandidatePromotions(),
    });
    queryClient.invalidateQueries({
      queryKey: ["admin", "ai-candidate-promotion-dashboard"],
    });
    if (selectedId != null) {
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-candidate-promotion", selectedId],
      });
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-candidate-promotion-history", selectedId],
      });
    }
  };

  const requireReason = () => {
    if (!reason.trim()) {
      message.error("reason 필요");
      return false;
    }
    return true;
  };

  const requireSelected = () => {
    if (selectedId == null) {
      message.error("Promotion 선택 필요");
      return false;
    }
    return true;
  };

  const createMut = useMutation({
    mutationFn: () =>
      adminApi.createAiCandidatePromotion({
        queue_id: queueId,
        reason,
        idempotency_key: `promo-${Date.now()}`,
      }),
    onSuccess: (data) => {
      message.success("Promotion Request 생성 (Candidate Insert 0)");
      const id = asRecord(asRecord(data)?.promotion)?.id;
      if (typeof id === "number") setSelectedId(id);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const validateMut = useMutation({
    mutationFn: () =>
      adminApi.validateAiCandidatePromotion(selectedId!, { reason }),
    onSuccess: () => {
      message.success("Validate 완료 (Candidate Insert 0)");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const dryMut = useMutation({
    mutationFn: () =>
      adminApi.dryRunAiCandidatePromotion(selectedId!, { reason }),
    onSuccess: (data) => {
      message.success("Dry-run 완료 (Candidate Insert 0)");
      setDryPreview(JSON.stringify(data, null, 2));
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const submitFirstMut = useMutation({
    mutationFn: () =>
      adminApi.submitFirstApprovalAiCandidatePromotion(selectedId!, {
        reason,
      }),
    onSuccess: () => {
      message.success("1차 승인 요청");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const approveFirstMut = useMutation({
    mutationFn: () =>
      adminApi.approveFirstAiCandidatePromotion(selectedId!, { reason }),
    onSuccess: () => {
      message.success("1차 승인 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const submitFinalMut = useMutation({
    mutationFn: () =>
      adminApi.submitFinalApprovalAiCandidatePromotion(selectedId!, {
        reason,
      }),
    onSuccess: () => {
      message.success("최종 승인 요청");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const approveFinalMut = useMutation({
    mutationFn: () =>
      adminApi.approveFinalAiCandidatePromotion(selectedId!, {
        reason,
        warning_acknowledgements: { acknowledged: warningAck },
      }),
    onSuccess: () => {
      message.success("최종 승인 완료 (아직 Candidate Insert 0)");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const commitMut = useMutation({
    mutationFn: () =>
      adminApi.commitAiCandidatePromotion(selectedId!, {
        confirm: true,
        reason,
        idempotency_key: `commit-${selectedId}-${Date.now()}`,
      }),
    onSuccess: () => {
      message.success("Commit 완료 — Candidate 등록 (매매 아님)");
      setCommitConfirm(false);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const cancelMut = useMutation({
    mutationFn: () =>
      adminApi.cancelAiCandidatePromotion(selectedId!, { reason }),
    onSuccess: () => {
      message.success("취소됨");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const rollbackMut = useMutation({
    mutationFn: () =>
      adminApi.rollbackAiCandidatePromotion(selectedId!, { reason }),
    onSuccess: () => {
      message.success("Rollback 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  return (
    <AdminPageShell title="Candidate Promotion Gateway">
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <Alert type="warning" showIcon title={REFERENCE_DISCLAIMER} />

        <Space wrap>
          <Tag>DRAFT: {cell(statusCounts.DRAFT)}</Tag>
          <Tag>Validated: {cell(statusCounts.VALIDATED)}</Tag>
          <Tag>Dry-run: {cell(statusCounts.DRY_RUN_COMPLETED)}</Tag>
          <Tag>Commit Pending: {cell(statusCounts.COMMIT_PENDING)}</Tag>
          <Tag color="green">Completed: {cell(statusCounts.COMPLETED)}</Tag>
          <Tag>Created Today: {cell(dash.completed_today)}</Tag>
        </Space>

        <Space wrap>
          <Space.Compact>
            <Input style={{ width: 80 }} value="reason" disabled />
            <Input
              placeholder="reason (필수)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              style={{ width: 280 }}
            />
          </Space.Compact>
          <Space.Compact>
            <Input style={{ width: 90 }} value="queue_id" disabled />
            <InputNumber
              min={1}
              value={queueId ?? undefined}
              onChange={(v) => setQueueId(typeof v === "number" ? v : null)}
            />
          </Space.Compact>
          <Button
            type="primary"
            onClick={() => {
              if (!requireReason() || queueId == null) return;
              createMut.mutate();
            }}
          >
            Promotion 요청 생성
          </Button>
          <Typography.Link href={adminRoutes.aiCandidateRecommendationQueues}>
            검토 큐로 이동
          </Typography.Link>
        </Space>

        <Table
          size="small"
          loading={listQuery.isLoading}
          dataSource={items}
          rowKey={(r) => String(asRecord(r)?.id ?? asRecord(r)?.promotion_request_id)}
          pagination={{ pageSize: 10 }}
          onRow={(r) => ({
            onClick: () => {
              const id = asRecord(r)?.id ?? asRecord(r)?.promotion_request_id;
              if (typeof id === "number") setSelectedId(id);
            },
          })}
          columns={[
            { title: "ID", dataIndex: "id", width: 80, render: cell },
            { title: "Queue", dataIndex: "queue_id", width: 90, render: cell },
            { title: "Symbol", dataIndex: "symbol", width: 100, render: cell },
            { title: "Exchange", dataIndex: "exchange_code", width: 90, render: cell },
            { title: "Status", dataIndex: "promotion_status", render: cell },
            { title: "Decision", dataIndex: "queue_decision_snapshot", render: cell },
          ]}
        />

        {selectedId != null && (
          <Space orientation="vertical" style={{ width: "100%" }} size="small">
            <Typography.Title level={5}>
              상세 #{selectedId} / {cell(detail.promotion_status)}
            </Typography.Title>
            <Typography.Paragraph>
              Symbol={cell(detail.symbol)} / Exchange={cell(detail.exchange_code)} /
              Queue={cell(detail.queue_id)} / Run={cell(detail.candidate_run_id)} /
              Result={cell(detail.candidate_result_id)}
            </Typography.Paragraph>

            <Space wrap>
              <Button
                onClick={() => {
                  if (!requireReason() || !requireSelected()) return;
                  validateMut.mutate();
                }}
              >
                Validate
              </Button>
              <Button
                onClick={() => {
                  if (!requireReason() || !requireSelected()) return;
                  dryMut.mutate();
                }}
              >
                Dry-run
              </Button>
              <Button
                onClick={() => {
                  if (!requireReason() || !requireSelected()) return;
                  submitFirstMut.mutate();
                }}
              >
                1차 승인 요청
              </Button>
              <Button
                onClick={() => {
                  if (!requireReason() || !requireSelected()) return;
                  approveFirstMut.mutate();
                }}
              >
                1차 승인
              </Button>
              <Button
                onClick={() => {
                  if (!requireReason() || !requireSelected()) return;
                  submitFinalMut.mutate();
                }}
              >
                최종 승인 요청
              </Button>
              <Button
                onClick={() => {
                  if (!requireReason() || !requireSelected()) return;
                  approveFinalMut.mutate();
                }}
              >
                최종 승인
              </Button>
              <Checkbox
                checked={warningAck}
                onChange={(e) => setWarningAck(e.target.checked)}
              >
                Warning 확인
              </Checkbox>
            </Space>

            <Space wrap>
              <Checkbox
                checked={commitConfirm}
                onChange={(e) => setCommitConfirm(e.target.checked)}
              >
                Commit 확인 (Strategy/Order/LIVE=0)
              </Checkbox>
              <Button
                type="primary"
                danger
                disabled={!commitConfirm}
                onClick={() => {
                  if (!requireReason() || !requireSelected() || !commitConfirm) {
                    message.error("commit confirm 필요");
                    return;
                  }
                  commitMut.mutate();
                }}
              >
                Commit (Candidate 등록만)
              </Button>
              <Button
                onClick={() => {
                  if (!requireReason() || !requireSelected()) return;
                  cancelMut.mutate();
                }}
              >
                Cancel
              </Button>
              <Button
                onClick={() => {
                  if (!requireReason() || !requireSelected()) return;
                  rollbackMut.mutate();
                }}
              >
                Rollback
              </Button>
            </Space>

            {dryPreview && (
              <Typography.Paragraph>
                <pre style={{ maxHeight: 240, overflow: "auto" }}>{dryPreview}</pre>
              </Typography.Paragraph>
            )}

            <Table
              size="small"
              dataSource={historyItems}
              rowKey={(r) =>
                String(
                  asRecord(r)?.id ??
                    asRecord(r)?.history_id ??
                    `${asRecord(r)?.action}-${asRecord(r)?.created_at}`,
                )
              }
              pagination={false}
              columns={[
                { title: "Action", dataIndex: "action", render: cell },
                { title: "From", dataIndex: "previous_status", render: cell },
                { title: "To", dataIndex: "new_status", render: cell },
                { title: "By", dataIndex: "requested_by", render: cell },
              ]}
            />
          </Space>
        )}
      </Space>
    </AdminPageShell>
  );
}
