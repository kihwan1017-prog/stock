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

export default function AdminTradesPage() {
  const [limit, setLimit] = useState(50);

  const executions = useQuery({
    queryKey: queryKeys.admin.executions({ limit }),
    queryFn: () => adminApi.listExecutions({ limit }),
  });
  const paperOrders = useQuery({
    queryKey: queryKeys.admin.paperOrders(),
    queryFn: () => adminApi.listPaperOrders({ limit: 100 }),
  });

  const execRows = useMemo(() => extractRows(executions.data), [executions.data]);
  const paperRows = useMemo(() => extractRows(paperOrders.data), [paperOrders.data]);

  return (
    <AdminPageShell title="거래내역" description="executions · paper-orders">
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Form layout="inline" onFinish={(v: { limit: number }) => setLimit(v.limit)}>
          <Form.Item name="limit" initialValue={50} label="limit">
            <InputNumber min={1} max={500} />
          </Form.Item>
          <Button htmlType="submit">필터</Button>
        </Form>

        <AdminDataTable
          title="GET /executions"
          loading={executions.isLoading}
          error={executions.error ? toApiError(executions.error) : null}
          rowKey={(r) => cell(r.execution_id ?? r.id ?? JSON.stringify(r))}
          columns={[
            { title: "execution_id", dataIndex: "execution_id", sorter: true },
            { title: "order_id", dataIndex: "order_id" },
            { title: "symbol", dataIndex: "symbol", sorter: true },
            { title: "qty", dataIndex: "quantity" },
            { title: "price", dataIndex: "price" },
            { title: "executed_at", dataIndex: "executed_at" },
          ]}
          dataSource={execRows}
        />

        <AdminDataTable
          title="GET /paper-orders"
          loading={paperOrders.isLoading}
          error={paperOrders.error ? toApiError(paperOrders.error) : null}
          rowKey={(r) => cell(r.paper_order_id ?? r.id ?? JSON.stringify(r))}
          columns={[
            { title: "id", dataIndex: "paper_order_id" },
            { title: "symbol", dataIndex: "symbol" },
            { title: "side", dataIndex: "side" },
            { title: "status", dataIndex: "status" },
            { title: "qty", dataIndex: "quantity" },
          ]}
          dataSource={paperRows}
        />

        <AdminJsonCard
          title="executions 원본"
          loading={executions.isLoading}
          error={executions.error ? toApiError(executions.error) : null}
          data={executions.data}
        />
      </Space>
    </AdminPageShell>
  );
}
