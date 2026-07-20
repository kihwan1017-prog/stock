"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Drawer,
  Empty,
  Form,
  InputNumber,
  Progress,
  Row,
  Select,
  Skeleton,
  Space,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useMemo, useState } from "react";

import { userRoutes } from "@/config/routes";
import type {
  AiRecommendationDetail,
  AiRecommendationListItem,
  CreateAiRecommendationRequest,
} from "@/features/user/api/userApi";
import * as userApi from "@/features/user/api/userApi";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const ACTION_COLOR: Record<string, string> = {
  POSITIVE: "green",
  WATCH: "blue",
  NEUTRAL: "default",
  CAUTION: "orange",
  AVOID: "red",
};

export default function UserAiPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [marketCode, setMarketCode] = useState("KRX");
  const [accountId, setAccountId] = useState<number | undefined>();
  const [sourceType, setSourceType] =
    useState<CreateAiRecommendationRequest["source_type"]>("WATCHLIST");
  const [horizon, setHorizon] =
    useState<CreateAiRecommendationRequest["investment_horizon"]>(
      "SHORT_TERM",
    );
  const [riskLevel, setRiskLevel] =
    useState<CreateAiRecommendationRequest["risk_level"]>("MODERATE");
  const [count, setCount] = useState(5);
  const [selectedRequestId, setSelectedRequestId] = useState<number | null>(
    null,
  );
  const [activeRequestId, setActiveRequestId] = useState<number | null>(null);

  const statusQuery = useQuery({
    queryKey: queryKeys.user.userAi.status(),
    queryFn: () => userApi.getUserAiStatus(),
  });

  const accountsQuery = useQuery({
    queryKey: queryKeys.user.userAccounts({ default: true }),
    queryFn: () => userApi.listUserAccounts({ default: true }),
  });

  const watchlistQuery = useQuery({
    queryKey: queryKeys.user.watchlist(),
    queryFn: () => userApi.listWatchlist(),
  });

  const listParams = useMemo(
    () => ({ market_code: marketCode, page: 1, page_size: 10 }),
    [marketCode],
  );

  const listQuery = useQuery({
    queryKey: queryKeys.user.userAi.recommendations.list(listParams),
    queryFn: () => userApi.listAiRecommendations(listParams),
  });

  const latestQuery = useQuery({
    queryKey: queryKeys.user.userAi.recommendations.latest({
      market_code: marketCode,
    }),
    queryFn: () =>
      userApi.getLatestAiRecommendation({ market_code: marketCode }),
    retry: false,
  });

  const detailId = selectedRequestId ?? activeRequestId;
  const detailQuery = useQuery({
    queryKey: queryKeys.user.userAi.recommendations.detail(detailId ?? 0),
    queryFn: () => userApi.getAiRecommendationDetail(detailId as number),
    enabled: detailId != null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "QUEUED" || status === "PROCESSING") return 3000;
      return false;
    },
  });

  const disclosureQuery = useQuery({
    queryKey: queryKeys.user.userDisclosures.recentSummaries(),
    queryFn: () => userApi.getRecentDisclosureAiSummaries(8),
  });

  const accountOptions = useMemo(
    () =>
      (accountsQuery.data?.items ?? []).map((item) => ({
        value: item.account_id,
        label: `${item.account_name ?? item.account_id}${
          item.is_default ? " (기본)" : ""
        }`,
      })),
    [accountsQuery.data?.items],
  );

  const aiEnabledCount =
    watchlistQuery.data?.items.filter((item) => item.ai_enabled).length ?? 0;

  const invalidateRec = async (requestId?: number) => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.user.userAi.recommendations.list(listParams),
    });
    await queryClient.invalidateQueries({
      queryKey: queryKeys.user.userAi.recommendations.latest({
        market_code: marketCode,
      }),
    });
    if (requestId != null) {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.userAi.recommendations.detail(requestId),
      });
    }
  };

  const createMutation = useMutation({
    mutationFn: () =>
      userApi.createAiRecommendation({
        market_code: marketCode,
        account_id: accountId ?? null,
        source_type: sourceType,
        recommendation_count: count,
        investment_horizon: horizon,
        risk_level: riskLevel,
      }),
    onSuccess: async (result) => {
      message.success(result.message);
      setActiveRequestId(result.request_id);
      setSelectedRequestId(result.request_id);
      await invalidateRec(result.request_id);
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
        ? userApi.bookmarkAiRecommendation(id)
        : userApi.unbookmarkAiRecommendation(id),
    onSuccess: async (_data, variables) => {
      await invalidateRec(variables.id);
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const hideMutation = useMutation({
    mutationFn: (id: number) => userApi.hideAiRecommendation(id),
    onSuccess: async (_data, id) => {
      message.success("추천을 숨겼습니다.");
      setSelectedRequestId(null);
      await invalidateRec(id);
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const available = statusQuery.data?.available ?? false;
  const displayDetail: AiRecommendationDetail | undefined =
    detailQuery.data ??
    (selectedRequestId == null ? latestQuery.data : undefined);

  return (
    <UserPageShell
      title="AI 추천"
      description="관심종목·보유종목 기반 참고용 AI 추천 (주문 자동 실행 없음)"
      extra={
        <Space wrap>
          <Button size="small">
            <Link href={userRoutes.watchlist}>관심종목</Link>
          </Button>
          <Button size="small">
            <Link href={userRoutes.disclosures}>공시</Link>
          </Button>
          <Button size="small">
            <Link href={userRoutes.news}>뉴스</Link>
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="warning"
          showIcon
          message="AI 추천은 투자 판단을 위한 참고 정보이며 수익을 보장하지 않습니다."
          description="실제 주문 전 시장 상황과 원문 데이터를 직접 확인하세요. 이 화면에서 주문이 실행되지 않습니다."
        />

        <Space wrap>
          <Tag color={available ? "success" : "warning"}>
            {available ? "AI 추천 사용 가능" : "AI 추천 일시 불가"}
          </Tag>
          {statusQuery.data?.active_model_display_name && (
            <Tag>{statusQuery.data.active_model_display_name}</Tag>
          )}
          <Tag>관심종목 AI 활성 {aiEnabledCount}개</Tag>
        </Space>

        {!available && (
          <Alert
            type="error"
            showIcon
            message={
              statusQuery.data?.message ||
              "현재 AI 추천 서비스를 사용할 수 없습니다."
            }
          />
        )}

        <Card size="small" title="추천 조건">
          <Form layout="inline">
            <Form.Item label="시장">
              <Select
                style={{ width: 120 }}
                value={marketCode}
                options={[
                  { value: "KRX", label: "KRX" },
                  { value: "UPBIT", label: "UPBIT" },
                ]}
                onChange={setMarketCode}
              />
            </Form.Item>
            <Form.Item label="계좌">
              <Select
                allowClear
                style={{ width: 200 }}
                placeholder="기본/선택"
                options={accountOptions}
                value={accountId}
                onChange={setAccountId}
              />
            </Form.Item>
            <Form.Item label="대상">
              <Select
                style={{ width: 200 }}
                value={sourceType}
                onChange={setSourceType}
                options={[
                  { value: "WATCHLIST", label: "관심종목" },
                  { value: "PORTFOLIO", label: "보유종목" },
                  {
                    value: "WATCHLIST_AND_PORTFOLIO",
                    label: "관심+보유",
                  },
                  {
                    value: "MARKET_CANDIDATES",
                    label: "시장 후보",
                  },
                ]}
              />
            </Form.Item>
            <Form.Item label="기간">
              <Select
                style={{ width: 140 }}
                value={horizon}
                onChange={setHorizon}
                options={[
                  { value: "SHORT_TERM", label: "단기" },
                  { value: "MEDIUM_TERM", label: "중기" },
                  { value: "LONG_TERM", label: "장기" },
                ]}
              />
            </Form.Item>
            <Form.Item label="위험">
              <Select
                style={{ width: 140 }}
                value={riskLevel}
                onChange={setRiskLevel}
                options={[
                  { value: "CONSERVATIVE", label: "보수" },
                  { value: "MODERATE", label: "보통" },
                  { value: "AGGRESSIVE", label: "공격" },
                ]}
              />
            </Form.Item>
            <Form.Item label="개수">
              <InputNumber
                min={1}
                max={10}
                value={count}
                onChange={(value) => setCount(Number(value) || 5)}
              />
            </Form.Item>
            <Button
              type="primary"
              loading={createMutation.isPending}
              disabled={!available}
              onClick={() => createMutation.mutate()}
            >
              추천 생성
            </Button>
          </Form>
        </Card>

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={14}>
            <Card
              title="추천 결과"
              size="small"
              loading={
                detailQuery.isLoading &&
                !displayDetail &&
                createMutation.isPending
              }
            >
              {!displayDetail ? (
                <Empty description="아직 완료된 추천이 없습니다." />
              ) : (
                <Space
                  orientation="vertical"
                  size={12}
                  style={{ width: "100%" }}
                >
                  <Space wrap>
                    <Tag>{displayDetail.status}</Tag>
                    <Tag>{displayDetail.source_type}</Tag>
                    {displayDetail.is_expired && (
                      <Tag color="orange">만료됨</Tag>
                    )}
                    <Typography.Text type="secondary">
                      요청 #{displayDetail.request_id}
                    </Typography.Text>
                  </Space>
                  {(displayDetail.status === "QUEUED" ||
                    displayDetail.status === "PROCESSING") && (
                    <Alert type="info" showIcon message="분석 중입니다…" />
                  )}
                  {displayDetail.status === "FAILED" && (
                    <Alert
                      type="error"
                      showIcon
                      message="추천 생성에 실패했습니다."
                      description={displayDetail.error_code || undefined}
                    />
                  )}
                  {displayDetail.items.map((item) => (
                    <Card key={`${item.symbol}-${item.rank}`} size="small">
                      <Space
                        orientation="vertical"
                        size={6}
                        style={{ width: "100%" }}
                      >
                        <Space wrap>
                          <Typography.Text strong>
                            #{item.rank} {item.symbol} {item.symbol_name}
                          </Typography.Text>
                          <Tag color={ACTION_COLOR[item.action] || "default"}>
                            {item.action}
                          </Tag>
                          {item.in_watchlist && <Tag>관심</Tag>}
                          {item.in_portfolio && <Tag>보유</Tag>}
                        </Space>
                        <div>
                          <Typography.Text type="secondary">
                            신뢰도
                          </Typography.Text>
                          <Progress
                            percent={Math.round(item.confidence_score * 100)}
                            size="small"
                          />
                        </div>
                        <Typography.Text>
                          점수 {item.total_score}
                        </Typography.Text>
                        <Typography.Paragraph style={{ marginBottom: 0 }}>
                          {item.summary}
                        </Typography.Paragraph>
                        <Typography.Text strong>근거</Typography.Text>
                        <ul style={{ margin: 0, paddingLeft: 18 }}>
                          {item.reasons.map((reason) => (
                            <li key={reason}>{reason}</li>
                          ))}
                        </ul>
                        <Typography.Text strong type="danger">
                          위험
                        </Typography.Text>
                        <ul style={{ margin: 0, paddingLeft: 18 }}>
                          {item.risk_factors.map((risk) => (
                            <li key={risk}>{risk}</li>
                          ))}
                        </ul>
                      </Space>
                    </Card>
                  ))}
                  <Space>
                    <Button
                      onClick={() =>
                        bookmarkMutation.mutate({
                          id: displayDetail.request_id,
                          bookmarked: !displayDetail.is_bookmarked,
                        })
                      }
                    >
                      {displayDetail.is_bookmarked
                        ? "북마크 해제"
                        : "북마크"}
                    </Button>
                    <Button
                      danger
                      onClick={() =>
                        hideMutation.mutate(displayDetail.request_id)
                      }
                    >
                      숨기기
                    </Button>
                  </Space>
                </Space>
              )}
            </Card>
          </Col>

          <Col xs={24} lg={10}>
            <Card title="최근 추천" size="small" loading={listQuery.isLoading}>
              {listQuery.isError ? (
                <Alert
                  type="error"
                  message={toApiError(listQuery.error).message}
                />
              ) : (listQuery.data?.items.length ?? 0) === 0 ? (
                <Empty description="이력 없음" />
              ) : (
                <Space
                  orientation="vertical"
                  style={{ width: "100%" }}
                  size={8}
                >
                  {listQuery.data?.items.map(
                    (item: AiRecommendationListItem) => (
                      <Card
                        key={item.request_id}
                        size="small"
                        hoverable
                        onClick={() => setSelectedRequestId(item.request_id)}
                      >
                        <Space wrap>
                          <Tag>{item.status}</Tag>
                          {item.is_expired && (
                            <Tag color="orange">만료</Tag>
                          )}
                          <Typography.Text>
                            {item.top_symbol
                              ? `${item.top_symbol} ${item.top_symbol_name ?? ""}`
                              : `요청 #${item.request_id}`}
                          </Typography.Text>
                        </Space>
                      </Card>
                    ),
                  )}
                </Space>
              )}
            </Card>

            <Card
              title="최근 공시 AI 요약"
              size="small"
              style={{ marginTop: 16 }}
              loading={disclosureQuery.isLoading}
              extra={
                <Button size="small">
                  <Link href={userRoutes.disclosures}>공시</Link>
                </Button>
              }
            >
              {(disclosureQuery.data?.items.length ?? 0) === 0 ? (
                <Typography.Text type="secondary">
                  최근 요약 없음
                </Typography.Text>
              ) : (
                <Space
                  orientation="vertical"
                  size={8}
                  style={{ width: "100%" }}
                >
                  {disclosureQuery.data?.items.map((row) => (
                    <div key={row.disclosure_id}>
                      <Tag>{row.symbol}</Tag>
                      <Typography.Text style={{ fontSize: 13 }}>
                        {row.report_name}
                      </Typography.Text>
                      <Typography.Paragraph
                        type="secondary"
                        style={{ fontSize: 12, marginBottom: 0 }}
                      >
                        {row.summary}
                      </Typography.Paragraph>
                    </div>
                  ))}
                </Space>
              )}
            </Card>
          </Col>
        </Row>
      </Space>

      <Drawer
        title="추천 상세"
        open={selectedRequestId != null}
        onClose={() => setSelectedRequestId(null)}
        width={520}
        destroyOnClose
      >
        {detailQuery.isLoading ? (
          <Skeleton active />
        ) : detailQuery.data ? (
          <Typography.Paragraph>
            {detailQuery.data.disclaimer}
          </Typography.Paragraph>
        ) : null}
        {detailQuery.data?.items.map((item) => (
          <Card key={item.symbol} size="small" style={{ marginBottom: 8 }}>
            <Typography.Text strong>
              #{item.rank} {item.symbol} {item.symbol_name}
            </Typography.Text>
            <div>
              <Tag color={ACTION_COLOR[item.action] || "default"}>
                {item.action}
              </Tag>
            </div>
            <Typography.Paragraph>{item.summary}</Typography.Paragraph>
          </Card>
        ))}
      </Drawer>
    </UserPageShell>
  );
}
