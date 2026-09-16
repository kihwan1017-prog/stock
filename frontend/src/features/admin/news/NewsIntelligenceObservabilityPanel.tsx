"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Space, Tag, Typography } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { asRecordOrEmpty, cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

/** News Intelligence Pipeline observability — REAL gate 비연동. */
export function NewsIntelligenceObservabilityPanel() {
  const { message } = App.useApp();
  const qc = useQueryClient();

  const status = useQuery({
    queryKey: queryKeys.admin.newsIntelligence(),
    queryFn: adminApi.getNewsIntelligenceStatus,
    refetchInterval: 30_000,
  });

  const runKiwoom = useMutation({
    mutationFn: () =>
      adminApi.runKiwoomNewsIntelligenceCollect({
        include_news: true,
        include_dart: true,
      }),
    onSuccess: () => {
      message.success("KIWOOM TOP10 뉴스/DART 수집 1회 완료 (SHADOW only)");
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.newsIntelligence(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  // loading/error는 아래 Tag에서 cell "-"로 표시 — empty record로 null 접근 방지
  const data = asRecordOrEmpty(status.data);
  const upbit = asRecordOrEmpty(data.upbit_collector);
  const kiwoom = asRecordOrEmpty(data.kiwoom_collector);
  const shadow = asRecordOrEmpty(data.shadow);
  const upbitShadow = asRecordOrEmpty(shadow.upbit);
  const kiwoomShadow = asRecordOrEmpty(shadow.kiwoom);
  const mapping = asRecordOrEmpty(data.symbol_mapping);
  const dynamic = asRecordOrEmpty(data.upbit_dynamic_targets);

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        News Intelligence Pipeline
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        SHADOW ONLY. UPBIT caution/news · KIWOOM news/DART는 REAL BUY / Fresh
        Golden Cross를 block/allow하지 않습니다. LAST_CHECK / LAST_SUCCESS /
        LAST_NEW_ITEM을 구분합니다.
      </Typography.Paragraph>
      <Space wrap>
        <Tag color="blue">
          UPBIT check={cell(upbit.last_check_at ?? upbit.last_run)}
        </Tag>
        <Tag color="green">
          UPBIT success={cell(upbit.last_success_at ?? upbit.last_success)}
        </Tag>
        <Tag>UPBIT new={cell(upbit.last_new_item_at ?? "-")}</Tag>
        <Tag color="blue">KIWOOM check={cell(kiwoom.last_check_at)}</Tag>
        <Tag color="green">KIWOOM success={cell(kiwoom.last_success_at)}</Tag>
        <Tag>dynamic_n={cell(dynamic.n)}</Tag>
        <Tag>map_rate={cell(mapping.mapping_rate)}</Tag>
        <Tag color="purple">
          shadow U={cell(upbitShadow.n)} / K={cell(kiwoomShadow.n)}
        </Tag>
      </Space>
      <Space wrap>
        <Button
          type="primary"
          loading={runKiwoom.isPending}
          onClick={() => runKiwoom.mutate()}
        >
          KIWOOM TOP10 수집 1회
        </Button>
        <Button onClick={() => void status.refetch()}>새로고침</Button>
      </Space>
      <AdminJsonCard
        title="News Intelligence status"
        loading={status.isLoading}
        error={status.error ? toApiError(status.error) : null}
        data={status.data}
      />
    </Space>
  );
}
