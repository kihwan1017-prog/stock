"use client";

import { useQuery } from "@tanstack/react-query";
import { Space } from "antd";

import { PageContainer } from "@/components/common/PageContainer";
import { JsonPanel } from "@/features/user/components/JsonPanel";
import * as userApi from "@/features/user/api/userApi";
import { queryKeys } from "@/lib/query/queryKeys";
import { toApiError } from "@/lib/api/apiError";

export default function UserTradesPage() {
  const orders = useQuery({
    queryKey: queryKeys.user.orders(),
    queryFn: () => userApi.listOrders(),
  });
  const executions = useQuery({
    queryKey: queryKeys.user.executions(),
    queryFn: () => userApi.listExecutions(),
  });
  const paperOrders = useQuery({
    queryKey: queryKeys.user.paperOrders(),
    queryFn: userApi.listPaperOrders,
  });

  return (
    <PageContainer title="거래내역" description="orders · executions · paper-orders">
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <JsonPanel
          title="GET /api/v1/orders"
          loading={orders.isLoading}
          error={orders.error ? toApiError(orders.error) : null}
          data={orders.data}
        />
        <JsonPanel
          title="GET /api/v1/executions"
          loading={executions.isLoading}
          error={executions.error ? toApiError(executions.error) : null}
          data={executions.data}
        />
        <JsonPanel
          title="GET /api/v1/paper-orders"
          loading={paperOrders.isLoading}
          error={paperOrders.error ? toApiError(paperOrders.error) : null}
          data={paperOrders.data}
        />
      </Space>
    </PageContainer>
  );
}
