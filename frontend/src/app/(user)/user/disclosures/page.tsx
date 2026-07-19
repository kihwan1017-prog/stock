"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useMemo, useState } from "react";

import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { pickFocusSymbol } from "@/features/user/dashboard/pickFocusSymbol";
import { useMyPaperAccountId } from "@/features/user/hooks/useMyPaperAccountId";
import { pickInterestSymbols } from "@/features/user/news/pickInterestSymbols";
import * as userApi from "@/features/user/api/userApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";

const DEFAULT_EXCHANGE = "KRX";

function tableRowKey(row: Record<string, unknown>, fields: string[]): string {
  for (const field of fields) {
    const value = row[field];
    if (value !== null && value !== undefined && value !== "") {
      return String(value);
    }
  }
  try {
    return JSON.stringify(row);
  } catch {
    return "unknown-row";
  }
}

type DisclosureFormValues = {
  stock_code: string;
  range: [dayjs.Dayjs, dayjs.Dayjs];
};

type ManualFilter = {
  stockCode: string;
  start: string;
  end: string;
};

export default function UserDisclosuresPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { accountId } = useMyPaperAccountId();
  const [form] = Form.useForm<DisclosureFormValues>();

  const defaultRange = useMemo(
    () => ({
      start: dayjs().subtract(30, "day").format("YYYY-MM-DD"),
      end: dayjs().format("YYYY-MM-DD"),
    }),
    [],
  );

  // null이면 AI/보유 기반 autoFocus + 기본 기간
  const [manualFilter, setManualFilter] = useState<ManualFilter | null>(null);
  const [interestSymbol, setInterestSymbol] = useState<string | null>(null);

  const positionsQuery = useQuery({
    queryKey: queryKeys.user.paperPositions(accountId ?? 0),
    queryFn: () => userApi.getPaperPositions(accountId as number),
    enabled: accountId != null,
  });

  const aiQuery = useQuery({
    queryKey: queryKeys.user.topCandidates(DEFAULT_EXCHANGE),
    queryFn: () => userApi.getTopCandidates(DEFAULT_EXCHANGE),
  });

  const positionRows = useMemo(() => {
    const fromExtract = extractRows(positionsQuery.data);
    if (fromExtract.length) return fromExtract;
    if (Array.isArray(positionsQuery.data)) {
      return positionsQuery.data as Record<string, unknown>[];
    }
    return [];
  }, [positionsQuery.data]);

  const aiRows = useMemo(
    () => extractRows(aiQuery.data).slice(0, 8),
    [aiQuery.data],
  );

  const autoFocus = useMemo(
    () => pickFocusSymbol(aiRows, positionRows),
    [aiRows, positionRows],
  );

  const stockCode = manualFilter?.stockCode ?? autoFocus;
  const dateRange = manualFilter
    ? { start: manualFilter.start, end: manualFilter.end }
    : defaultRange;
  const rangeKey = `${dateRange.start}_${dateRange.end}`;

  const interestSymbols = useMemo(
    () => pickInterestSymbols(positionRows, 5),
    [positionRows],
  );

  const activeInterest =
    interestSymbol && interestSymbols.includes(interestSymbol)
      ? interestSymbol
      : (interestSymbols[0] ?? null);

  const listQuery = useQuery({
    queryKey: queryKeys.user.dartDisclosures(stockCode, rangeKey),
    queryFn: () =>
      userApi.listDartDisclosures({
        stock_code: stockCode,
        start_date: dateRange.start,
        end_date: dateRange.end,
        limit: 50,
      }),
  });

  const interestDisclosureQueries = useQueries({
    queries: interestSymbols.map((sym) => ({
      queryKey: queryKeys.user.dartDisclosures(sym, rangeKey),
      queryFn: () =>
        userApi.listDartDisclosures({
          stock_code: sym,
          start_date: dateRange.start,
          end_date: dateRange.end,
          limit: 20,
        }),
      enabled: interestSymbols.length > 0,
    })),
  });

  const syncDisclosures = useMutation({
    mutationFn: (body: {
      stock_code: string;
      start_date: string;
      end_date: string;
    }) => userApi.syncDartDisclosures(body),
    onSuccess: async (_data, variables) => {
      message.success("공시 동기화 요청 완료");
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.dartDisclosures(variables.stock_code),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const applyFilter = (values: DisclosureFormValues) => {
    const code = values.stock_code.trim().toUpperCase();
    const start = values.range[0].format("YYYY-MM-DD");
    const end = values.range[1].format("YYYY-MM-DD");
    setManualFilter({ stockCode: code, start, end });
    return { stock_code: code, start_date: start, end_date: end };
  };

  const rows = extractRows(listQuery.data);
  const meta = asRecord(listQuery.data);

  const sortedRows = useMemo(
    () =>
      [...rows].sort((a, b) =>
        String(b.receipt_date ?? "").localeCompare(String(a.receipt_date ?? "")),
      ),
    [rows],
  );

  const interestMergedRows = useMemo(() => {
    const merged: Record<string, unknown>[] = [];
    interestSymbols.forEach((sym, index) => {
      const result = interestDisclosureQueries[index];
      for (const row of extractRows(result?.data)) {
        merged.push({ ...row, _interest_symbol: sym });
      }
    });
    return merged.sort((a, b) =>
      String(b.receipt_date ?? "").localeCompare(String(a.receipt_date ?? "")),
    );
  }, [interestSymbols, interestDisclosureQueries]);

  const filteredInterestRows = activeInterest
    ? interestMergedRows.filter(
        (row) => String(row._interest_symbol) === activeInterest,
      )
    : interestMergedRows;

  const interestLoading = interestDisclosureQueries.some((q) => q.isLoading);
  const interestError = interestDisclosureQueries.find((q) => q.error)?.error;

  const disclosureColumns = [
    {
      title: "보고서",
      dataIndex: "report_name",
      ellipsis: true,
      render: cell,
    },
    {
      title: "법인",
      dataIndex: "corp_name",
      width: 140,
      ellipsis: true,
      render: cell,
    },
    {
      title: "중요도",
      dataIndex: "importance_score",
      width: 80,
      render: cell,
    },
    {
      title: "접수일",
      dataIndex: "receipt_date",
      width: 110,
      render: cell,
    },
    {
      title: "접수번호",
      dataIndex: "receipt_no",
      width: 140,
      render: cell,
    },
  ];

  return (
    <UserPageShell
      title="공시"
      description="최신 공시 · 관심(보유) 종목 · AI 요약"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card size="small" title="조회 조건 · 최신 공시">
          <Form
            key={
              manualFilter
                ? `manual-${manualFilter.stockCode}-${manualFilter.start}`
                : `auto-${autoFocus}`
            }
            form={form}
            layout="inline"
            initialValues={{
              stock_code: stockCode,
              range: [
                dayjs(dateRange.start),
                dayjs(dateRange.end),
              ] as [dayjs.Dayjs, dayjs.Dayjs],
            }}
            onFinish={(values) => {
              applyFilter(values);
            }}
          >
            <Form.Item
              name="stock_code"
              label="종목코드"
              rules={[{ required: true }]}
            >
              <Input style={{ width: 120 }} />
            </Form.Item>
            <Form.Item name="range" label="기간" rules={[{ required: true }]}>
              <DatePicker.RangePicker />
            </Form.Item>
            <Button type="primary" htmlType="submit">
              조회
            </Button>
            <Button
              loading={syncDisclosures.isPending}
              onClick={async () => {
                try {
                  const values = await form.validateFields();
                  const filtered = applyFilter(values);
                  syncDisclosures.mutate(filtered);
                } catch {
                  // Form 검증 실패
                }
              }}
            >
              동기화
            </Button>
          </Form>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            포커스 기본값: {autoFocus} · GET /dart/disclosures · POST /dart/sync
          </Typography.Text>
        </Card>

        {listQuery.error ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(listQuery.error).message}
          />
        ) : null}

        <Card
          title={`최신 공시 · ${stockCode}`}
          size="small"
          loading={listQuery.isLoading}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {dateRange.start} ~ {dateRange.end} · limit{" "}
              {cell(meta?.limit ?? 50)} ·{" "}
              <Tag color="blue">종목 단위 API</Tag>
            </Typography.Text>
          }
        >
          <Table
            size="small"
            pagination={{ pageSize: 12 }}
            rowKey={(row) =>
              tableRowKey(row, [
                "disclosure_id",
                "receipt_no",
                "report_name",
              ])
            }
            dataSource={sortedRows}
            locale={{ emptyText: "공시 없음 — 동기화 후 다시 조회하세요" }}
            columns={disclosureColumns}
            expandable={{
              expandedRowRender: (row) => (
                <Space orientation="vertical" size={2}>
                  <Typography.Text style={{ fontSize: 12 }}>
                    filer: {cell(row.filer_name)} · category:{" "}
                    {cell(row.category_code)}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    remark: {cell(row.remark)}
                  </Typography.Text>
                </Space>
              ),
            }}
          />
        </Card>

        <Card size="small" title="관심종목 공시">
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            {/* TODO: GET /api/v1/user/watchlist */}
            <UnimplementedNotice
              feature="관심종목 공시"
              reason="Backend 관심종목(watchlist) API가 없습니다. 보유 종목 공시로 대체 표시합니다."
              relatedApis={[
                "GET /dart/disclosures",
                "GET /paper-accounts/{id}/positions",
              ]}
            />

            {interestSymbols.length === 0 ? (
              <Alert
                type="info"
                showIcon
                title="보유 종목 없음"
                description="Paper 포지션이 있으면 종목별 공시를 여기에 모읍니다."
              />
            ) : (
              <>
                <Space wrap>
                  <Typography.Text type="secondary">보유 종목:</Typography.Text>
                  <Select
                    style={{ minWidth: 160 }}
                    value={activeInterest ?? undefined}
                    options={interestSymbols.map((sym) => ({
                      value: sym,
                      label: sym,
                    }))}
                    onChange={(value) => setInterestSymbol(value)}
                  />
                  <Button
                    size="small"
                    loading={syncDisclosures.isPending}
                    disabled={!activeInterest}
                    onClick={() => {
                      if (!activeInterest) return;
                      syncDisclosures.mutate({
                        stock_code: activeInterest,
                        start_date: dateRange.start,
                        end_date: dateRange.end,
                      });
                    }}
                  >
                    선택 종목 동기화
                  </Button>
                </Space>

                {interestError ? (
                  <Alert
                    type="error"
                    showIcon
                    title={toApiError(interestError).message}
                  />
                ) : null}

                <Table
                  size="small"
                  loading={interestLoading}
                  pagination={{ pageSize: 8 }}
                  rowKey={(row) =>
                    `${String(row._interest_symbol)}-${tableRowKey(row, [
                      "disclosure_id",
                      "receipt_no",
                      "report_name",
                    ])}`
                  }
                  dataSource={filteredInterestRows}
                  locale={{ emptyText: "해당 보유 종목 공시 없음" }}
                  columns={[
                    {
                      title: "종목",
                      dataIndex: "_interest_symbol",
                      width: 90,
                      render: cell,
                    },
                    ...disclosureColumns,
                  ]}
                />
              </>
            )}
          </Space>
        </Card>

        <Card size="small" title="AI 요약">
          {/* TODO: POST /api/v1/dart/summarize */}
          <UnimplementedNotice
            feature="공시 AI 요약"
            reason="Backend에 공시 AI 요약 API(POST /dart/summarize)가 없습니다. 뉴스 요약(POST /news/summarize)만 사용 가능합니다."
            relatedApis={["GET /dart/disclosures", "POST /dart/sync"]}
          />
        </Card>
      </Space>
    </UserPageShell>
  );
}
