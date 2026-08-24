"use client";

/**
 * 업비트 자동매매용 연구 데이터 요약 — 상세는 전략·분석 → 연구 데이터.
 */

import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Progress, Space, Tag, Typography } from "antd";
import Link from "next/link";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { withMarketQuery } from "@/features/admin/strategy-analysis/marketScope";
import { asRecord, cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

function statusColor(status: unknown): string {
  const s = String(status ?? "");
  if (s === "OK" || s === "COLLECTING") return "success";
  if (s === "WAITING") return "processing";
  if (s === "PARTIAL" || s === "STALE") return "warning";
  if (s === "ERROR" || s === "DISABLED") return "error";
  return "default";
}

export function UpbitResearchCollectionSummaryCard({
  ubaId,
}: {
  ubaId: number;
}) {
  const q = useQuery({
    queryKey: queryKeys.admin.upbitResearchCollectionStatus(ubaId),
    queryFn: () => adminApi.getAdminUbaResearchCollectionStatus(ubaId),
    enabled: ubaId > 0,
    refetchInterval: 60_000,
  });

  const data = asRecord(q.data) ?? {};
  const clean = asRecord(data.clean_forward) ?? {};
  const cleanCount = Number(clean.count ?? 0);
  const target500 = Number(clean.target_primary ?? 500);
  const pct = Math.min(
    100,
    target500 ? (cleanCount / target500) * 100 : 0,
  );
  const overallKo = String(data.overall_status_ko ?? data.overall_status ?? "—");
  const detailHref = withMarketQuery(adminRoutes.researchData, "UPBIT");

  return (
    <Card
      size="small"
      title="연구 데이터"
      extra={
        <Link href={detailHref}>
          <Button size="small" type="link">
            전략·분석에서 자세히 보기
          </Button>
        </Link>
      }
      loading={q.isLoading}
    >
      {q.error ? (
        <Alert
          type="error"
          showIcon
          title={toApiError(q.error).message}
          description="연구 현황을 불러오지 못했습니다."
        />
      ) : (
        <Space orientation="vertical" size={6} style={{ width: "100%" }}>
          <Space wrap>
            <Typography.Text>
              정상 신규 검증 {cleanCount} / {target500.toLocaleString()}
            </Typography.Text>
            <Tag color={statusColor(data.overall_status)}>● {overallKo}</Tag>
          </Space>
          <Progress percent={Number(pct.toFixed(1))} size="small" />
          <Typography.Text type="secondary">
            수집·CLEAN·시장/뉴스/AI 분석은 전략·분석 → 연구 데이터에서 관리합니다.
            {" · "}
            오늘 +{cell(clean.today_new ?? 0)}
          </Typography.Text>
        </Space>
      )}
    </Card>
  );
}
