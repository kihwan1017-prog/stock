"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Space, Typography } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminUpbitMarketsPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();

  const markets = useQuery({
    queryKey: queryKeys.admin.upbitMarkets(),
    queryFn: adminApi.getUpbitMarkets,
  });

  const syncInstruments = useMutation({
    mutationFn: adminApi.syncUpbitInstruments,
    onSuccess: () => {
      message.success("업비트 종목 동기화 요청 완료");
      void qc.invalidateQueries({ queryKey: queryKeys.admin.upbitMarkets() });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const rows = extractRows(markets.data).length
    ? extractRows(markets.data)
    : Array.isArray(markets.data)
      ? (markets.data as Record<string, unknown>[])
      : [];

  return (
    <AdminPageShell
      title="업비트 시세"
      description="마켓 목록 · 종목(Instrument) 동기화 — 계좌/잔고는 업비트 계좌 메뉴"
      extra={
        <Space wrap>
          <Button
            type="primary"
            loading={syncInstruments.isPending}
            onClick={() => syncInstruments.mutate()}
          >
            종목 동기화
          </Button>
          <Button
            onClick={() => void markets.refetch()}
            loading={markets.isFetching}
          >
            마켓 새로고침
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          GET /upbit/markets 로 업비트 KRW 마켓 목록을 조회합니다. Instrument
          동기화는 DB 종목 마스터를 갱신합니다.
        </Typography.Paragraph>

        <AdminDataTable
          title="GET /upbit/markets"
          loading={markets.isLoading}
          error={markets.error ? toApiError(markets.error) : null}
          rowKey={(r) => cell(r.market ?? r.symbol ?? JSON.stringify(r))}
          columns={[
            { title: "market", dataIndex: "market", sorter: true },
            { title: "korean_name", dataIndex: "korean_name" },
            { title: "english_name", dataIndex: "english_name" },
          ]}
          dataSource={rows}
        />

        <AdminJsonCard
          title="마켓 원본 응답"
          loading={markets.isLoading}
          error={markets.error ? toApiError(markets.error) : null}
          data={markets.data}
        />
      </Space>
    </AdminPageShell>
  );
}
