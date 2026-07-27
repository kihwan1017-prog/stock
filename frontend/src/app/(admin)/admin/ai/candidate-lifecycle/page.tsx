"use client";

/**
 * STEP 11-13 — Candidate Lifecycle (Provenance & Reference Management).
 * Promotion으로 등록된 CandidateResult 참조·검증·만료·철회.
 * 매매·전략·주문 승인 아님 — soft status 전이만.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Input,
  InputNumber,
  Space,
  Table,
  Tabs,
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
  "Candidate Lifecycle은 Promotion Gateway를 통해 등록된 CandidateResult(result_id)에 대한 " +
  "내부 참조·검증·만료·철회 관리이며, 자동 매매·전략 배포·주문 승인을 의미하지 않습니다.";

export default function AdminAiCandidateLifecyclePage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [expectedVersion, setExpectedVersion] = useState<number>(0);
  const [replacementId, setReplacementId] = useState<number | null>(null);
  const [selectedRevocationId, setSelectedRevocationId] = useState<number | null>(
    null,
  );

  const listQuery = useQuery({
    queryKey: queryKeys.admin.aiCandidateLifecycle(),
    queryFn: () => adminApi.listAiCandidateLifecycles(),
  });
  const items = extractRows(asRecord(listQuery.data)?.items);

  const dashQuery = useQuery({
    queryKey: ["admin", "ai-candidate-lifecycle-dashboard"],
    queryFn: adminApi.getAiCandidateLifecycleDashboard,
  });
  const dash = asRecord(dashQuery.data) ?? {};

  const detailQuery = useQuery({
    queryKey: ["admin", "ai-candidate-lifecycle", selectedId],
    queryFn: () => adminApi.getAiCandidateLifecycle(selectedId!),
    enabled: selectedId != null,
  });
  const lifecycle = asRecord(asRecord(detailQuery.data)?.lifecycle) ?? {};

  const provenanceQuery = useQuery({
    queryKey: ["admin", "ai-candidate-lifecycle-provenance", selectedId],
    queryFn: () => adminApi.getAiCandidateLifecycleProvenance(selectedId!),
    enabled: selectedId != null,
  });

  const historyQuery = useQuery({
    queryKey: ["admin", "ai-candidate-lifecycle-history", selectedId],
    queryFn: () => adminApi.getAiCandidateLifecycleHistory(selectedId!),
    enabled: selectedId != null,
  });
  const historyItems = extractRows(asRecord(historyQuery.data)?.items);

  const revalidationsQuery = useQuery({
    queryKey: ["admin", "ai-candidate-lifecycle-revalidations", selectedId],
    queryFn: () => adminApi.getAiCandidateLifecycleRevalidations(selectedId!),
    enabled: selectedId != null,
  });
  const revalidationItems = extractRows(asRecord(revalidationsQuery.data)?.items);

  const revocationsQuery = useQuery({
    queryKey: ["admin", "ai-candidate-lifecycle-revocations", selectedId],
    queryFn: () => adminApi.getAiCandidateLifecycleRevocations(selectedId!),
    enabled: selectedId != null,
  });
  const revocationItems = extractRows(asRecord(revocationsQuery.data)?.items);

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.admin.aiCandidateLifecycle(),
    });
    queryClient.invalidateQueries({
      queryKey: ["admin", "ai-candidate-lifecycle-dashboard"],
    });
    if (selectedId != null) {
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-candidate-lifecycle", selectedId],
      });
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-candidate-lifecycle-provenance", selectedId],
      });
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-candidate-lifecycle-history", selectedId],
      });
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-candidate-lifecycle-revalidations", selectedId],
      });
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-candidate-lifecycle-revocations", selectedId],
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
      message.error("Candidate 선택 필요");
      return false;
    }
    return true;
  };

  const mutationBody = () => ({
    reason,
    expected_version: expectedVersion,
  });

  const activateMut = useMutation({
    mutationFn: () =>
      adminApi.activateReviewAiCandidateLifecycle(selectedId!, mutationBody()),
    onSuccess: () => {
      message.success("ACTIVE_REVIEW 전이");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const validateMut = useMutation({
    mutationFn: () =>
      adminApi.validateAiCandidateLifecycle(selectedId!, mutationBody()),
    onSuccess: () => {
      message.success("Validate 완료 (fingerprint only)");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const revalidateMut = useMutation({
    mutationFn: () =>
      adminApi.revalidateAiCandidateLifecycle(selectedId!, mutationBody()),
    onSuccess: () => {
      message.success("Revalidate 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const expireMut = useMutation({
    mutationFn: () =>
      adminApi.expireAiCandidateLifecycle(selectedId!, mutationBody()),
    onSuccess: () => {
      message.success("Expire (soft status)");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const archiveMut = useMutation({
    mutationFn: () =>
      adminApi.archiveAiCandidateLifecycle(selectedId!, mutationBody()),
    onSuccess: () => {
      message.success("Archive 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const requestRevocationMut = useMutation({
    mutationFn: () =>
      adminApi.requestRevocationAiCandidateLifecycle(selectedId!, mutationBody()),
    onSuccess: () => {
      message.success("Revocation 요청");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const supersedeMut = useMutation({
    mutationFn: () =>
      adminApi.supersedeAiCandidateLifecycle(selectedId!, {
        ...mutationBody(),
        replacement_candidate_id: replacementId,
      }),
    onSuccess: () => {
      message.success("Supersede 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const approveRevocationMut = useMutation({
    mutationFn: () =>
      adminApi.approveRevocationAiCandidateLifecycle(
        selectedId!,
        selectedRevocationId!,
        mutationBody(),
      ),
    onSuccess: () => {
      message.success("Revocation 승인 (soft revoke)");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  return (
    <AdminPageShell title="Candidate Lifecycle">
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <Alert type="warning" showIcon title={REFERENCE_DISCLAIMER} />

        <Space wrap>
          <Tag>Total: {cell(dash.total)}</Tag>
          <Tag color="green">Healthy: {cell(dash.healthy)}</Tag>
          <Tag color="orange">Warning: {cell(dash.warning)}</Tag>
          <Tag>Revalidation: {cell(dash.revalidation_required)}</Tag>
          <Tag>Expiring ≤24h: {cell(dash.expiring_soon)}</Tag>
          <Tag>Expired: {cell(dash.expired)}</Tag>
          <Tag>Revoked: {cell(dash.revoked)}</Tag>
          <Tag>Source Changed: {cell(dash.source_changed)}</Tag>
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
            <Input style={{ width: 120 }} value="expected_version" disabled />
            <InputNumber
              min={0}
              value={expectedVersion}
              onChange={(v) => setExpectedVersion(typeof v === "number" ? v : 0)}
            />
          </Space.Compact>
          <Typography.Link href={adminRoutes.aiCandidatePromotions}>
            Promotion Gateway
          </Typography.Link>
        </Space>

        <Table
          size="small"
          loading={listQuery.isLoading}
          dataSource={items}
          rowKey={(r) => String(asRecord(r)?.candidate_id)}
          pagination={{ pageSize: 10 }}
          onRow={(r) => ({
            onClick: () => {
              const id = asRecord(r)?.candidate_id;
              if (typeof id === "number") {
                setSelectedId(id);
                const ver = asRecord(r)?.lifecycle_version;
                if (typeof ver === "number") setExpectedVersion(ver);
              }
            },
          })}
          columns={[
            { title: "Candidate ID", dataIndex: "candidate_id", width: 110, render: cell },
            { title: "Lifecycle", dataIndex: "lifecycle_status", width: 140, render: cell },
            { title: "Health", dataIndex: "health_status", width: 120, render: cell },
            { title: "Version", dataIndex: "lifecycle_version", width: 80, render: cell },
            { title: "Promotion", dataIndex: "promotion_request_id", width: 90, render: cell },
            { title: "Queue", dataIndex: "queue_id", width: 80, render: cell },
            {
              title: "Reval?",
              dataIndex: "revalidation_required",
              width: 70,
              render: (v) => (v ? "Y" : "N"),
            },
          ]}
        />

        {selectedId != null && (
          <Space orientation="vertical" style={{ width: "100%" }} size="small">
            <Typography.Title level={5}>
              Candidate #{selectedId} / {cell(lifecycle.lifecycle_status)} / v
              {cell(lifecycle.lifecycle_version)}
            </Typography.Title>

            <Space wrap>
              <Button
                onClick={() => {
                  if (!requireReason() || !requireSelected()) return;
                  activateMut.mutate();
                }}
              >
                Activate Review
              </Button>
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
                  revalidateMut.mutate();
                }}
              >
                Revalidate
              </Button>
              <Button
                danger
                onClick={() => {
                  if (!requireReason() || !requireSelected()) return;
                  expireMut.mutate();
                }}
              >
                Expire
              </Button>
              <Button
                onClick={() => {
                  if (!requireReason() || !requireSelected()) return;
                  archiveMut.mutate();
                }}
              >
                Archive
              </Button>
              <Button
                onClick={() => {
                  if (!requireReason() || !requireSelected()) return;
                  requestRevocationMut.mutate();
                }}
              >
                Request Revocation
              </Button>
            </Space>

            <Space wrap>
              <Space.Compact>
                <Input style={{ width: 140 }} value="replacement_id" disabled />
                <InputNumber
                  min={1}
                  value={replacementId ?? undefined}
                  onChange={(v) =>
                    setReplacementId(typeof v === "number" ? v : null)
                  }
                />
              </Space.Compact>
              <Button
                onClick={() => {
                  if (
                    !requireReason() ||
                    !requireSelected() ||
                    replacementId == null
                  ) {
                    message.error("replacement_candidate_id 필요");
                    return;
                  }
                  supersedeMut.mutate();
                }}
              >
                Supersede
              </Button>
              <InputNumber
                placeholder="revocation_id"
                value={selectedRevocationId ?? undefined}
                onChange={(v) =>
                  setSelectedRevocationId(typeof v === "number" ? v : null)
                }
              />
              <Button
                danger
                onClick={() => {
                  if (
                    !requireReason() ||
                    !requireSelected() ||
                    selectedRevocationId == null
                  ) {
                    message.error("revocation_id 필요");
                    return;
                  }
                  approveRevocationMut.mutate();
                }}
              >
                Approve Revocation
              </Button>
            </Space>

            <Tabs
              items={[
                {
                  key: "provenance",
                  label: "Provenance",
                  children: (
                    <pre style={{ maxHeight: 280, overflow: "auto" }}>
                      {JSON.stringify(provenanceQuery.data, null, 2)}
                    </pre>
                  ),
                },
                {
                  key: "history",
                  label: "History",
                  children: (
                    <Table
                      size="small"
                      dataSource={historyItems}
                      rowKey={(r) =>
                        String(
                          asRecord(r)?.history_id ??
                            `${asRecord(r)?.action}-${asRecord(r)?.created_at}`,
                        )
                      }
                      pagination={false}
                      columns={[
                        { title: "Action", dataIndex: "action", render: cell },
                        { title: "From", dataIndex: "previous_lifecycle_status", render: cell },
                        { title: "To", dataIndex: "new_lifecycle_status", render: cell },
                        { title: "By", dataIndex: "requested_by", render: cell },
                        { title: "At", dataIndex: "created_at", render: cell },
                      ]}
                    />
                  ),
                },
                {
                  key: "revalidations",
                  label: "Revalidations",
                  children: (
                    <Table
                      size="small"
                      dataSource={revalidationItems}
                      rowKey={(r) => String(asRecord(r)?.revalidation_id)}
                      pagination={false}
                      columns={[
                        { title: "Status", dataIndex: "revalidation_status", render: cell },
                        { title: "Match", dataIndex: "fingerprint_match", render: cell },
                        { title: "At", dataIndex: "completed_at", render: cell },
                      ]}
                    />
                  ),
                },
                {
                  key: "revocations",
                  label: "Revocations",
                  children: (
                    <Table
                      size="small"
                      dataSource={revocationItems}
                      rowKey={(r) => String(asRecord(r)?.revocation_id)}
                      pagination={false}
                      onRow={(r) => ({
                        onClick: () => {
                          const id = asRecord(r)?.revocation_id;
                          if (typeof id === "number") setSelectedRevocationId(id);
                        },
                      })}
                      columns={[
                        { title: "ID", dataIndex: "revocation_id", width: 70, render: cell },
                        { title: "Status", dataIndex: "revocation_status", render: cell },
                        { title: "Reason", dataIndex: "reason", render: cell },
                        { title: "At", dataIndex: "requested_at", render: cell },
                      ]}
                    />
                  ),
                },
              ]}
            />
          </Space>
        )}
      </Space>
    </AdminPageShell>
  );
}
