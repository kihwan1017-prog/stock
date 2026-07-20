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
  Select,
  Skeleton,
  Space,
  Tag,
  Typography,
} from "antd";
import {
  BookOutlined,
  BookFilled,
  ReloadOutlined,
  LinkOutlined,
} from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import Link from "next/link";
import { useMemo, useState } from "react";

import { UserPageShell } from "@/features/user/components/UserPageShell";
import type {
  UserNewsFilter,
  UserNewsItem,
} from "@/features/user/api/userApi";
import * as userApi from "@/features/user/api/userApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { userRoutes } from "@/config/routes";

type DateRange = [Dayjs | null, Dayjs | null] | null;

function formatPublishedAt(value: string | null): string {
  if (!value) return "발행시각 없음";
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format("YYYY-MM-DD HH:mm") : value;
}

export default function UserNewsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [marketCode, setMarketCode] = useState<string | undefined>();
  const [symbol, setSymbol] = useState<string | undefined>();
  const [readStatus, setReadStatus] = useState<"" | "read" | "unread">("");
  const [bookmarkedOnly, setBookmarkedOnly] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [dateRange, setDateRange] = useState<DateRange>(null);
  const [page, setPage] = useState(1);
  const [selectedNewsId, setSelectedNewsId] = useState<number | null>(null);

  const pageSize = 20;

  const watchlistQuery = useQuery({
    queryKey: queryKeys.user.watchlist(),
    queryFn: () => userApi.listWatchlist(),
  });

  const newsEnabledItems = useMemo(
    () =>
      (watchlistQuery.data?.items ?? []).filter((item) => item.news_enabled),
    [watchlistQuery.data?.items],
  );

  const listParams: UserNewsFilter = useMemo(
    () => ({
      market_code: marketCode,
      symbol,
      keyword: keyword || undefined,
      from_date: dateRange?.[0]
        ? dateRange[0].format("YYYY-MM-DD")
        : undefined,
      to_date: dateRange?.[1]
        ? dateRange[1].format("YYYY-MM-DD")
        : undefined,
      read_status: readStatus || undefined,
      bookmarked: bookmarkedOnly ? true : undefined,
      page,
      page_size: pageSize,
    }),
    [
      marketCode,
      symbol,
      keyword,
      dateRange,
      readStatus,
      bookmarkedOnly,
      page,
    ],
  );

  const newsQuery = useQuery({
    queryKey: queryKeys.user.userNews.list(listParams),
    queryFn: () => userApi.listUserNews(listParams),
  });

  const unreadQuery = useQuery({
    queryKey: queryKeys.user.userNews.unreadCount(),
    queryFn: () => userApi.getUnreadNewsCount(),
  });

  const detailQuery = useQuery({
    queryKey: queryKeys.user.userNews.detail(selectedNewsId ?? 0),
    queryFn: () => userApi.getUserNewsDetail(selectedNewsId as number),
    enabled: selectedNewsId != null,
  });

  const invalidateNews = async (newsId?: number) => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.user.userNews.list(listParams),
    });
    await queryClient.invalidateQueries({
      queryKey: queryKeys.user.userNews.unreadCount(),
    });
    if (newsId != null) {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.userNews.detail(newsId),
      });
    }
  };

  const readMutation = useMutation({
    mutationFn: async ({
      newsId,
      read,
    }: {
      newsId: number;
      read: boolean;
    }) =>
      read
        ? userApi.markUserNewsRead(newsId)
        : userApi.unmarkUserNewsRead(newsId),
    onSuccess: async (_data, variables) => {
      await invalidateNews(variables.newsId);
    },
    onError: (error) => {
      message.error(toApiError(error).message);
    },
  });

  const bookmarkMutation = useMutation({
    mutationFn: async ({
      newsId,
      bookmarked,
    }: {
      newsId: number;
      bookmarked: boolean;
    }) =>
      bookmarked
        ? userApi.bookmarkUserNews(newsId)
        : userApi.unbookmarkUserNews(newsId),
    onSuccess: async (_data, variables) => {
      await invalidateNews(variables.newsId);
    },
    onError: (error) => {
      message.error(toApiError(error).message);
    },
  });

  const readAllMutation = useMutation({
    mutationFn: () =>
      userApi.readAllUserNews({
        market_code: marketCode,
        symbol,
      }),
    onSuccess: async (result) => {
      message.success(`읽음 처리 ${result.updated_count}건`);
      await invalidateNews();
    },
    onError: (error) => {
      message.error(toApiError(error).message);
    },
  });

  const openDetail = (item: UserNewsItem) => {
    setSelectedNewsId(item.news_id);
    if (!item.is_read) {
      readMutation.mutate({ newsId: item.news_id, read: true });
    }
  };

  const watchlistEmpty =
    !watchlistQuery.isLoading &&
    (watchlistQuery.data?.items.length ?? 0) === 0;

  const items = newsQuery.data?.items ?? [];
  const totalCount = newsQuery.data?.total_count ?? 0;
  const hasNext = newsQuery.data?.has_next ?? false;

  const symbolOptions = useMemo(() => {
    const filtered = marketCode
      ? newsEnabledItems.filter(
          (item) => item.market.toUpperCase() === marketCode.toUpperCase(),
        )
      : newsEnabledItems;
    return filtered.map((item) => ({
      value: item.symbol,
      label: `${item.symbol} ${item.symbol_name}`,
    }));
  }, [newsEnabledItems, marketCode]);

  const marketOptions = useMemo(() => {
    const markets = Array.from(
      new Set(newsEnabledItems.map((item) => item.market.toUpperCase())),
    );
    return markets.map((m) => ({ value: m, label: m }));
  }, [newsEnabledItems]);

  return (
    <UserPageShell
      title="관심종목 뉴스"
      description="내 관심종목과 연결된 뉴스만 조회합니다. AI 요약은 준비 중입니다."
      extra={
        <Space wrap>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              void newsQuery.refetch();
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
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="AI 요약 기능은 준비 중입니다."
        description="현재는 수집된 제목·요약과 원문 링크만 제공합니다. 공시·AI 요약은 이후 STEP에서 제공됩니다."
      />

      {watchlistQuery.isError && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="관심종목을 불러오지 못했습니다."
          description={toApiError(watchlistQuery.error).message}
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

          {newsQuery.isLoading ? (
            <Skeleton active paragraph={{ rows: 8 }} />
          ) : newsQuery.isError ? (
            <Alert
              type="error"
              showIcon
              message="뉴스를 불러오지 못했습니다."
              description={toApiError(newsQuery.error).message}
            />
          ) : items.length === 0 ? (
            <Empty description="검색 결과가 없습니다." />
          ) : (
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              {items.map((item) => (
                <Card
                  key={item.news_id}
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
                        {item.title}
                      </Typography.Text>
                      {!item.is_read && <Tag color="blue">미읽음</Tag>}
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
                          newsId: item.news_id,
                          bookmarked: !item.is_bookmarked,
                        });
                      }}
                    />
                  }
                >
                  <Typography.Paragraph
                    type="secondary"
                    ellipsis={{ rows: 2 }}
                    style={{ marginBottom: 8 }}
                  >
                    {item.summary || "요약 없음"}
                  </Typography.Paragraph>
                  <Space wrap size={[8, 8]}>
                    <Tag>{item.source_name || item.source_code}</Tag>
                    <Typography.Text type="secondary">
                      {formatPublishedAt(item.published_at)}
                    </Typography.Text>
                    {item.matched_symbols.map((matched) => (
                      <Tag key={`${matched.market_code}-${matched.symbol}`}>
                        {matched.symbol_name || matched.symbol}
                      </Tag>
                    ))}
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
        title="뉴스 상세"
        width={520}
        open={selectedNewsId != null}
        onClose={() => setSelectedNewsId(null)}
        destroyOnClose
      >
        {detailQuery.isLoading ? (
          <Skeleton active />
        ) : detailQuery.isError ? (
          <Alert
            type="error"
            message={toApiError(detailQuery.error).message}
          />
        ) : detailQuery.data ? (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {detailQuery.data.title}
            </Typography.Title>
            <Space wrap>
              <Tag>{detailQuery.data.source_name}</Tag>
              <Typography.Text type="secondary">
                {formatPublishedAt(detailQuery.data.published_at)}
              </Typography.Text>
              {detailQuery.data.is_read ? (
                <Tag>읽음</Tag>
              ) : (
                <Tag color="blue">미읽음</Tag>
              )}
              {detailQuery.data.is_bookmarked && (
                <Tag color="gold">북마크</Tag>
              )}
            </Space>
            <Space wrap>
              {detailQuery.data.matched_symbols.map((matched) => (
                <Tag key={`${matched.market_code}-${matched.symbol}`}>
                  {matched.market_code} {matched.symbol_name || matched.symbol}
                </Tag>
              ))}
            </Space>
            <Typography.Paragraph>
              {detailQuery.data.summary || "요약 없음"}
            </Typography.Paragraph>
            <Alert
              type="info"
              showIcon
              message="AI 요약 기능은 준비 중입니다."
            />
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
                    newsId: detailQuery.data.news_id,
                    bookmarked: !detailQuery.data.is_bookmarked,
                  })
                }
              >
                {detailQuery.data.is_bookmarked
                  ? "북마크 해제"
                  : "북마크"}
              </Button>
              <Button
                onClick={() =>
                  readMutation.mutate({
                    newsId: detailQuery.data.news_id,
                    read: !detailQuery.data.is_read,
                  })
                }
              >
                {detailQuery.data.is_read ? "미읽음으로" : "읽음 처리"}
              </Button>
            </Space>
          </Space>
        ) : null}
      </Drawer>
    </UserPageShell>
  );
}
