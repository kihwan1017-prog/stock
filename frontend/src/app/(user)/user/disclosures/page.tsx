"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  DatePicker,
  Drawer,
  Empty,
  Input,
  List,
  Select,
  Skeleton,
  Space,
  Tag,
  Typography,
} from "antd";
import {
  BookFilled,
  BookOutlined,
  LinkOutlined,
  ReloadOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import Link from "next/link";
import { useMemo, useState } from "react";

import { userRoutes } from "@/config/routes";
import type {
  DisclosureAiSummary,
  UserDisclosureFilter,
  UserDisclosureItem,
} from "@/features/user/api/userApi";
import * as userApi from "@/features/user/api/userApi";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type DateRange = [Dayjs | null, Dayjs | null] | null;

function formatSubmittedAt(value: string | null): string {
  if (!value) return "접수일 없음";
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format("YYYY-MM-DD") : value;
}

function SummaryBlock({ summary }: { summary: DisclosureAiSummary }) {
  if (summary.status === "PROCESSING" || summary.status === "QUEUED") {
    return <Alert type="info" showIcon message="AI 요약을 생성 중입니다…" />;
  }
  if (summary.status === "FAILED") {
    return (
      <Alert
        type="error"
        showIcon
        message="AI 요약 생성에 실패했습니다."
        description="잠시 후 다시 시도해 주세요."
      />
    );
  }
  if (summary.status !== "COMPLETED" && summary.status !== "STALE") {
    return (
      <Typography.Text type="secondary">
        아직 생성된 AI 요약이 없습니다.
      </Typography.Text>
    );
  }
  return (
    <Space direction="vertical" style={{ width: "100%" }} size={8}>
      {summary.is_stale && (
        <Alert type="warning" showIcon message="요약이 오래되었을 수 있습니다." />
      )}
      <Typography.Paragraph>{summary.summary}</Typography.Paragraph>
      {!!summary.key_points?.length && (
        <>
          <Typography.Text strong>주요 내용</Typography.Text>
          <List
            size="small"
            dataSource={summary.key_points}
            renderItem={(item) => <List.Item>{item}</List.Item>}
          />
        </>
      )}
      {!!summary.risk_factors?.length && (
        <>
          <Typography.Text strong>위험 요인</Typography.Text>
          <List
            size="small"
            dataSource={summary.risk_factors}
            renderItem={(item) => <List.Item>{item}</List.Item>}
          />
        </>
      )}
      {!!summary.financial_impacts?.length && (
        <>
          <Typography.Text strong>재무 영향</Typography.Text>
          <List
            size="small"
            dataSource={summary.financial_impacts}
            renderItem={(item) => <List.Item>{item}</List.Item>}
          />
        </>
      )}
      {!!summary.important_numbers?.length && (
        <>
          <Typography.Text strong>주요 수치</Typography.Text>
          <List
            size="small"
            dataSource={summary.important_numbers}
            renderItem={(item) => <List.Item>{item}</List.Item>}
          />
        </>
      )}
      {!!summary.uncertainty_notes?.length && (
        <>
          <Typography.Text strong>불확실성</Typography.Text>
          <List
            size="small"
            dataSource={summary.uncertainty_notes}
            renderItem={(item) => <List.Item>{item}</List.Item>}
          />
        </>
      )}
      <Alert
        type="warning"
        showIcon
        message={
          summary.disclaimer ||
          "AI가 생성한 요약으로 오류나 누락이 있을 수 있습니다. 중요한 판단은 공시 원문을 확인하세요."
        }
      />
    </Space>
  );
}

export default function UserDisclosuresPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [marketCode, setMarketCode] = useState<string | undefined>();
  const [symbol, setSymbol] = useState<string | undefined>();
  const [disclosureType, setDisclosureType] = useState<string | undefined>();
  const [readStatus, setReadStatus] = useState<"" | "read" | "unread">("");
  const [bookmarkedOnly, setBookmarkedOnly] = useState(false);
  const [hasAiSummary, setHasAiSummary] = useState<boolean | undefined>();
  const [keyword, setKeyword] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [dateRange, setDateRange] = useState<DateRange>(null);
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const pageSize = 20;

  const watchlistQuery = useQuery({
    queryKey: queryKeys.user.watchlist(),
    queryFn: () => userApi.listWatchlist(),
  });

  const disclosureEnabledItems = useMemo(
    () =>
      (watchlistQuery.data?.items ?? []).filter(
        (item) =>
          item.disclosure_enabled &&
          ["KRX", "KOSPI", "KOSDAQ"].includes(item.market.toUpperCase()),
      ),
    [watchlistQuery.data?.items],
  );

  const listParams: UserDisclosureFilter = useMemo(
    () => ({
      market_code: marketCode,
      symbol,
      disclosure_type: disclosureType,
      keyword: keyword || undefined,
      from_date: dateRange?.[0]
        ? dateRange[0].format("YYYY-MM-DD")
        : undefined,
      to_date: dateRange?.[1]
        ? dateRange[1].format("YYYY-MM-DD")
        : undefined,
      read_status: readStatus || undefined,
      bookmarked: bookmarkedOnly ? true : undefined,
      has_ai_summary: hasAiSummary,
      page,
      page_size: pageSize,
    }),
    [
      marketCode,
      symbol,
      disclosureType,
      keyword,
      dateRange,
      readStatus,
      bookmarkedOnly,
      hasAiSummary,
      page,
    ],
  );

  const listQuery = useQuery({
    queryKey: queryKeys.user.userDisclosures.list(listParams),
    queryFn: () => userApi.listUserDisclosures(listParams),
  });

  const unreadQuery = useQuery({
    queryKey: queryKeys.user.userDisclosures.unreadCount(),
    queryFn: () => userApi.getUnreadDisclosureCount(),
  });

  const aiStatusQuery = useQuery({
    queryKey: queryKeys.user.userAiStatus(),
    queryFn: () => userApi.getUserAiStatus(),
  });

  const detailQuery = useQuery({
    queryKey: queryKeys.user.userDisclosures.detail(selectedId ?? 0),
    queryFn: () => userApi.getUserDisclosureDetail(selectedId as number),
    enabled: selectedId != null,
  });

  const summaryQuery = useQuery({
    queryKey: queryKeys.user.userDisclosures.aiSummary(selectedId ?? 0),
    queryFn: () => userApi.getDisclosureAiSummary(selectedId as number),
    enabled: selectedId != null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "PROCESSING" || status === "QUEUED") return 3000;
      return false;
    },
  });

  const invalidateList = async (disclosureId?: number) => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.user.userDisclosures.list(listParams),
    });
    await queryClient.invalidateQueries({
      queryKey: queryKeys.user.userDisclosures.unreadCount(),
    });
    if (disclosureId != null) {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.userDisclosures.detail(disclosureId),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.userDisclosures.aiSummary(disclosureId),
      });
    }
  };

  const readMutation = useMutation({
    mutationFn: async ({
      id,
      read,
    }: {
      id: number;
      read: boolean;
    }) =>
      read
        ? userApi.markUserDisclosureRead(id)
        : userApi.unmarkUserDisclosureRead(id),
    onSuccess: async (_data, variables) => {
      await invalidateList(variables.id);
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const bookmarkMutation = useMutation({
    mutationFn: async ({
      id,
      bookmarked,
    }: {
      id: number;
      bookmarked: boolean;
    }) =>
      bookmarked
        ? userApi.bookmarkUserDisclosure(id)
        : userApi.unbookmarkUserDisclosure(id),
    onSuccess: async (_data, variables) => {
      await invalidateList(variables.id);
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const readAllMutation = useMutation({
    mutationFn: () =>
      userApi.readAllUserDisclosures({
        market_code: marketCode,
        symbol,
      }),
    onSuccess: async (result) => {
      message.success(`읽음 처리 ${result.updated_count}건`);
      await invalidateList();
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const summarizeMutation = useMutation({
    mutationFn: (id: number) => userApi.requestDisclosureAiSummary(id),
    onSuccess: async (_data, id) => {
      message.success("AI 요약 요청 완료");
      await invalidateList(id);
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const regenerateMutation = useMutation({
    mutationFn: (id: number) => userApi.regenerateDisclosureAiSummary(id),
    onSuccess: async (_data, id) => {
      message.success("AI 요약 재생성 요청 완료");
      await invalidateList(id);
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const openDetail = (item: UserDisclosureItem) => {
    setSelectedId(item.disclosure_id);
    if (!item.is_read) {
      readMutation.mutate({ id: item.disclosure_id, read: true });
    }
  };

  const watchlistEmpty =
    !watchlistQuery.isLoading &&
    (watchlistQuery.data?.items.length ?? 0) === 0;

  const items = listQuery.data?.items ?? [];
  const totalCount = listQuery.data?.total_count ?? 0;
  const hasNext = listQuery.data?.has_next ?? false;

  const symbolOptions = useMemo(() => {
    const filtered = marketCode
      ? disclosureEnabledItems.filter(
          (item) => item.market.toUpperCase() === marketCode.toUpperCase(),
        )
      : disclosureEnabledItems;
    return filtered.map((item) => ({
      value: item.symbol,
      label: `${item.symbol} ${item.symbol_name}`,
    }));
  }, [disclosureEnabledItems, marketCode]);

  const marketOptions = useMemo(() => {
    const markets = Array.from(
      new Set(
        disclosureEnabledItems.map((item) => item.market.toUpperCase()),
      ),
    );
    return markets.map((m) => ({ value: m, label: m }));
  }, [disclosureEnabledItems]);

  const activeSummary =
    summaryQuery.data ?? detailQuery.data?.ai_summary ?? null;

  return (
    <UserPageShell
      title="관심종목 공시"
      description="내 관심종목(KRX)과 연결된 DART 공시를 조회하고 AI 요약을 요청합니다."
      extra={
        <Space wrap>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              void listQuery.refetch();
              void unreadQuery.refetch();
            }}
          >
            새로고침
          </Button>
          <Button
            onClick={() => readAllMutation.mutate()}
            loading={readAllMutation.isPending}
            disabled={watchlistEmpty}
          >
            전체 읽음
          </Button>
          <Button
            type={bookmarkedOnly ? "primary" : "default"}
            onClick={() => {
              setBookmarkedOnly((prev) => !prev);
              setPage(1);
            }}
          >
            북마크만 보기
          </Button>
          {unreadQuery.data != null && (
            <Tag color="blue">미읽음 {unreadQuery.data.unread_count}</Tag>
          )}
        </Space>
      }
    >
      {aiStatusQuery.data && !aiStatusQuery.data.disclosure_summary_available && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="현재 AI 요약 서비스를 사용할 수 없습니다."
          description="공시 목록·원문 조회는 가능합니다."
        />
      )}

      {watchlistEmpty ? (
        <Empty
          description="관심종목을 먼저 등록해 주세요."
          style={{ marginTop: 48 }}
        >
          <Link href={userRoutes.watchlist}>
            <Button type="primary">관심종목으로 이동</Button>
          </Link>
        </Empty>
      ) : (
        <>
          <Card size="small" style={{ marginBottom: 16 }}>
            <Space wrap>
              <Select
                allowClear
                placeholder="시장"
                style={{ width: 120 }}
                options={marketOptions}
                value={marketCode}
                onChange={(value) => {
                  setMarketCode(value);
                  setSymbol(undefined);
                  setPage(1);
                }}
              />
              <Select
                allowClear
                showSearch
                placeholder="관심종목"
                style={{ width: 220 }}
                options={symbolOptions}
                value={symbol}
                onChange={(value) => {
                  setSymbol(value);
                  setPage(1);
                }}
                filterOption={(input, option) =>
                  String(option?.label ?? "")
                    .toLowerCase()
                    .includes(input.toLowerCase())
                }
              />
              <Select
                allowClear
                placeholder="공시 유형"
                style={{ width: 160 }}
                value={disclosureType}
                options={[
                  { value: "MAJOR_EVENT", label: "주요사항" },
                  { value: "FINANCIAL", label: "실적/재무" },
                  { value: "OTHER", label: "기타" },
                ]}
                onChange={(value) => {
                  setDisclosureType(value);
                  setPage(1);
                }}
              />
              <Select
                allowClear
                placeholder="읽음 상태"
                style={{ width: 140 }}
                value={readStatus || undefined}
                options={[
                  { value: "unread", label: "미읽음" },
                  { value: "read", label: "읽음" },
                ]}
                onChange={(value) => {
                  setReadStatus((value as "" | "read" | "unread") || "");
                  setPage(1);
                }}
              />
              <Select
                allowClear
                placeholder="AI 요약"
                style={{ width: 140 }}
                value={
                  hasAiSummary === undefined
                    ? undefined
                    : hasAiSummary
                      ? "yes"
                      : "no"
                }
                options={[
                  { value: "yes", label: "요약 있음" },
                  { value: "no", label: "요약 없음" },
                ]}
                onChange={(value) => {
                  setHasAiSummary(
                    value === "yes" ? true : value === "no" ? false : undefined,
                  );
                  setPage(1);
                }}
              />
              <DatePicker.RangePicker
                value={dateRange}
                onChange={(value) => {
                  setDateRange(value);
                  setPage(1);
                }}
              />
              <Input.Search
                allowClear
                placeholder="키워드"
                style={{ width: 220 }}
                value={keywordInput}
                onChange={(event) => setKeywordInput(event.target.value)}
                onSearch={(value) => {
                  setKeyword(value.trim());
                  setPage(1);
                }}
              />
            </Space>
          </Card>

          {listQuery.isLoading ? (
            <Skeleton active paragraph={{ rows: 8 }} />
          ) : listQuery.isError ? (
            <Alert
              type="error"
              showIcon
              message="공시를 불러오지 못했습니다."
              description={toApiError(listQuery.error).message}
            />
          ) : items.length === 0 ? (
            <Empty description="공시 데이터가 없습니다." />
          ) : (
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              {items.map((item) => (
                <Card
                  key={item.disclosure_id}
                  size="small"
                  hoverable
                  onClick={() => openDetail(item)}
                  style={{
                    opacity: item.is_read ? 0.85 : 1,
                    borderLeft: item.is_read
                      ? undefined
                      : "3px solid #1677ff",
                  }}
                  title={
                    <Space wrap>
                      <Typography.Text strong={!item.is_read}>
                        {item.report_name}
                      </Typography.Text>
                      {item.is_correction && <Tag color="orange">정정</Tag>}
                      {!item.is_read && <Tag color="blue">미읽음</Tag>}
                      <Tag>{item.disclosure_type}</Tag>
                      <Tag
                        color={
                          item.has_ai_summary
                            ? "green"
                            : item.ai_summary_status === "FAILED"
                              ? "red"
                              : "default"
                        }
                      >
                        AI {item.ai_summary_status}
                      </Tag>
                    </Space>
                  }
                  extra={
                    <Button
                      type="text"
                      icon={
                        item.is_bookmarked ? (
                          <BookFilled />
                        ) : (
                          <BookOutlined />
                        )
                      }
                      onClick={(event) => {
                        event.stopPropagation();
                        bookmarkMutation.mutate({
                          id: item.disclosure_id,
                          bookmarked: !item.is_bookmarked,
                        });
                      }}
                    />
                  }
                >
                  <Space wrap size={[8, 8]}>
                    <Tag>
                      {item.symbol} {item.symbol_name}
                    </Tag>
                    <Typography.Text type="secondary">
                      {formatSubmittedAt(item.submitted_at)}
                    </Typography.Text>
                    {item.original_url && (
                      <a
                        href={item.original_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <LinkOutlined /> 원문
                      </a>
                    )}
                  </Space>
                </Card>
              ))}
              <Space>
                <Button
                  disabled={page <= 1}
                  onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                >
                  이전
                </Button>
                <Typography.Text>
                  {page} / {Math.max(1, Math.ceil(totalCount / pageSize))}
                  페이지 (총 {totalCount}건)
                </Typography.Text>
                <Button
                  disabled={!hasNext}
                  onClick={() => setPage((prev) => prev + 1)}
                >
                  다음
                </Button>
              </Space>
            </Space>
          )}
        </>
      )}

      <Drawer
        title="공시 상세"
        width={560}
        open={selectedId != null}
        onClose={() => setSelectedId(null)}
        destroyOnClose
      >
        {detailQuery.isLoading ? (
          <Skeleton active />
        ) : detailQuery.isError ? (
          <Alert type="error" message={toApiError(detailQuery.error).message} />
        ) : detailQuery.data ? (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {detailQuery.data.report_name}
            </Typography.Title>
            <Space wrap>
              <Tag>
                {detailQuery.data.symbol} {detailQuery.data.symbol_name}
              </Tag>
              <Tag>{detailQuery.data.disclosure_type}</Tag>
              {detailQuery.data.is_correction && (
                <Tag color="orange">정정공시</Tag>
              )}
              <Typography.Text type="secondary">
                접수번호 {detailQuery.data.receipt_no}
              </Typography.Text>
            </Space>
            <Typography.Text type="secondary">
              제출 {formatSubmittedAt(detailQuery.data.submitted_at)}
            </Typography.Text>
            <Typography.Paragraph>
              {detailQuery.data.body_text || "메타데이터 없음"}
            </Typography.Paragraph>
            <Typography.Text type="secondary">
              {detailQuery.data.body_note}
            </Typography.Text>

            <Card
              size="small"
              title={
                <Space>
                  <RobotOutlined />
                  AI 요약
                </Space>
              }
              extra={
                <Space>
                  <Button
                    size="small"
                    loading={summarizeMutation.isPending}
                    disabled={
                      aiStatusQuery.data?.disclosure_summary_available === false
                    }
                    onClick={() =>
                      summarizeMutation.mutate(detailQuery.data.disclosure_id)
                    }
                  >
                    생성
                  </Button>
                  <Button
                    size="small"
                    loading={regenerateMutation.isPending}
                    disabled={
                      aiStatusQuery.data?.disclosure_summary_available === false
                    }
                    onClick={() =>
                      regenerateMutation.mutate(
                        detailQuery.data.disclosure_id,
                      )
                    }
                  >
                    재생성
                  </Button>
                </Space>
              }
            >
              {summaryQuery.isLoading && !activeSummary ? (
                <Skeleton active />
              ) : activeSummary ? (
                <SummaryBlock summary={activeSummary} />
              ) : (
                <Typography.Text type="secondary">
                  요약을 생성해 주세요.
                </Typography.Text>
              )}
            </Card>

            <Space wrap>
              {detailQuery.data.original_url && (
                <Button
                  type="primary"
                  href={detailQuery.data.original_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  icon={<LinkOutlined />}
                >
                  원문 보기
                </Button>
              )}
              <Button
                icon={
                  detailQuery.data.is_bookmarked ? (
                    <BookFilled />
                  ) : (
                    <BookOutlined />
                  )
                }
                onClick={() =>
                  bookmarkMutation.mutate({
                    id: detailQuery.data.disclosure_id,
                    bookmarked: !detailQuery.data.is_bookmarked,
                  })
                }
              >
                {detailQuery.data.is_bookmarked
                  ? "북마크 해제"
                  : "북마크"}
              </Button>
            </Space>
          </Space>
        ) : null}
      </Drawer>
    </UserPageShell>
  );
}
