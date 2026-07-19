"use client";

import { useQuery } from "@tanstack/react-query";
import { Button, InputNumber, Space } from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminPortfolioPage() {
  const [accountId, setAccountId] = useState(1);

  const summary = useQuery({
    queryKey: queryKeys.admin.portfolioSummary(accountId),
    queryFn: () => adminApi.getPortfolioSummary(accountId),
  });
  const paper = useQuery({
    queryKey: queryKeys.admin.paperPositions(accountId),
    queryFn: () => adminApi.getPaperPositions(accountId),
  });

  return (
    <AdminPageShell
      title="포트폴리오"
      description="Paper 계좌·포지션 (STEP56: step32 API 제거)"
      extra={
        <Space>
          <InputNumber
            min={1}
            value={accountId}
            onChange={(v) => setAccountId(Number(v) || 1)}
          />
          <Button onClick={() => void summary.refetch()}>조회</Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <AdminJsonCard
          title={`Paper summary account_id=${accountId}`}
          loading={summary.isLoading}
          error={summary.error ? toApiError(summary.error) : null}
          data={summary.data}
        />
        <AdminDataTable
          title={`GET /paper-accounts/${accountId}/positions`}
          loading={paper.isLoading}
          error={paper.error ? toApiError(paper.error) : null}
          rowKey={(r) => cell(r.symbol ?? JSON.stringify(r))}
          columns={[
            { title: "symbol", dataIndex: "symbol" },
            { title: "quantity", dataIndex: "quantity" },
            { title: "avg", dataIndex: "average_entry_price" },
          ]}
          dataSource={extractRows(paper.data)}
        />
      </Space>
    </AdminPageShell>
  );
}
