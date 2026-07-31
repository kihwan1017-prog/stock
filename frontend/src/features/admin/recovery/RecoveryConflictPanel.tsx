"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Descriptions,
  Drawer,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message as antdMessage,
} from "antd";
import { useState } from "react";

import type { RecoveryConflictItem } from "@/features/admin/api/adminApi";
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

const REVIEW_COLORS: Record<string, string> = {
  PENDING_REVIEW: "orange",
  ON_HOLD: "gold",
  APPROVED_IMPORT: "green",
  IGNORED: "default",
  REMOTE_DISAPPEARED: "purple",
  RESOLVED: "blue",
  REJECTED: "red",
  HISTORICAL_PRESERVED: "cyan",
};

const REVIEW_LABELS: Record<string, string> = {
  PENDING_REVIEW: "Review Required",
  ON_HOLD: "On Hold",
  APPROVED_IMPORT: "Review Complete (Import)",
  IGNORED: "Review Complete (Ignored)",
  REMOTE_DISAPPEARED: "Review Complete",
  RESOLVED: "Review Complete",
  REJECTED: "Rejected",
  HISTORICAL_PRESERVED: "Review Complete (History Preserved)",
};

/**
 * STEP 8-5-4 — Upbit Remote-only Conflict 검토 패널.
 * 승인은 외부 재주문 없이 내부 기록 Import만 수행한다.
 */
export function RecoveryConflictPanel() {
  const [messageApi, contextHolder] = antdMessage.useMessage();
  const [modalApi, modalContextHolder] = Modal.useModal();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string | undefined>(
    "PENDING_REVIEW",
  );
  const [detailId, setDetailId] = useState<number | null>(null);
  const [noteForm] = Form.useForm();

  const listQuery = useQuery({
    queryKey: ["admin", "recovery-conflicts", statusFilter ?? "all"],
    queryFn: () =>
      adminApi.listRecoveryConflicts({
        broker_code: "UPBIT",
        review_status: statusFilter,
        limit: 100,
      }),
  });

  const detailQuery = useQuery({
    queryKey: ["admin", "recovery-conflict", detailId],
    queryFn: () => adminApi.getRecoveryConflict(detailId!),
    enabled: detailId != null && detailId > 0,
  });

  const invalidate = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["admin", "recovery-conflicts"],
    });
    await queryClient.invalidateQueries({
      queryKey: ["admin", "recovery-conflict"],
    });
  };

  const refreshMut = useMutation({
    mutationFn: (id: number) => adminApi.refreshRecoveryConflict(id),
    onSuccess: async () => {
      messageApi.success("외부 주문 상태를 갱신했습니다.");
      await invalidate();
    },
    onError: (e) => messageApi.error(toApiError(e).message),
  });

  const approveMut = useMutation({
    mutationFn: (id: number) =>
      adminApi.approveImportRecoveryConflict(id, {
        note: noteForm.getFieldValue("note"),
      }),
    onSuccess: async () => {
      messageApi.success("내부 주문·체결 기록을 가져왔습니다.");
      // Drawer destroyOnHidden — 닫기 전 미연결 reset 호출 금지
      setDetailId(null);
      await invalidate();
    },
    onError: (e) => messageApi.error(toApiError(e).message),
  });

  const ignoreMut = useMutation({
    mutationFn: ({ id, note }: { id: number; note: string }) =>
      adminApi.ignoreRecoveryConflict(id, { note }),
    onSuccess: async () => {
      messageApi.success("무시 처리했습니다. (계좌 Pause는 자동 해제되지 않음)");
      setDetailId(null);
      await invalidate();
    },
    onError: (e) => messageApi.error(toApiError(e).message),
  });

  const preserveMut = useMutation({
    mutationFn: ({ id, note }: { id: number; note: string }) =>
      adminApi.preserveHistoryRecoveryConflict(id, { note }),
    onSuccess: async () => {
      messageApi.success(
        "History Preserve 처리했습니다. (Import/Ignore 아님 · Pause 유지)",
      );
      setDetailId(null);
      await invalidate();
    },
    onError: (e) => messageApi.error(toApiError(e).message),
  });

  const holdMut = useMutation({
    mutationFn: ({ id, note }: { id: number; note: string }) =>
      adminApi.holdRecoveryConflict(id, { note }),
    onSuccess: async () => {
      messageApi.success("보류 처리했습니다.");
      noteForm.resetFields(); // Drawer 열린 상태 — Form 연결됨
      await invalidate();
    },
    onError: (e) => messageApi.error(toApiError(e).message),
  });

  const resumeMut = useMutation({
    mutationFn: ({
      ubaId,
      reason,
      correlationId,
    }: {
      ubaId: number;
      reason: string;
      correlationId: string;
    }) =>
      adminApi.resumeRecoveryAccount(ubaId, {
        reason,
        correlation_id: correlationId,
      }),
    onSuccess: async () => {
      messageApi.success("계좌 거래를 재개했습니다.");
      await invalidate();
    },
    onError: (e) => messageApi.error(toApiError(e).message),
  });

  const rows = extractRows(listQuery.data) as unknown as RecoveryConflictItem[];
  const detail = asRecord(
    detailQuery.data,
  ) as unknown as RecoveryConflictItem | null;
  const busy =
    refreshMut.isPending ||
    approveMut.isPending ||
    ignoreMut.isPending ||
    preserveMut.isPending ||
    holdMut.isPending ||
    resumeMut.isPending;

  const confirmApprove = (id: number) => {
    modalApi.confirm({
      title: "내부 기록으로 가져오기",
      content: (
        <Typography.Paragraph>
          이 주문은 업비트에 이미 존재하는 주문입니다. 승인 시 새로운 주문을
          전송하지 않고 내부 주문·체결 기록만 생성합니다.
        </Typography.Paragraph>
      ),
      okText: "내부 기록으로 가져오기",
      cancelText: "취소",
      onOk: () => approveMut.mutateAsync(id),
    });
  };

  const askNote = (
    title: string,
    onOk: (note: string) => Promise<unknown>,
  ) => {
    let note = "";
    modalApi.confirm({
      title,
      content: (
        <Input.TextArea
          rows={3}
          placeholder="사유 (필수)"
          onChange={(e) => {
            note = e.target.value;
          }}
        />
      ),
      okText: "확인",
      onOk: async () => {
        if (!note.trim()) {
          messageApi.error("사유를 입력하세요.");
          throw new Error("note required");
        }
        await onOk(note.trim());
      },
    });
  };

  return (
    <Card
      size="small"
      title="Upbit Remote-only Conflict 검토"
      extra={
        <Select
          allowClear
          placeholder="검토 상태"
          style={{ width: 180 }}
          value={statusFilter}
          onChange={(v) => setStatusFilter(v)}
          options={[
            { value: "PENDING_REVIEW", label: "Review Required" },
            { value: "ON_HOLD", label: "ON_HOLD" },
            { value: "HISTORICAL_PRESERVED", label: "History Preserved" },
            { value: "APPROVED_IMPORT", label: "APPROVED_IMPORT" },
            { value: "IGNORED", label: "IGNORED" },
            { value: "REMOTE_DISAPPEARED", label: "REMOTE_DISAPPEARED" },
          ]}
        />
      }
    >
      {contextHolder}
      {modalContextHolder}
      <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
        외부에만 존재하는 주문은 자동 Import하지 않습니다. Secret·전체 UUID는
        표시하지 않습니다.
      </Typography.Paragraph>
      <Table<RecoveryConflictItem>
        size="small"
        rowKey={(r) => String(r.conflict_id)}
        loading={listQuery.isLoading}
        dataSource={rows}
        pagination={{ pageSize: 10 }}
        onRow={(row) => ({
          onClick: () => setDetailId(row.conflict_id),
          style: { cursor: "pointer" },
        })}
        columns={[
          { title: "ID", dataIndex: "conflict_id", width: 70 },
          { title: "User", dataIndex: "user_id", width: 70 },
          {
            title: "계좌",
            dataIndex: "masked_account",
            render: (v: string | null) => v ?? "-",
          },
          { title: "Market", dataIndex: "market_code", width: 100 },
          { title: "Side", dataIndex: "side_code", width: 70 },
          {
            title: "UUID",
            dataIndex: "external_order_id_masked",
            width: 120,
          },
          {
            title: "상태",
            dataIndex: "review_status",
            render: (v: string) => (
              <Tag color={REVIEW_COLORS[v] ?? "default"}>
                {REVIEW_LABELS[v] ?? v}
              </Tag>
            ),
          },
          {
            title: "Pause",
            dataIndex: "account_paused",
            width: 70,
            render: (v: boolean) =>
              v ? <Tag color="red">ON</Tag> : <Tag>OFF</Tag>,
          },
          {
            title: "탐지",
            dataIndex: "detected_at",
            render: formatTs,
          },
        ]}
      />

      <Drawer
        title={`Conflict #${detailId ?? ""}`}
        open={detailId != null}
        size={560}
        onClose={() => setDetailId(null)}
        destroyOnHidden
        afterOpenChange={(open) => {
          if (open) {
            noteForm.resetFields();
          }
        }}
      >
        {detail ? (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="User">
                {detail.user_id ?? "-"}
              </Descriptions.Item>
              <Descriptions.Item label="계좌">
                {detail.masked_account ?? "-"}
              </Descriptions.Item>
              <Descriptions.Item label="Broker">
                {detail.broker_code}
              </Descriptions.Item>
              <Descriptions.Item label="UUID(마스킹)">
                {detail.external_order_id_masked}
              </Descriptions.Item>
              <Descriptions.Item label="Market">
                {detail.market_code ?? "-"}
              </Descriptions.Item>
              <Descriptions.Item label="Side / Type">
                {detail.side_code} / {detail.order_type_code}
              </Descriptions.Item>
              <Descriptions.Item label="수량">
                {detail.requested_quantity} (체결 {detail.executed_quantity} /
                잔여 {detail.remaining_quantity})
              </Descriptions.Item>
              <Descriptions.Item label="가격 / 평균 / 수수료">
                {detail.order_price} / {detail.average_execution_price} /{" "}
                {detail.paid_fee}
              </Descriptions.Item>
              <Descriptions.Item label="외부 상태">
                {detail.external_status ?? "-"}
              </Descriptions.Item>
              <Descriptions.Item label="Risk">
                {detail.risk_level}
              </Descriptions.Item>
              <Descriptions.Item label="검토">
                {REVIEW_LABELS[detail.review_status] ?? detail.review_status}
              </Descriptions.Item>
              <Descriptions.Item label="탐지">
                {formatTs(detail.detected_at)}
              </Descriptions.Item>
              <Descriptions.Item label="마지막 외부 확인">
                {formatTs(detail.last_remote_checked_at)}
              </Descriptions.Item>
              <Descriptions.Item label="Pause">
                {detail.account_paused ? "ON" : "OFF"}
              </Descriptions.Item>
            </Descriptions>

            <Form form={noteForm} layout="vertical">
              <Form.Item name="note" label="처리 메모 (선택·Ignore/Hold 시 필수)">
                <Input.TextArea rows={2} maxLength={2000} />
              </Form.Item>
            </Form>

            <Space wrap>
              <Button
                loading={refreshMut.isPending}
                disabled={busy}
                onClick={() => refreshMut.mutate(detail.conflict_id)}
              >
                최신 상태 조회
              </Button>
              <Button
                type="primary"
                disabled={busy}
                loading={approveMut.isPending}
                onClick={() => confirmApprove(detail.conflict_id)}
              >
                내부 기록으로 가져오기
              </Button>
              <Button
                type="primary"
                ghost
                disabled={busy}
                loading={preserveMut.isPending}
                onClick={() =>
                  askNote("History Preserve 사유", (note) =>
                    preserveMut.mutateAsync({
                      id: detail.conflict_id,
                      note,
                    }),
                  )
                }
              >
                History Preserve
              </Button>
              <Button
                disabled={busy}
                onClick={() =>
                  askNote("무시 사유", (note) =>
                    ignoreMut.mutateAsync({
                      id: detail.conflict_id,
                      note,
                    }),
                  )
                }
              >
                무시
              </Button>
              <Button
                disabled={busy}
                onClick={() =>
                  askNote("보류 사유", (note) =>
                    holdMut.mutateAsync({
                      id: detail.conflict_id,
                      note,
                    }),
                  )
                }
              >
                보류
              </Button>
              {detail.user_broker_account_id != null ? (
                <Button
                  danger
                  disabled={busy}
                  loading={resumeMut.isPending}
                  onClick={() =>
                    modalApi.confirm({
                      title: "계좌 거래 재개",
                      content:
                        "미해결 Conflict·Open Order·Credential·Kill Switch 조건을 통과할 때만 재개됩니다. Recovery는 Pause를 자동 해제하지 않습니다.",
                      onOk: () =>
                        resumeMut.mutateAsync({
                          ubaId: Number(detail.user_broker_account_id),
                          reason:
                            "OPERATOR_MANUAL_RESUME_FROM_ADMIN_UI",
                          correlationId: `admin-resume-${Date.now()}`,
                        }),
                    })
                  }
                >
                  계좌 거래 재개
                </Button>
              ) : null}
            </Space>
          </Space>
        ) : null}
      </Drawer>
    </Card>
  );
}
