"use client";

import { useQuery } from "@tanstack/react-query";
import { Space } from "antd";

import { PageContainer } from "@/components/common/PageContainer";
import { JsonPanel } from "@/features/user/components/JsonPanel";
import * as userApi from "@/features/user/api/userApi";
import { queryKeys } from "@/lib/query/queryKeys";
import { toApiError } from "@/lib/api/apiError";

export default function UserStrategiesPage() {
  const active = useQuery({
    queryKey: queryKeys.user.activeDeployment(),
    queryFn: userApi.getActiveStrategyDeployment,
  });
  const ranking = useQuery({
    queryKey: queryKeys.user.strategyRanking(),
    queryFn: userApi.getStrategyRanking,
  });
  const selection = useQuery({
    queryKey: queryKeys.user.strategySelection(),
    queryFn: userApi.getLatestStrategySelection,
  });

  return (
    <PageContainer title="전략" description="strategy-deployments / ranking / selector API">
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <JsonPanel
          title="GET /api/v1/strategy-deployments/active"
          loading={active.isLoading}
          error={active.error ? toApiError(active.error) : null}
          data={active.data}
        />
        <JsonPanel
          title="GET /api/v1/strategy-ranking"
          loading={ranking.isLoading}
          error={ranking.error ? toApiError(ranking.error) : null}
          data={ranking.data}
        />
        <JsonPanel
          title="GET /api/v1/strategy-selector/latest"
          loading={selection.isLoading}
          error={selection.error ? toApiError(selection.error) : null}
          data={selection.data}
        />
      </Space>
    </PageContainer>
  );
}
