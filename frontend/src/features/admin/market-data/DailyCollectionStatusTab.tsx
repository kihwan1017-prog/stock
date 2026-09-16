"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  DatePicker,
  Descriptions,
  Drawer,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";

import * as adminApi from "@/features/admin/api/adminApi";
import { cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type Row = {
  trade_date: string;
  market: string;
  expected_symbols: number;
  collected_symbols: number;
  missing_symbols: number;
  collection_rate: number;
  last_run_at: string | null;
  status: string;
  status_label: string;
  is_trading_day: boolean;
};

const YEAR_OPTIONS = [2024, 2025, 2026];

export function DailyCollectionStatusTab() {
  const [market, setMarket] = useState<"ALL" | "UPBIT" | "KIWOOM">("ALL");
  const [periodDays, setPeriodDays] = useState(30);
  const [year, setYear] = useState<number | null>(null);
  const [customRange, setCustomRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [drawerRow, setDrawerRow] = useState<Row | null>(null);

  const range = useMemo(() => {
    if (year) {
      return { from: `${year}-01-01`, to: `${year}-12-31` };
    }
    if (customRange) {
      return {
        from: customRange[0].format("YYYY-MM-DD"),
        to: customRange[1].format("YYYY-MM-DD"),
      };
    }
    const to = dayjs();
    return {
      from: to.subtract(periodDays, "day").format("YYYY-MM-DD"),
      to: to.format("YYYY-MM-DD"),
    };
  }, [year, customRange, periodDays]);

  const listQ = useQuery({
    queryKey: queryKeys.admin.marketDataDailyStatus({
      market,
      ...range,
      status: statusFilter,
    }),
    queryFn: () =>
      adminApi.getMarketDataDailyStatus({
        market: market === "ALL" ? undefined : market,
        from: range.from,
        to: range.to,
        status: statusFilter === "ALL" ? undefined : statusFilter,
      }),
  });

  const missingQ = useQuery({
    queryKey: queryKeys.admin.marketDataDailyMissing(
      drawerRow?.market ?? "",
      drawerRow?.trade_date ?? "",
    ),
    queryFn: () =>
      adminApi.getMarketDataDailyMissing({
        market: drawerRow!.market,
        trade_date: drawerRow!.trade_date,
        limit: 100,
      }),
    enabled: Boolean(drawerRow),
  });

  const rows = ((listQ.data as { items?: Row[] } | undefined)?.items ??
    []) as Row[];

  const columns: ColumnsType<Row> = [
    { title: "일자", dataIndex: "trade_date", width: 120 },
    { title: "시장", dataIndex: "market", width: 90 },
    { title: "예상 종목수", dataIndex: "expected_symbols", width: 110 },
    { title: "수집 종목수", dataIndex: "collected_symbols", width: 110 },
    { title: "누락 종목수", dataIndex: "missing_symbols", width: 110 },
    {
      title: "수집률",
      dataIndex: "collection_rate",
      width: 90,
      render: (v: number) => `${v}%`,
    },
    {
      title: "최종 실행",
      dataIndex: "last_run_at",
      width: 100,
      render: (v) => cell(v) || "—",
    },
    {
      title: "상태",
      dataIndex: "status_label",
      render: (v) => <Tag>{v}</Tag>,
    },
  ];

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Space wrap>
        <Segmented
          value={market}
          onChange={(v) => setMarket(v as typeof market)}
          options={[
            { label: "전체", value: "ALL" },
            { label: "UPBIT", value: "UPBIT" },
            { label: "KIWOOM", value: "KIWOOM" },
          ]}
        />
        {[
          { label: "7일", days: 7 },
          { label: "30일", days: 30 },
          { label: "3개월", days: 90 },
          { label: "1년", days: 365 },
        ].map((p) => (
          <Tag.CheckableTag
            key={p.label}
            checked={!year && !customRange && periodDays === p.days}
            onChange={() => {
              setYear(null);
              setCustomRange(null);
              setPeriodDays(p.days);
            }}
          >
            {p.label}
          </Tag.CheckableTag>
        ))}
        {YEAR_OPTIONS.map((y) => (
          <Tag.CheckableTag
            key={y}
            checked={year === y}
            onChange={() => {
              setYear(y);
              setCustomRange(null);
            }}
          >
            {y}
          </Tag.CheckableTag>
        ))}
        <DatePicker.RangePicker
          onChange={(vals) => {
            if (vals?.[0] && vals[1]) {
              setCustomRange([vals[0], vals[1]]);
              setYear(null);
            } else {
              setCustomRange(null);
            }
          }}
        />
        <Select
          style={{ width: 140 }}
          value={statusFilter}
          onChange={setStatusFilter}
          options={[
            { value: "ALL", label: "전체 상태" },
            { value: "HEALTHY", label: "정상" },
            { value: "PARTIAL", label: "누락" },
            { value: "FAILED", label: "실패" },
            { value: "CLOSED", label: "휴장" },
          ]}
        />
      </Space>

      <Table
        size="small"
        rowKey={(r) => `${r.market}-${r.trade_date}`}
        loading={listQ.isLoading}
        columns={columns}
        dataSource={rows}
        pagination={{ pageSize: 20 }}
        onRow={(record) => ({
          onClick: () => setDrawerRow(record),
          style: { cursor: "pointer" },
        })}
      />
      {listQ.error ? (
        <Typography.Text type="danger">
          {toApiError(listQ.error).message}
        </Typography.Text>
      ) : null}

      <Drawer
        title={
          drawerRow
            ? `${drawerRow.market} ${drawerRow.trade_date} 누락 상세`
            : "누락 상세"
        }
        open={drawerRow != null}
        onClose={() => setDrawerRow(null)}
        size={480}
      >
        {drawerRow ? (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="상태">
                {drawerRow.status_label}
              </Descriptions.Item>
              <Descriptions.Item label="수집률">
                {drawerRow.collection_rate}%
              </Descriptions.Item>
              <Descriptions.Item label="누락">
                {drawerRow.missing_symbols}
              </Descriptions.Item>
            </Descriptions>
            {missingQ.isLoading ? (
              <Typography.Text>불러오는 중…</Typography.Text>
            ) : (
              <>
                <Typography.Text type="secondary">
                  {(missingQ.data as { message?: string } | undefined)?.message}
                </Typography.Text>
                <Table
                  size="small"
                  pagination={false}
                  rowKey={(r) => String((r as { symbol: string }).symbol)}
                  dataSource={
                    ((missingQ.data as { items?: unknown[] })?.items ??
                      []) as Record<string, unknown>[]
                  }
                  columns={[
                    { title: "종목", dataIndex: "symbol" },
                    { title: "이름", dataIndex: "name" },
                  ]}
                />
                <Descriptions size="small" column={1} bordered title="수집 Job">
                  <Descriptions.Item label="job">
                    {cell(
                      (
                        (missingQ.data as { last_job?: Record<string, unknown> })
                          ?.last_job ?? {}
                      ).job_run_id,
                    )}
                  </Descriptions.Item>
                  <Descriptions.Item label="status">
                    {cell(
                      (
                        (missingQ.data as { last_job?: Record<string, unknown> })
                          ?.last_job ?? {}
                      ).status_code,
                    )}
                  </Descriptions.Item>
                  <Descriptions.Item label="error">
                    {cell(
                      (
                        (missingQ.data as { last_job?: Record<string, unknown> })
                          ?.last_job ?? {}
                      ).error_message,
                    ) || "—"}
                  </Descriptions.Item>
                </Descriptions>
              </>
            )}
          </Space>
        ) : null}
      </Drawer>
    </Space>
  );
}
