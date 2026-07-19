"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useState } from "react";

import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { userRoutes } from "@/config/routes";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import * as userApi from "@/features/user/api/userApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";

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

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).filter(Boolean);
  }
  if (typeof value === "string" && value.trim()) {
    return [value];
  }
  return [];
}

export default function UserAiPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [exchange, setExchange] = useState("KRX");
  const [symbol, setSymbol] = useState("005930");
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);

  const topQuery = useQuery({
    queryKey: queryKeys.user.topCandidates(exchange),
    queryFn: () => userApi.getTopCandidates(exchange),
  });

  const latestQuery = useQuery({
    queryKey: queryKeys.user.aiLatest(exchange),
    queryFn: () => userApi.getLatestAiAnalysis(exchange),
    retry: false,
  });

  const runsQuery = useQuery({
    queryKey: queryKeys.user.aiRuns(exchange),
    queryFn: () =>
      userApi.listAiAnalysisRuns({ exchange_code: exchange, limit: 10 }),
  });

  const newsQuery = useQuery({
    queryKey: queryKeys.user.news(exchange, symbol),
    queryFn: () => userApi.getNewsContext(exchange, symbol),
  });

  const disclosuresQuery = useQuery({
    queryKey: queryKeys.user.dartDisclosures(symbol),
    queryFn: () =>
      userApi.listDartDisclosures({
        stock_code: symbol,
        limit: 15,
      }),
  });

  const ollamaStatusQuery = useQuery({
    queryKey: queryKeys.user.ollamaStatus(),
    queryFn: userApi.getOllamaStatus,
    retry: false,
  });

  const ollamaModelsQuery = useQuery({
    queryKey: queryKeys.user.ollamaModels(),
    queryFn: userApi.listOllamaModels,
    retry: false,
  });

  const latest = asRecord(latestQuery.data);
  const analysisRunId = Number(latest?.analysis_run_id ?? latest?.id ?? 0);
  const analysisCandidates = extractRows(latest?.candidates);

  const focusSymbol =
    selectedSymbol ??
    (analysisCandidates[0]
      ? String(analysisCandidates[0].symbol ?? "")
      : symbol);

  const selectSymbol = (nextSymbol: string) => {
    const normalized = nextSymbol.trim().toUpperCase();
    if (!normalized) return;
    setSelectedSymbol(normalized);
    setSymbol(normalized);
  };

  const rationaleQuery = useQuery({
    queryKey: queryKeys.user.aiRationale(
      analysisRunId || 0,
      focusSymbol || "_",
    ),
    queryFn: () =>
      userApi.getAiCandidateRationale(analysisRunId, focusSymbol),
    enabled: analysisRunId > 0 && Boolean(focusSymbol),
    retry: false,
  });

  const summarizeNews = useMutation({
    mutationFn: () =>
      userApi.summarizeNews({
        exchange_code: exchange,
        symbol,
        limit: 20,
      }),
    onSuccess: async (data) => {
      const saved = asRecord(data)?.saved_count;
      message.success(`뉴스 요약 완료 (saved=${cell(saved)})`);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.user.news(exchange, symbol),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const updateModel = useMutation({
    mutationFn: (modelName: string) =>
      userApi.updateAppSettings({
        items: [{ key: "ollama_model", value: modelName }],
        change_reason: "User Web AI 화면에서 모델 선택",
      }),
    onSuccess: async () => {
      message.success("Ollama 모델 설정 저장");
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.user.ollamaStatus(),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.user.ollamaModels(),
        }),
      ]);
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const topRows = extractRows(topQuery.data);
  const newsRows = extractRows(newsQuery.data);
  const disclosureRows = extractRows(disclosuresQuery.data);
  const runRows = extractRows(runsQuery.data);

  const latestError = latestQuery.error ? toApiError(latestQuery.error) : null;
  const latestNotFound = latestError?.status === 404;

  const rationale = asRecord(rationaleQuery.data);
  const rationaleCandidate = asRecord(rationale?.candidate);
  const selectedAnalysis = analysisCandidates.find(
    (row) => String(row.symbol) === focusSymbol,
  );

  const reasonItems = (() => {
    const fromRationale = asStringList(rationaleCandidate?.reasons);
    if (fromRationale.length) return fromRationale;
    if (selectedAnalysis) {
      const reasons = asStringList(selectedAnalysis.reasons);
      if (reasons.length) return reasons;
    }
    const top = topRows.find((row) => String(row.symbol) === focusSymbol);
    const breakdown = asRecord(top?.breakdown ?? top?.score_breakdown);
    if (breakdown) {
      return Object.entries(breakdown).map(
        ([key, value]) => `${key}: ${cell(value)}`,
      );
    }
    return [];
  })();

  const riskItems = asStringList(
    rationaleCandidate?.risks ?? selectedAnalysis?.risks,
  );
  const rationaleDetail = asRecord(rationaleCandidate?.rationale);

  const ollamaStatus = asRecord(ollamaStatusQuery.data);
  const ollamaModelsPayload = asRecord(ollamaModelsQuery.data);
  const ollamaModels = extractRows(
    ollamaModelsPayload?.models ?? ollamaModelsQuery.data,
  );
  const configuredModel = String(
    ollamaStatus?.configured_model ?? ollamaStatus?.model ?? "",
  );

  return (
    <UserPageShell
      title="AI 추천"
      description="추천 · 분석 · 의견 · 뉴스/공시 요약 · Ollama"
      extra={
        <Space wrap>
          <Button size="small">
            <Link href={userRoutes.news}>뉴스</Link>
          </Button>
          <Button size="small">
            <Link href={userRoutes.disclosures}>공시</Link>
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Space wrap size={8}>
          <Tag>
            Focus: {exchange}:{focusSymbol || "—"}
          </Tag>
          <Tag
            color={
              String(ollamaStatus?.status ?? "").toUpperCase() === "UP"
                ? "success"
                : ollamaStatusQuery.isError
                  ? "warning"
                  : "default"
            }
          >
            Ollama:{" "}
            {ollamaStatusQuery.isError
              ? "권한/연결 확인"
              : cell(ollamaStatus?.status ?? "…")}
          </Tag>
          <Tag>
            Model: {configuredModel || "—"}
          </Tag>
        </Space>

        <Card size="small" title="조회 조건">
          <Form
            key={`${exchange}-${symbol}`}
            layout="inline"
            initialValues={{ exchange_code: exchange, symbol }}
            onFinish={(v: { exchange_code: string; symbol: string }) => {
              setExchange(v.exchange_code.trim().toUpperCase());
              selectSymbol(v.symbol);
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
            <Button type="primary" htmlType="submit">
              조회
            </Button>
          </Form>
        </Card>

        {/* Ollama 모델 선택 */}
        <Card
          title="Ollama 모델 선택"
          size="small"
          loading={ollamaStatusQuery.isLoading || ollamaModelsQuery.isLoading}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              GET /ollama/status · /models · PUT /settings
            </Typography.Text>
          }
        >
          {ollamaStatusQuery.error || ollamaModelsQuery.error ? (
            <Alert
              type="warning"
              showIcon
              title="Ollama API 접근 실패"
              description={
                toApiError(
                  ollamaStatusQuery.error ?? ollamaModelsQuery.error!,
                ).message +
                " — settings:read / system:read / settings:write 권한이 필요할 수 있습니다."
              }
            />
          ) : (
            <Space wrap align="center">
              <Typography.Text>
                상태:{" "}
                <Tag
                  color={
                    String(ollamaStatus?.status ?? "").toUpperCase() === "UP"
                      ? "success"
                      : "error"
                  }
                >
                  {cell(ollamaStatus?.status)}
                </Tag>
              </Typography.Text>
              <Typography.Text type="secondary">
                {cell(ollamaStatus?.base_url)}
              </Typography.Text>
              <Select
                style={{ minWidth: 260 }}
                placeholder="모델 선택"
                loading={updateModel.isPending}
                value={configuredModel || undefined}
                options={ollamaModels.map((row) => ({
                  value: String(row.name ?? ""),
                  label: String(row.name ?? ""),
                }))}
                onChange={(value: string) => {
                  if (value) updateModel.mutate(value);
                }}
                notFoundContent="설치된 모델 없음"
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                변경은 DB 설정 `ollama_model` 에 저장됩니다
              </Typography.Text>
            </Space>
          )}
        </Card>

        <Row gutter={[16, 16]}>
          {/* AI 추천 종목 */}
          <Col xs={24} lg={12}>
            <Card
              title="AI 추천 종목"
              size="small"
              loading={topQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /candidates/top/{exchange}
                </Typography.Text>
              }
            >
              {topQuery.error ? (
                <Alert
                  type="error"
                  showIcon
                  title={toApiError(topQuery.error).message}
                />
              ) : (
                <Table
                  size="small"
                  pagination={false}
                  rowKey={(row) =>
                    tableRowKey(row, ["symbol", "rank", "score"])
                  }
                  dataSource={topRows.slice(0, 15)}
                  locale={{ emptyText: "추천 후보 없음" }}
                  onRow={(row) => ({
                    onClick: () => selectSymbol(String(row.symbol ?? "")),
                    style: {
                      cursor: "pointer",
                      background:
                        String(row.symbol) === focusSymbol
                          ? "rgba(22,119,255,0.08)"
                          : undefined,
                    },
                  })}
                  columns={[
                    {
                      title: "순위",
                      width: 60,
                      render: (_v, _row, index) => cell(index + 1),
                    },
                    { title: "심볼", dataIndex: "symbol", render: cell },
                    {
                      title: "점수",
                      dataIndex: "total_score",
                      render: (v, row) =>
                        cell(v ?? row.score ?? row.rank_score),
                    },
                  ]}
                />
              )}
            </Card>
          </Col>

          {/* AI 종목 분석 */}
          <Col xs={24} lg={12}>
            <Card
              title="AI 종목 분석"
              size="small"
              loading={latestQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /ai-analysis/latest/{exchange}
                </Typography.Text>
              }
            >
              {latestNotFound ? (
                <Alert
                  type="info"
                  showIcon
                  title="분석 결과 없음"
                  description="아직 AI 분석이 없습니다. Admin에서 분석을 실행한 뒤 조회하세요."
                />
              ) : latestError ? (
                <Alert type="error" showIcon title={latestError.message} />
              ) : (
                <>
                  <Descriptions
                    size="small"
                    column={1}
                    style={{ marginBottom: 12 }}
                  >
                    <Descriptions.Item label="run">
                      {cell(latest?.analysis_run_id)}
                    </Descriptions.Item>
                    <Descriptions.Item label="model">
                      {cell(latest?.model)}
                    </Descriptions.Item>
                    <Descriptions.Item label="status">
                      <Tag>{cell(latest?.status_code)}</Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="created">
                      {cell(latest?.created_at)}
                    </Descriptions.Item>
                  </Descriptions>
                  <Table
                    size="small"
                    pagination={false}
                    rowKey={(row) =>
                      tableRowKey(row, ["symbol", "rank", "ai_score"])
                    }
                    dataSource={analysisCandidates.slice(0, 10)}
                    locale={{ emptyText: "분석 후보 없음" }}
                    onRow={(row) => ({
                      onClick: () => selectSymbol(String(row.symbol ?? "")),
                      style: {
                        cursor: "pointer",
                        background:
                          String(row.symbol) === focusSymbol
                            ? "rgba(22,119,255,0.08)"
                            : undefined,
                      },
                    })}
                    columns={[
                      {
                        title: "순위",
                        dataIndex: "rank",
                        width: 60,
                        render: cell,
                      },
                      { title: "심볼", dataIndex: "symbol", render: cell },
                      {
                        title: "점수",
                        dataIndex: "ai_score",
                        render: cell,
                      },
                      {
                        title: "액션",
                        dataIndex: "action",
                        render: (v) => <Tag>{cell(v)}</Tag>,
                      },
                    ]}
                  />
                </>
              )}
            </Card>
          </Col>
        </Row>

        {/* AI 의견 */}
        <Card
          title={`AI 의견 · ${focusSymbol || "—"}`}
          size="small"
          loading={rationaleQuery.isLoading}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              GET /ai-analysis/runs/{"{id}"}/candidates/{"{symbol}"}
            </Typography.Text>
          }
        >
          {!focusSymbol ? (
            <Typography.Text type="secondary">
              추천/분석 목록에서 종목을 선택하세요
            </Typography.Text>
          ) : (
            <Row gutter={[16, 16]}>
              <Col xs={24} md={8}>
                <Descriptions size="small" column={1} title="판단">
                  <Descriptions.Item label="action">
                    <Tag>
                      {cell(
                        rationaleCandidate?.action ??
                          selectedAnalysis?.action,
                      )}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="confidence">
                    {cell(
                      rationaleCandidate?.confidence ??
                        selectedAnalysis?.confidence,
                    )}
                  </Descriptions.Item>
                  <Descriptions.Item label="ai_score">
                    {cell(
                      rationaleCandidate?.ai_score ??
                        selectedAnalysis?.ai_score,
                    )}
                  </Descriptions.Item>
                </Descriptions>
              </Col>
              <Col xs={24} md={8}>
                <Typography.Text strong>Reasons</Typography.Text>
                <ul style={{ marginTop: 8, paddingLeft: 18 }}>
                  {reasonItems.length === 0 ? (
                    <li>
                      <Typography.Text type="secondary">없음</Typography.Text>
                    </li>
                  ) : (
                    reasonItems.map((item) => (
                      <li key={item}>
                        <Typography.Text style={{ fontSize: 13 }}>
                          {item}
                        </Typography.Text>
                      </li>
                    ))
                  )}
                </ul>
              </Col>
              <Col xs={24} md={8}>
                <Typography.Text strong>Risks</Typography.Text>
                <ul style={{ marginTop: 8, paddingLeft: 18 }}>
                  {riskItems.length === 0 ? (
                    <li>
                      <Typography.Text type="secondary">없음</Typography.Text>
                    </li>
                  ) : (
                    riskItems.map((item) => (
                      <li key={item}>
                        <Typography.Text type="danger" style={{ fontSize: 13 }}>
                          {item}
                        </Typography.Text>
                      </li>
                    ))
                  )}
                </ul>
                {rationaleDetail ? (
                  <Typography.Paragraph
                    type="secondary"
                    style={{ fontSize: 12, marginTop: 8 }}
                  >
                    positive:{" "}
                    {asStringList(rationaleDetail.positive_reasons).join(
                      ", ",
                    ) || "—"}
                    <br />
                    negative:{" "}
                    {asStringList(rationaleDetail.negative_reasons).join(
                      ", ",
                    ) || "—"}
                  </Typography.Paragraph>
                ) : null}
              </Col>
            </Row>
          )}
        </Card>

        <Row gutter={[16, 16]}>
          {/* 뉴스 요약 */}
          <Col xs={24} lg={12}>
            <Card
              title={`뉴스 요약 · ${symbol}`}
              size="small"
              loading={newsQuery.isLoading}
              extra={
                <Space>
                  <Button
                    size="small"
                    loading={summarizeNews.isPending}
                    onClick={() => summarizeNews.mutate()}
                  >
                    요약 실행
                  </Button>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    POST /news/summarize
                  </Typography.Text>
                </Space>
              }
            >
              {newsQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title={toApiError(newsQuery.error).message}
                />
              ) : newsRows.length === 0 ? (
                <Typography.Text type="secondary">
                  뉴스 없음 — sync 후 다시 조회하세요
                </Typography.Text>
              ) : (
                <Space orientation="vertical" size={10} style={{ width: "100%" }}>
                  {newsRows.slice(0, 10).map((row, index) => (
                    <div
                      key={
                        tableRowKey(row, [
                          "title",
                          "published_at",
                          "original_link",
                        ]) + index
                      }
                      style={{
                        borderBottom: "1px solid rgba(0,0,0,0.06)",
                        paddingBottom: 8,
                      }}
                    >
                      <Typography.Text strong style={{ fontSize: 13 }}>
                        {cell(row.title)}
                      </Typography.Text>
                      <Typography.Paragraph
                        type="secondary"
                        style={{
                          marginBottom: 0,
                          marginTop: 4,
                          fontSize: 12,
                        }}
                      >
                        {cell(row.summary)}
                      </Typography.Paragraph>
                    </div>
                  ))}
                </Space>
              )}
            </Card>
          </Col>

          {/* 공시 요약 */}
          <Col xs={24} lg={12}>
            <Card
              title={`공시 요약 · ${symbol}`}
              size="small"
              loading={disclosuresQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /dart/disclosures
                </Typography.Text>
              }
            >
              {/* TODO: POST /dart/summarize */}
              <UnimplementedNotice
                feature="AI 공시 요약 생성"
                reason="공시 전용 AI 요약 API는 없습니다. DART 목록(보고서명·중요도)을 요약 대용으로 표시합니다."
                relatedApis={[
                  "GET /api/v1/dart/disclosures",
                  "TODO: POST /api/v1/dart/summarize",
                ]}
              />
              {disclosuresQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginTop: 12 }}
                  title={toApiError(disclosuresQuery.error).message}
                />
              ) : (
                <Table
                  size="small"
                  style={{ marginTop: 12 }}
                  pagination={false}
                  rowKey={(row) =>
                    tableRowKey(row, [
                      "disclosure_id",
                      "receipt_no",
                      "report_name",
                    ])
                  }
                  dataSource={disclosureRows.slice(0, 12)}
                  locale={{ emptyText: "공시 없음" }}
                  columns={[
                    {
                      title: "보고서",
                      dataIndex: "report_name",
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
                      title: "일자",
                      dataIndex: "receipt_date",
                      width: 100,
                      render: cell,
                    },
                  ]}
                />
              )}
            </Card>
          </Col>
        </Row>

        <Card
          title="최근 AI 분석 실행"
          size="small"
          loading={runsQuery.isLoading}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              GET /ai-analysis/runs
            </Typography.Text>
          }
        >
          <Table
            size="small"
            pagination={false}
            rowKey={(row) =>
              tableRowKey(row, ["analysis_run_id", "created_at"])
            }
            dataSource={runRows.slice(0, 8)}
            locale={{ emptyText: "실행 이력 없음" }}
            columns={[
              {
                title: "ID",
                dataIndex: "analysis_run_id",
                width: 80,
                render: cell,
              },
              { title: "거래소", dataIndex: "exchange_code", render: cell },
              { title: "모델", dataIndex: "model", render: cell },
              {
                title: "상태",
                dataIndex: "status_code",
                render: (v) => <Tag>{cell(v)}</Tag>,
              },
              { title: "시각", dataIndex: "created_at", render: cell },
            ]}
          />
        </Card>
      </Space>
    </UserPageShell>
  );
}
