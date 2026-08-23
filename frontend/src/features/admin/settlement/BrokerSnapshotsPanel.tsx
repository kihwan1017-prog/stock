"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Input,
  InputNumber,
  Modal,
  Space,
  Table,
  Tag,
} from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { SNAPSHOT_STATUS_COLOR } from "@/features/admin/settlement/snapshotStatusColors";
import { cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

export { SNAPSHOT_STATUS_COLOR };

/** STEP 8-5-17/18 — Broker Snapshot Binding / ORPHAN 관리 */
export function BrokerSnapshotsPanel() {
  const qc = useQueryClient();
  const [ubaId, setUbaId] = useState<number | null>(null);
  const [reasonOpen, setReasonOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [pendingAction, setPendingAction] = useState<
    null | "refresh" | "release" | "verify" | "rebind" | "retire"
  >(null);
  const [verifyId, setVerifyId] = useState<number | null>(null);
  const [orphanId, setOrphanId] = useState<number | null>(null);
  const [rebindUbaId, setRebindUbaId] = useState<number | null>(null);

  const listQuery = useQuery({
    queryKey: ["admin", "broker-snapshots"],
    queryFn: () => adminApi.listAdminBrokerSnapshots({ limit: 100 }),
    refetchInterval: 30_000,
  });
  const orphanQuery = useQuery({
    queryKey: ["admin", "broker-snapshots", "orphans"],
    queryFn: () => adminApi.listAdminOrphanBrokerSnapshots({ limit: 100 }),
    refetchInterval: 30_000,
  });
  const healthQuery = useQuery({
    queryKey: ["admin", "broker-snapshots", "health"],
    queryFn: () => adminApi.getAdminBrokerSnapshotHealth(),
    refetchInterval: 30_000,
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["admin", "broker-snapshots"] });
  };

  const refreshMut = useMutation({
    mutationFn: (vars: { ubaId: number; reason: string }) =>
      adminApi.refreshAdminUbaSnapshot(vars.ubaId, vars.reason),
    onSuccess: invalidate,
  });
  const releaseMut = useMutation({
    mutationFn: (vars: { ubaId: number; reason: string }) =>
      adminApi.releaseAdminUbaStaleSnapshot(vars.ubaId, vars.reason),
    onSuccess: invalidate,
  });
  const verifyMut = useMutation({
    mutationFn: (vars: { id: number; reason: string }) =>
      adminApi.verifyAdminBrokerSnapshot(vars.id, vars.reason),
    onSuccess: invalidate,
  });
  const rebindMut = useMutation({
    mutationFn: (vars: {
      id: number;
      targetUba: number;
      reason: string;
    }) =>
      adminApi.rebindAdminOrphanBrokerSnapshot(vars.id, {
        target_user_broker_account_id: vars.targetUba,
        reason: vars.reason,
      }),
    onSuccess: invalidate,
  });
  const retireMut = useMutation({
    mutationFn: (vars: { id: number; reason: string }) =>
      adminApi.retireAdminOrphanBrokerSnapshot(vars.id, vars.reason),
    onSuccess: invalidate,
  });

  const health = healthQuery.data;
  const items = listQuery.data?.items ?? [];
  const orphans = orphanQuery.data?.items ?? [];

  const runPending = () => {
    if (reason.trim().length < 3) return;
    if (pendingAction === "refresh" && ubaId != null) {
      refreshMut.mutate({ ubaId, reason: reason.trim() });
    } else if (pendingAction === "release" && ubaId != null) {
      releaseMut.mutate({ ubaId, reason: reason.trim() });
    } else if (pendingAction === "verify" && verifyId != null) {
      verifyMut.mutate({ id: verifyId, reason: reason.trim() });
    } else if (
      pendingAction === "rebind" &&
      orphanId != null &&
      rebindUbaId != null
    ) {
      rebindMut.mutate({
        id: orphanId,
        targetUba: rebindUbaId,
        reason: reason.trim(),
      });
    } else if (pendingAction === "retire" && orphanId != null) {
      retireMut.mutate({ id: orphanId, reason: reason.trim() });
    }
    setReasonOpen(false);
  };

  return (
    <Card title="Broker Snapshot Binding (STEP 8-5-18)" size="small">
      <Modal
        title="사유 입력"
        open={reasonOpen}
        onCancel={() => setReasonOpen(false)}
        onOk={runPending}
        okText="확인"
      >
        {pendingAction === "rebind" ? (
          <InputNumber
            style={{ width: "100%", marginBottom: 8 }}
            placeholder="Target UBA ID"
            value={rebindUbaId ?? undefined}
            onChange={(v) => setRebindUbaId(typeof v === "number" ? v : null)}
            min={1}
          />
        ) : null}
        <Input.TextArea
          rows={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="최소 3자"
        />
      </Modal>

      {healthQuery.error ? (
        <Alert
          type="error"
          showIcon
          title={toApiError(healthQuery.error).message}
          style={{ marginBottom: 12 }}
        />
      ) : null}
      {health ? (
        <Descriptions size="small" column={4} style={{ marginBottom: 12 }}>
          <Descriptions.Item label="Active">
            {cell(health.active_count)}
          </Descriptions.Item>
          <Descriptions.Item label="Orphan">
            {cell(health.orphan_count)}
          </Descriptions.Item>
          <Descriptions.Item label="Retired">
            {cell(health.retired_count)}
          </Descriptions.Item>
          <Descriptions.Item label="Stale(Active)">
            {cell(health.stale_active_count)}
          </Descriptions.Item>
        </Descriptions>
      ) : null}

      <Space style={{ marginBottom: 12 }}>
        <InputNumber
          placeholder="UBA ID"
          value={ubaId ?? undefined}
          onChange={(v) => setUbaId(typeof v === "number" ? v : null)}
          min={1}
        />
        <Button
          disabled={ubaId == null}
          onClick={() => {
            setPendingAction("refresh");
            setReason("");
            setReasonOpen(true);
          }}
        >
          Refresh Snapshot
        </Button>
        <Button
          disabled={ubaId == null}
          onClick={() => {
            setPendingAction("release");
            setReason("");
            setReasonOpen(true);
          }}
        >
          Release Stale
        </Button>
      </Space>

      <Card
        type="inner"
        title="고아(ORPHAN) 대기열"
        size="small"
        style={{ marginBottom: 12 }}
      >
        <Table
          size="small"
          loading={orphanQuery.isLoading}
          rowKey={(r) => String(r.broker_account_snapshot_id)}
          dataSource={orphans}
          pagination={false}
          columns={[
            { title: "번호", dataIndex: "broker_account_snapshot_id", width: 70 },
            { title: "거래소/증권사", dataIndex: "broker_code", width: 90 },
            {
              title: "계좌(마스킹)",
              dataIndex: "masked_account_number",
              ellipsis: true,
            },
            {
              title: "상태",
              dataIndex: "snapshot_status",
              render: (v: string) => (
                <Tag color={SNAPSHOT_STATUS_COLOR[v] ?? "default"}>{v}</Tag>
              ),
            },
            { title: "경과(초)", dataIndex: "age_seconds", width: 80 },
            {
              title: "작업",
              key: "actions",
              render: (_: unknown, row) => (
                <Space>
                  <Button
                    size="small"
                    onClick={() => {
                      setOrphanId(Number(row.broker_account_snapshot_id));
                      setRebindUbaId(null);
                      setPendingAction("rebind");
                      setReason("");
                      setReasonOpen(true);
                    }}
                  >
                    Rebind
                  </Button>
                  <Button
                    size="small"
                    danger
                    onClick={() => {
                      setOrphanId(Number(row.broker_account_snapshot_id));
                      setPendingAction("retire");
                      setReason("");
                      setReasonOpen(true);
                    }}
                  >
                    Retire
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      {listQuery.error ? (
        <Alert type="error" showIcon title={toApiError(listQuery.error).message} />
      ) : (
        <Table
          size="small"
          loading={listQuery.isLoading}
          rowKey={(r) => String(r.broker_account_snapshot_id)}
          dataSource={items}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: "번호", dataIndex: "broker_account_snapshot_id", width: 70 },
            { title: "계좌", dataIndex: "user_broker_account_id", width: 80 },
            { title: "거래소/증권사", dataIndex: "broker_code", width: 90 },
            {
              title: "상태",
              dataIndex: "snapshot_status",
              render: (v: string) => (
                <Tag color={SNAPSHOT_STATUS_COLOR[v] ?? "default"}>{v}</Tag>
              ),
            },
            { title: "세대", dataIndex: "snapshot_generation", width: 60 },
            { title: "경과(초)", dataIndex: "age_seconds" },
            { title: "해시", dataIndex: "snapshot_hash", ellipsis: true },
            {
              title: "검증",
              key: "verify",
              render: (_: unknown, row) => (
                <Button
                  size="small"
                  disabled={row.snapshot_status !== "ACTIVE"}
                  onClick={() => {
                    setVerifyId(Number(row.broker_account_snapshot_id));
                    setPendingAction("verify");
                    setReason("");
                    setReasonOpen(true);
                  }}
                >
                  검증
                </Button>
              ),
            },
          ]}
        />
      )}
    </Card>
  );
}
