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
import { SETTLEMENT_STATUS_COLOR } from "@/features/admin/settlement/settlementStatusColors";
import { cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

export { SETTLEMENT_STATUS_COLOR };

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

/** STEP 8-5-16 — EOD Account Settlement Admin 패널 */
export function AccountSettlementsPanel() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [detailId, setDetailId] = useState<number | null>(null);
  const { prompt, modal } = useReasonPrompt();

  const listQuery = useQuery({
    queryKey: ["admin", "settlements", statusFilter],
    queryFn: () =>
      adminApi.listAdminSettlements({
        status_code: statusFilter,
        limit: 100,
      }),
    refetchInterval: 30_000,
  });

  const healthQuery = useQuery({
    queryKey: ["admin", "settlements", "health"],
    queryFn: () => adminApi.getAdminSettlementHealth(),
    refetchInterval: 30_000,
  });

  const detailQuery = useQuery({
    queryKey: ["admin", "settlements", detailId],
    queryFn: () => adminApi.getAdminSettlement(detailId!),
    enabled: detailId != null,
  });

  const issuesQuery = useQuery({
    queryKey: ["admin", "settlements", detailId, "issues"],
    queryFn: () => adminApi.listAdminSettlementIssues(detailId!),
    enabled: detailId != null,
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["admin", "settlements"] });
  };

  const retryMut = useMutation({
    mutationFn: (vars: { id: number; reason: string }) =>
      adminApi.retryAdminSettlement(vars.id, vars.reason),
    onSuccess: invalidate,
  });
  const reconcileMut = useMutation({
    mutationFn: (vars: { id: number; reason: string }) =>
      adminApi.reconcileAdminSettlement(vars.id, vars.reason),
    onSuccess: invalidate,
  });

  const health = healthQuery.data;
  const items = listQuery.data?.items ?? [];

  return (
    <Card
      title="Account Daily Settlement (STEP 8-5-16)"
      size="small"
      extra={
        <Select
          allowClear
          placeholder="상태 필터"
          style={{ width: 220 }}
          value={statusFilter}
          onChange={(v) => setStatusFilter(v)}
          options={Object.keys(SETTLEMENT_STATUS_COLOR).map((s) => ({
            value: s,
            label: s,
          }))}
        />
      }
    >
      {modal}
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
          <Descriptions.Item label="대상">
            {cell(health.total)}
          </Descriptions.Item>
          <Descriptions.Item label="성공">
            {cell(health.succeeded)}
          </Descriptions.Item>
          <Descriptions.Item label="Manual">
            {cell(health.manual_review)}
          </Descriptions.Item>
          <Descriptions.Item label="실패">
            {cell(health.failed)}
          </Descriptions.Item>
          <Descriptions.Item label="Position Mismatch">
            {cell(health.position_mismatch_total)}
          </Descriptions.Item>
          <Descriptions.Item label="Cash Mismatch">
            {cell(health.cash_mismatch_count)}
          </Descriptions.Item>
          <Descriptions.Item label="Ambiguous">
            {cell(health.unresolved_ambiguous_total)}
          </Descriptions.Item>
          <Descriptions.Item label="최근 성공">
            {cell(health.last_success_at)}
          </Descriptions.Item>
        </Descriptions>
      ) : null}

      {listQuery.error ? (
        <Alert type="error" showIcon title={toApiError(listQuery.error).message} />
      ) : (
        <Table
          size="small"
          loading={listQuery.isLoading}
          rowKey={(r) => String(r.settlement_id)}
          dataSource={items}
          pagination={{ pageSize: 10 }}
          onRow={(row) => ({
            onClick: () => setDetailId(Number(row.settlement_id)),
          })}
          columns={[
            { title: "번호", dataIndex: "settlement_id", width: 70 },
            { title: "날짜", dataIndex: "market_date", width: 110 },
            { title: "거래소/증권사", dataIndex: "broker_code", width: 90 },
            {
              title: "상태",
              dataIndex: "status_code",
              render: (v: string) => (
                <Tag color={SETTLEMENT_STATUS_COLOR[v] ?? "default"}>{v}</Tag>
              ),
            },
            { title: "내부 자산", dataIndex: "internal_equity" },
            { title: "외부 자산", dataIndex: "external_equity" },
            { title: "차이", dataIndex: "equity_difference" },
            { title: "순손익", dataIndex: "net_pnl" },
            {
              title: "이슈",
              key: "issues",
              render: (_: unknown, row) =>
                Number(row.position_mismatch_count ?? 0) +
                Number(row.unresolved_order_count ?? 0),
            },
            {
              title: "작업",
              key: "actions",
              render: (_: unknown, row) => (
                <Space>
                  <Button
                    size="small"
                    onClick={(e) => {
                      e.stopPropagation();
                      prompt((reason) =>
                        retryMut.mutate({
                          id: Number(row.settlement_id),
                          reason,
                        }),
                      );
                    }}
                  >
                    Retry
                  </Button>
                  <Button
                    size="small"
                    onClick={(e) => {
                      e.stopPropagation();
                      prompt((reason) =>
                        reconcileMut.mutate({
                          id: Number(row.settlement_id),
                          reason,
                        }),
                      );
                    }}
                  >
                    Reconcile
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      )}

      {detailId != null ? (
        <Card
          size="small"
          title={`Settlement #${detailId}`}
          style={{ marginTop: 12 }}
          extra={
            <Button size="small" onClick={() => setDetailId(null)}>
              닫기
            </Button>
          }
        >
          {detailQuery.data ? (
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="상태">
                {detailQuery.data.status_code}
              </Descriptions.Item>
              <Descriptions.Item label="요약">
                {cell(detailQuery.data.result_summary)}
              </Descriptions.Item>
              <Descriptions.Item label="실현손익">
                {cell(detailQuery.data.realized_pnl)}
              </Descriptions.Item>
              <Descriptions.Item label="미실현">
                {cell(detailQuery.data.unrealized_pnl)}
              </Descriptions.Item>
              <Descriptions.Item label="수수료">
                {cell(detailQuery.data.fees)}
              </Descriptions.Item>
              <Descriptions.Item label="세금">
                {cell(detailQuery.data.taxes)}
              </Descriptions.Item>
            </Descriptions>
          ) : null}
          <Typography.Title level={5} style={{ marginTop: 12 }}>
            이슈
          </Typography.Title>
          <Table
            size="small"
            loading={issuesQuery.isLoading}
            rowKey={(r) => String(r.issue_id)}
            dataSource={issuesQuery.data?.items ?? []}
            pagination={false}
            columns={[
              { title: "유형", dataIndex: "issue_type" },
              { title: "심각도", dataIndex: "severity" },
              { title: "종목", dataIndex: "symbol" },
              { title: "내부 값", dataIndex: "local_value" },
              { title: "외부 값", dataIndex: "external_value" },
              { title: "차이", dataIndex: "difference" },
              {
                title: "해결",
                dataIndex: "resolved",
                render: (v: boolean) => (v ? "예" : "아니오"),
              },
            ]}
          />
        </Card>
      ) : null}
    </Card>
  );
}
