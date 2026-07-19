"use client";

import { useQuery } from "@tanstack/react-query";
import { Button, Form, InputNumber, Space } from "antd";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminBacktestsPage() {
  const [limit, setLimit] = useState(50);

  const runs = useQuery({
    queryKey: queryKeys.admin.backtestRuns({ limit }),
    queryFn: () => adminApi.listBacktestRuns({ limit }),
  });

  const rows = useMemo(() => extractRows(runs.data), [runs.data]);

  return (
    <AdminPageShell title="백테스트" description="backtest-runs 목록·필터·페이징">
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Form layout="inline" onFinish={(v: { limit: number }) => setLimit(v.limit)}>
          <Form.Item name="limit" initialValue={50} label="limit">
            <InputNumber min={1} max={200} />
          </Form.Item>
          <Button htmlType="submit">검색</Button>
          <Button onClick={() => void runs.refetch()}>새로고침</Button>
        </Form>

        <AdminDataTable
          title="GET /backtest-runs"
          loading={runs.isLoading}
          error={runs.error ? toApiError(runs.error) : null}
          rowKey={(r) => cell(r.backtest_run_id ?? r.run_id ?? JSON.stringify(r))}
          columns={[
            { title: "run_id", dataIndex: "backtest_run_id", sorter: true },
            { title: "strategy", dataIndex: "strategy_code" },
            { title: "symbol", dataIndex: "symbol" },
            { title: "exchange", dataIndex: "exchange_code" },
            { title: "created", dataIndex: "created_at" },
          ]}
          dataSource={rows}
        />

        <AdminJsonCard
          title="원본 응답"
          loading={runs.isLoading}
          error={runs.error ? toApiError(runs.error) : null}
          data={runs.data}
        />
      </Space>
    </AdminPageShell>
  );
}
