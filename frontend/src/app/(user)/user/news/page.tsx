"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
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

type FilterFormValues = {
  exchange_code: string;
  symbol: string;
  query: string;
};

type ManualFilter = {
  exchange: string;
  symbol: string;
};

export default function UserNewsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { accountId } = useMyPaperAccountId();
  const [form] = Form.useForm<FilterFormValues>();

  // null이면 AI/보유 기반 autoFocus 사용
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

  const exchange = manualFilter?.exchange ?? DEFAULT_EXCHANGE;
  const symbol = manualFilter?.symbol ?? autoFocus;

  const interestSymbols = useMemo(
    () => pickInterestSymbols(positionRows, 5),
    [positionRows],
  );

  const activeInterest =
    interestSymbol && interestSymbols.includes(interestSymbol)
      ? interestSymbol
      : (interestSymbols[0] ?? null);

  const latestNewsQuery = useQuery({
    queryKey: queryKeys.user.news(exchange, symbol),
    queryFn: () => userApi.getNewsContext(exchange, symbol, 30),
  });

  const interestNewsQueries = useQueries({
    queries: interestSymbols.map((sym) => ({
      queryKey: queryKeys.user.news(DEFAULT_EXCHANGE, sym),
      queryFn: () => userApi.getNewsContext(DEFAULT_EXCHANGE, sym, 15),
      enabled: interestSymbols.length > 0,
    })),
  });

  const syncNews = useMutation({
    mutationFn: (body: {
      exchange_code: string;
      symbol: string;
      query: string;
    }) => userApi.syncNews(body),
    onSuccess: async (_data, variables) => {
      message.success("뉴스 동기화 완료");
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.news(
          variables.exchange_code,
          variables.symbol,
        ),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const summarizeNews = useMutation({
    mutationFn: (body: { exchange_code: string; symbol: string }) =>
      userApi.summarizeNews({ ...body, limit: 20 }),
    onSuccess: async (data, variables) => {
      const saved = asRecord(data)?.saved_count;
      message.success(`뉴스 AI 요약 완료 (saved=${cell(saved)})`);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.news(
          variables.exchange_code,
          variables.symbol,
        ),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const applyFilter = (values: FilterFormValues) => {
    const nextExchange = values.exchange_code.trim().toUpperCase();
    const nextSymbol = values.symbol.trim().toUpperCase();
    setManualFilter({ exchange: nextExchange, symbol: nextSymbol });
    return {
      exchange: nextExchange,
      symbol: nextSymbol,
      query: values.query.trim() || nextSymbol,
    };
  };

  const latestRows = extractRows(latestNewsQuery.data);

  const interestMergedRows = useMemo(() => {
    const rows: Record<string, unknown>[] = [];
    interestSymbols.forEach((sym, index) => {
      const result = interestNewsQueries[index];
      for (const row of extractRows(result?.data)) {
        rows.push({ ...row, _interest_symbol: sym });
      }
    });
    return rows.sort((a, b) =>
      String(b.published_at ?? "").localeCompare(String(a.published_at ?? "")),
    );
  }, [interestSymbols, interestNewsQueries]);

  const filteredInterestRows = activeInterest
    ? interestMergedRows.filter(
        (row) => String(row._interest_symbol) === activeInterest,
      )
    : interestMergedRows;

  const interestLoading = interestNewsQueries.some((q) => q.isLoading);
  const interestError = interestNewsQueries.find((q) => q.error)?.error;

  const newsColumns = [
    {
      title: "제목",
      dataIndex: "title",
      ellipsis: true,
      render: cell,
    },
    {
      title: "요약",
      dataIndex: "summary",
      ellipsis: true,
      render: cell,
    },
    {
      title: "감성",
      dataIndex: "sentiment_score",
      width: 90,
      render: (v: unknown) =>
        v === null || v === undefined ? <Tag>미요약</Tag> : cell(v),
    },
    {
      title: "중요도",
      dataIndex: "importance_score",
      width: 80,
      render: cell,
    },
    {
      title: "게시",
      dataIndex: "published_at",
      width: 160,
      render: cell,
    },
  ];

  return (
    <UserPageShell
      title="뉴스"
      description="최신 뉴스 · 관심(보유) 종목 · AI 요약"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card size="small" title="조회 조건 · 최신 뉴스">
          <Form
            key={manualFilter ? "manual" : `auto-${autoFocus}`}
            form={form}
            layout="inline"
            initialValues={{
              exchange_code: exchange,
              symbol,
              query: symbol,
            }}
            onFinish={(values) => {
              applyFilter(values);
            }}
          >
            <Form.Item
              name="exchange_code"
              label="거래소"
              rules={[{ required: true }]}
            >
              <Input style={{ width: 100 }} />
            </Form.Item>
            <Form.Item name="symbol" label="종목" rules={[{ required: true }]}>
              <Input style={{ width: 120 }} />
            </Form.Item>
            <Form.Item name="query" label="검색어" rules={[{ required: true }]}>
              <Input style={{ width: 160 }} placeholder="네이버 검색어" />
            </Form.Item>
            <Button type="primary" htmlType="submit">
              조회
            </Button>
            <Button
              loading={syncNews.isPending}
              onClick={async () => {
                try {
                  const values = await form.validateFields();
                  const filtered = applyFilter(values);
                  syncNews.mutate({
                    exchange_code: filtered.exchange,
                    symbol: filtered.symbol,
                    query: filtered.query,
                  });
                } catch {
                  // Form 검증 실패
                }
              }}
            >
              동기화
            </Button>
            <Button
              type="primary"
              ghost
              loading={summarizeNews.isPending}
              onClick={async () => {
                try {
                  const values = await form.validateFields([
                    "exchange_code",
                    "symbol",
                  ]);
                  const filtered = applyFilter({
                    ...values,
                    query: values.query ?? values.symbol,
                  });
                  summarizeNews.mutate({
                    exchange_code: filtered.exchange,
                    symbol: filtered.symbol,
                  });
                } catch {
                  // Form 검증 실패
                }
              }}
            >
              AI 요약
            </Button>
          </Form>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            포커스 기본값: {autoFocus} (AI 1위 → 보유 → 005930) · GET
            /news/{"{ex}/{symbol}"} · POST /news/sync · POST /news/summarize
          </Typography.Text>
        </Card>

        {latestNewsQuery.error ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(latestNewsQuery.error).message}
          />
        ) : null}

        <Card
          title={`최신 뉴스 · ${exchange} ${symbol}`}
          size="small"
          loading={latestNewsQuery.isLoading}
          extra={
            <Tag color="blue">종목 단위 API (전역 피드 없음)</Tag>
          }
        >
          <Table
            size="small"
            pagination={{ pageSize: 10 }}
            rowKey={(row) =>
              tableRowKey(row, ["original_link", "title", "published_at"])
            }
            dataSource={latestRows}
            locale={{ emptyText: "뉴스 없음 — 동기화 후 다시 조회하세요" }}
            columns={newsColumns}
            expandable={{
              expandedRowRender: (row) => (
                <Space orientation="vertical" size={4}>
                  <Typography.Text style={{ fontSize: 13 }}>
                    {cell(row.summary)}
                  </Typography.Text>
                  {Array.isArray(row.risks) && row.risks.length > 0 ? (
                    <Typography.Text type="danger" style={{ fontSize: 12 }}>
                      risks: {row.risks.map(String).join(", ")}
                    </Typography.Text>
                  ) : null}
                  {row.original_link ? (
                    <Typography.Link
                      href={String(row.original_link)}
                      target="_blank"
                      rel="noreferrer"
                      style={{ fontSize: 12 }}
                    >
                      원문 보기
                    </Typography.Link>
                  ) : null}
                </Space>
              ),
            }}
          />
        </Card>

        <Card size="small" title="관심종목 뉴스">
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            {/* TODO: GET /api/v1/user/watchlist */}
            <UnimplementedNotice
              feature="관심종목 뉴스"
              reason="Backend 관심종목(watchlist) API가 없습니다. 보유 종목 뉴스로 대체 표시합니다."
              relatedApis={[
                "GET /news/{exchange}/{symbol}",
                "GET /paper-accounts/{id}/positions",
              ]}
            />

            {interestSymbols.length === 0 ? (
              <Alert
                type="info"
                showIcon
                title="보유 종목 없음"
                description="Paper 포지션이 있으면 종목별 뉴스를 여기에 모읍니다."
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
                    loading={summarizeNews.isPending}
                    disabled={!activeInterest}
                    onClick={() => {
                      if (!activeInterest) return;
                      summarizeNews.mutate({
                        exchange_code: DEFAULT_EXCHANGE,
                        symbol: activeInterest,
                      });
                    }}
                  >
                    선택 종목 AI 요약
                  </Button>
                  <Button
                    size="small"
                    loading={syncNews.isPending}
                    disabled={!activeInterest}
                    onClick={() => {
                      if (!activeInterest) return;
                      syncNews.mutate({
                        exchange_code: DEFAULT_EXCHANGE,
                        symbol: activeInterest,
                        query: activeInterest,
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
                      "original_link",
                      "title",
                      "published_at",
                    ])}`
                  }
                  dataSource={filteredInterestRows}
                  locale={{ emptyText: "해당 보유 종목 뉴스 없음" }}
                  columns={[
                    {
                      title: "종목",
                      dataIndex: "_interest_symbol",
                      width: 90,
                      render: cell,
                    },
                    ...newsColumns,
                  ]}
                />
              </>
            )}
          </Space>
        </Card>

        <Card size="small" title="AI 요약">
          <Typography.Paragraph style={{ marginBottom: 8 }}>
            상단 <Typography.Text code>AI 요약</Typography.Text> 또는 관심(보유)
            종목의 <Typography.Text code>선택 종목 AI 요약</Typography.Text>이{" "}
            <Typography.Text code>POST /news/summarize</Typography.Text>를
            호출합니다. Ollama 연결·모델 설정이 필요합니다.
          </Typography.Paragraph>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            요약 결과는 뉴스 행의 summary · sentiment_score · risks 필드에
            반영됩니다.
          </Typography.Text>
        </Card>
      </Space>
    </UserPageShell>
  );
}
