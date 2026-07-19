"use client";

import { useQuery } from "@tanstack/react-query";
import { Space } from "antd";

import { PageContainer } from "@/components/common/PageContainer";
import { JsonPanel } from "@/features/user/components/JsonPanel";
import * as userApi from "@/features/user/api/userApi";
import { queryKeys } from "@/lib/query/queryKeys";
import { toApiError } from "@/lib/api/apiError";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";

export default function UserPortfolioPage() {
  const summary = useQuery({
    queryKey: queryKeys.user.portfolioSummary(),
    queryFn: userApi.getPortfolioSummary,
  });
  const positions = useQuery({
    queryKey: queryKeys.user.positions(),
    queryFn: userApi.listPositions,
  });

  return (
    <PageContainer title="포트폴리오" description="portfolio/summary · positions API">
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <UnimplementedNotice
          feature="DB 기반 실계좌 포트폴리오 집계"
          reason="GET /portfolio/summary 와 /positions 는 step32 인메모리 성격일 수 있습니다. 사용자별 영속 포트폴리오 API는 별도로 없습니다."
          relatedApis={["GET /api/v1/portfolio/summary", "GET /api/v1/positions"]}
        />
        <JsonPanel
          title="GET /api/v1/portfolio/summary"
          loading={summary.isLoading}
          error={summary.error ? toApiError(summary.error) : null}
          data={summary.data}
        />
        <JsonPanel
          title="GET /api/v1/positions"
          loading={positions.isLoading}
          error={positions.error ? toApiError(positions.error) : null}
          data={positions.data}
        />
      </Space>
    </PageContainer>
  );
}
