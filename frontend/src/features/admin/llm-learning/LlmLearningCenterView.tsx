"use client";

/**
 * LLM 학습센터 — Dual LLM / RAG / Feedback / Shadow 집계 + Read-only Assistant.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Empty,
  Form,
  Input,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Timeline,
  Typography,
} from "antd";
import Link from "next/link";
import { useState } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { MarketSelector } from "@/features/admin/strategy-analysis/MarketSelector";
import {
  type StrategyMarket,
  withMarketQuery,
} from "@/features/admin/strategy-analysis/marketScope";
import { UpbitMaExitForwardShadowPanel } from "@/features/admin/upbit/UpbitMaExitForwardShadowPanel";
import { dash, safeArray } from "@/features/admin/upbit/researchDetailFormat";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const FEEDBACK_LABELS = [
  "GOOD_DECISION",
  "BAD_DECISION",
  "EARLY_EXIT",
  "BAD_ENTRY",
  "FEE_CHURN",
  "MISSED_WINNER",
  "NEWS_EVENT",
  "MARKET_ANOMALY",
  "EXCLUDE_FROM_TRAINING",
  "OTHER",
] as const;

const EXAMPLE_QUESTIONS = [
  "현재 학습 상태 알려줘",
  "UPBIT 최근 손실 원인은?",
  "Trading LLM 성능은?",
  "Teacher가 발견한 문제는?",
  "MA Confirm2 결과는?",
  "LoRA는 언제 가능한가?",
  "KIWOOM 표본은?",
  "최근 실패 사례 5개 설명해줘",
] as const;

function stageColor(status: string): "green" | "blue" | "default" | "orange" {
  if (status === "완료") return "green";
  if (status === "진행 중") return "blue";
  if (status === "표본 부족") return "orange";
  return "default";
}

function numOrDash(v: unknown): string {
  if (v == null || v === "") return "—";
  if (typeof v === "number" && !Number.isFinite(v)) return "—";
  return String(v);
}

type Props = {
  market: StrategyMarket;
};

export function LlmLearningCenterView({ market }: Props) {
  const apiMarket = market === "ALL" ? "ALL" : market;
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState("");
  const [askAnswer, setAskAnswer] = useState<Record<string, unknown> | null>(null);
  const [commentForm] = Form.useForm();

  const summaryQ = useQuery({
    queryKey: queryKeys.admin.llmLearningSummary(apiMarket),
    queryFn: () => adminApi.getAdminLlmLearningSummary({ market: apiMarket }),
    staleTime: 45_000,
    refetchOnWindowFocus: false,
  });

  const stagesQ = useQuery({
    queryKey: queryKeys.admin.llmLearningStages(apiMarket),
    queryFn: () => adminApi.getAdminLlmLearningStages({ market: apiMarket }),
    staleTime: 45_000,
    enabled: !summaryQ.isLoading,
  });

  const qualityQ = useQuery({
    queryKey: queryKeys.admin.llmLearningQuality(apiMarket),
    queryFn: () => adminApi.getAdminLlmLearningQuality({ market: apiMarket }),
    staleTime: 45_000,
    enabled: market !== "ALL" || true,
  });

  const teacherQ = useQuery({
    queryKey: queryKeys.admin.llmLearningTeacherReviews(apiMarket),
    queryFn: () =>
      adminApi.getAdminLlmLearningTeacherReviews({ market: apiMarket, limit: 30 }),
    staleTime: 60_000,
  });

  const loraQ = useQuery({
    queryKey: queryKeys.admin.llmLearningLoraReadiness(apiMarket),
    queryFn: () => adminApi.getAdminLlmLearningLoraReadiness({ market: apiMarket }),
    staleTime: 60_000,
  });

  const upbitSamplesQ = useQuery({
    queryKey: queryKeys.admin.llmLearningSamples("UPBIT"),
    queryFn: () => adminApi.getAdminLlmLearningSamples({ market: "UPBIT" }),
    staleTime: 60_000,
    enabled: market === "ALL" || market === "UPBIT",
  });

  const kiwoomSamplesQ = useQuery({
    queryKey: queryKeys.admin.llmLearningSamples("KIWOOM"),
    queryFn: () => adminApi.getAdminLlmLearningSamples({ market: "KIWOOM" }),
    staleTime: 60_000,
    enabled: market === "ALL" || market === "KIWOOM",
  });

  const askMut = useMutation({
    mutationFn: (q: string) =>
      adminApi.postAdminLlmLearningAsk({
        question: q,
        market: apiMarket,
        use_llm: true,
      }),
    onSuccess: (data) => {
      setAskAnswer(asRecord(data));
    },
  });

  const commentMut = useMutation({
    mutationFn: adminApi.postAdminLlmLearningComment,
    onSuccess: () => {
      commentForm.resetFields();
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.llmLearningComments(apiMarket),
      });
    },
  });

  const summary = asRecord(summaryQ.data) ?? {};
  const models = asRecord(summary.models) ?? {};
  const analysis = asRecord(summary.analysis) ?? {};
  const trading = asRecord(summary.trading) ?? {};
  const teacher = asRecord(summary.teacher) ?? {};
  const rag = asRecord(summary.rag) ?? {};
  const loraSummary = asRecord(summary.lora) ?? {};
  const samples = asRecord(summary.samples) ?? {};
  const stages = safeArray(asRecord(stagesQ.data)?.stages);
  const progressGate = asRecord(asRecord(stagesQ.data)?.progress_gate) ?? {};
  const quality = asRecord(qualityQ.data) ?? {};
  const lora = asRecord(loraQ.data) ?? {};
  const teacherItems = safeArray(asRecord(teacherQ.data)?.items);

  const upbitSamples = asRecord(upbitSamplesQ.data);
  const kiwoomSamples = asRecord(kiwoomSamplesQ.data);

  const answerBlock = asRecord(askAnswer?.answer);
  const contextRefs = asRecord(askAnswer?.context_refs);

  const exportMarket = market === "KIWOOM" ? "kiwoom" : "upbit";

  const sampleRows: Record<string, unknown>[] = [];
  if (market === "ALL" || market === "UPBIT") {
    sampleRows.push({ key: "UPBIT", market: "UPBIT", ...upbitSamples });
  }
  if (market === "ALL" || market === "KIWOOM") {
    sampleRows.push({ key: "KIWOOM", market: "KIWOOM", ...kiwoomSamples });
  }
  if (market !== "ALL") {
    sampleRows.push({ key: market, market, ...samples });
  }
  const tableRows =
    sampleRows.length > 0
      ? sampleRows
      : [{ key: "empty", market: apiMarket, CLEAN: 0 }];

  if (summaryQ.isLoading) {
    return <Spin description="LLM 학습센터 불러오는 중…" />;
  }
  if (summaryQ.isError) {
    return (
      <Alert
        type="error"
        showIcon
        title="조회 실패"
        description={toApiError(summaryQ.error).message}
      />
    );
  }

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} xl={16}>
        <Space orientation="vertical" size={16} style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            title="연구 전용 · REAL 미적용"
            description="CROSS_MARKET_RAG=0 · TRADING SHADOW · LoRA 자동 학습 금지"
          />

          <Card size="small" title="학습 진행 상태">
            {stages.length === 0 ? (
              <Typography.Text type="secondary">표본 수집 중</Typography.Text>
            ) : (
              <Timeline
                items={stages.map((s) => {
                  const rec = asRecord(s) ?? {};
                  const statusKo = String(rec.status_ko ?? "");
                  return {
                    color: stageColor(statusKo),
                    content: (
                      <Space>
                        <Typography.Text>{dash(rec.label_ko)}</Typography.Text>
                        <Tag color={stageColor(statusKo)}>{dash(rec.status_ko)}</Tag>
                        {rec.note ? (
                          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                            {String(rec.note)}
                          </Typography.Text>
                        ) : null}
                      </Space>
                    ),
                  };
                })}
              />
            )}
            <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
              {dash(progressGate.gate_label_ko)} · 기준: 30 / 100 / 500 / 1000 (자동 승격 없음)
            </Typography.Paragraph>
          </Card>

          <Row gutter={[12, 12]}>
            <Col xs={24} sm={12} md={8} lg={8} xl={8}>
              <Card size="small" title="Analysis">
                <Statistic title="Model" value={dash(models.ANALYSIS ?? analysis.model)} />
                <Typography.Text type="secondary">
                  Calls {numOrDash(analysis.calls)} · Samples {numOrDash(analysis.samples)}
                </Typography.Text>
                <br />
                <Typography.Text type="secondary">
                  Latency {numOrDash(analysis.median_latency_ms)}ms · Err{" "}
                  {numOrDash(analysis.errors)}
                </Typography.Text>
              </Card>
            </Col>
            <Col xs={24} sm={12} md={8} lg={8} xl={8}>
              <Card size="small" title="Trading">
                <Statistic
                  title="Mode"
                  value={dash(trading.mode ?? "SHADOW")}
                  styles={{ content: { fontSize: 18 } }}
                />
                <Typography.Text type="secondary">
                  Pred {numOrDash(trading.predictions)} · Out {numOrDash(trading.outcomes)}
                </Typography.Text>
                <br />
                <Typography.Text type="secondary">
                  Benefit {numOrDash(trading.accuracy_benefit)}
                </Typography.Text>
              </Card>
            </Col>
            <Col xs={24} sm={12} md={8} lg={8} xl={8}>
              <Card size="small" title="Teacher">
                <Statistic title="Model" value={dash(models.TEACHER ?? teacher.model)} />
                <Typography.Text type="secondary">
                  Reviews {numOrDash(teacher.reviews)} · Rate {numOrDash(teacher.review_rate)}
                </Typography.Text>
              </Card>
            </Col>
            <Col xs={24} sm={12} md={12}>
              <Card size="small" title="RAG">
                <Descriptions size="small" column={2}>
                  <Descriptions.Item label="Corpus">{numOrDash(rag.corpus_size)}</Descriptions.Item>
                  <Descriptions.Item label="Gold">{numOrDash(rag.gold)}</Descriptions.Item>
                  <Descriptions.Item label="Silver">{numOrDash(rag.silver)}</Descriptions.Item>
                  <Descriptions.Item label="Excluded">{numOrDash(rag.excluded)}</Descriptions.Item>
                  <Descriptions.Item label="Retrieval">{numOrDash(rag.retrieval_count)}</Descriptions.Item>
                  <Descriptions.Item label="Hit/Miss">
                    {numOrDash(rag.hit)}/{numOrDash(rag.miss)}
                  </Descriptions.Item>
                </Descriptions>
              </Card>
            </Col>
            <Col xs={24} sm={12} md={12}>
              <Card size="small" title="LoRA">
                <Descriptions size="small" column={1}>
                  <Descriptions.Item label="Dataset">
                    {numOrDash(loraSummary.ready_any ?? "—")}
                  </Descriptions.Item>
                  <Descriptions.Item label="Training">시작 안 함 (DISABLED)</Descriptions.Item>
                  <Descriptions.Item label="Last export">수동 내보내기만</Descriptions.Item>
                </Descriptions>
              </Card>
            </Col>
          </Row>

          <Card size="small" title="표본 진행 (시장 분리)">
            <Table
              size="small"
              pagination={false}
              dataSource={tableRows}
              columns={[
                { title: "Market", dataIndex: "market", key: "market" },
                { title: "CLEAN", dataIndex: "CLEAN", key: "clean", render: numOrDash },
                { title: "Prediction", dataIndex: "predictions", key: "pred", render: numOrDash },
                { title: "Outcome", dataIndex: "outcomes", key: "out", render: numOrDash },
                { title: "Gold", dataIndex: "gold", key: "gold", render: numOrDash },
                { title: "Silver", dataIndex: "silver", key: "silver", render: numOrDash },
                {
                  title: "Forward Shadow",
                  dataIndex: "forward_shadow",
                  key: "fs",
                  render: (v) => (v == null ? "—" : numOrDash(v)),
                },
              ]}
            />
          </Card>

          <Card size="small" title="LLM Quality">
            <Row gutter={12}>
              {(["analysis", "trading", "teacher"] as const).map((role) => {
                const q = asRecord(quality[role]) ?? {};
                return (
                  <Col xs={24} md={8} key={role}>
                    <Typography.Text strong>{role.toUpperCase()}</Typography.Text>
                    <Descriptions size="small" column={1}>
                      <Descriptions.Item label="model">{dash(q.model)}</Descriptions.Item>
                      <Descriptions.Item label="prompt">{dash(q.prompt_version)}</Descriptions.Item>
                      <Descriptions.Item label="sample N">{numOrDash(q.sample_n)}</Descriptions.Item>
                      <Descriptions.Item label="calls">{numOrDash(q.calls)}</Descriptions.Item>
                      <Descriptions.Item label="timeouts">{numOrDash(q.timeouts)}</Descriptions.Item>
                      <Descriptions.Item label="parse/err">{numOrDash(q.parse_errors)}</Descriptions.Item>
                      <Descriptions.Item label="latency ms">
                        {numOrDash(q.median_latency_ms)}
                      </Descriptions.Item>
                    </Descriptions>
                  </Col>
                );
              })}
            </Row>
          </Card>

          {(market === "ALL" || market === "UPBIT") && (
            <Card size="small" title="Forward Shadow — MA_DEAD_CROSS_CONFIRM2">
              <UpbitMaExitForwardShadowPanel />
            </Card>
          )}

          <Card size="small" title="Teacher Findings">
            {teacherItems.length === 0 ? (
              <Empty description="Teacher 검토 사례 없음 · 표본 수집 중" />
            ) : (
              <Table
                size="small"
                scroll={{ x: 900 }}
                pagination={{ pageSize: 10 }}
                dataSource={teacherItems.map((r, i) => {
                  const rec = asRecord(r) ?? {};
                  return { ...rec, key: rec.analysis_id ?? i };
                })}
                columns={[
                  { title: "Symbol", dataIndex: "symbol", width: 100 },
                  { title: "Market", dataIndex: "market", width: 80 },
                  { title: "Time", dataIndex: "time", width: 160, render: dash },
                  {
                    title: "Category",
                    dataIndex: "error_category",
                    width: 120,
                    render: (v) => <Tag>{dash(v)}</Tag>,
                  },
                  {
                    title: "Teacher",
                    key: "tc",
                    render: (_, row) => {
                      const tc = asRecord(asRecord(row)?.teacher_comment) ?? {};
                      return dash(tc.preferred_recommendation ?? tc.analysis_quality);
                    },
                  },
                ]}
              />
            )}
          </Card>

          <Card size="small" title="LoRA Training">
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              title="LoRA 학습 시작 버튼 비활성"
              description="조건 충족 전 자동/수동 학습 금지 · Dataset 내보내기만 허용"
            />
            <Space wrap>
              <Button
                type="primary"
                href={`/api/v1/admin/${exportMarket}/dual-llm/export/analysis`}
                target="_blank"
              >
                Analysis Dataset 내보내기
              </Button>
              <Button
                href={`/api/v1/admin/${exportMarket}/dual-llm/export/trading`}
                target="_blank"
              >
                Trading Dataset 내보내기
              </Button>
              <Button disabled title="조건 미충족 · TRAINING_STARTED=NO">
                LoRA 학습 시작
              </Button>
            </Space>
            <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
              Ready: {String(lora.training_button_enabled ?? false)} ·{" "}
              LORA_TRAINING_STARTED=NO
            </Typography.Paragraph>
          </Card>

          <Collapse
            items={[
              {
                key: "dev",
                label: "개발자 상세 보기",
                children: (
                  <pre style={{ fontSize: 11, maxHeight: 240, overflow: "auto" }}>
                    {JSON.stringify({ summary, quality, lora }, null, 2)}
                  </pre>
                ),
              },
            ]}
          />

          <Space wrap>
            <Link href={adminRoutes.aiAnalysis}>AI 분석</Link>
            <Link href={withMarketQuery(adminRoutes.researchData, market)}>연구 데이터</Link>
            <Link href={adminRoutes.ollama}>Ollama 역할 모델</Link>
          </Space>
        </Space>
      </Col>

      <Col xs={24} xl={8}>
        <Space orientation="vertical" size={16} style={{ width: "100%" }}>
          <Card size="small" title="LLM에게 물어보기" extra={<Tag>READ ONLY</Tag>}>
            <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
              Teacher {dash(models.TEACHER)} · 주문/전략 변경 불가
            </Typography.Paragraph>
            <Space wrap style={{ marginBottom: 8 }}>
              {EXAMPLE_QUESTIONS.map((q) => (
                <Button
                  key={q}
                  size="small"
                  onClick={() => {
                    setQuestion(q);
                    askMut.mutate(q);
                  }}
                >
                  {q}
                </Button>
              ))}
            </Space>
            <Input.TextArea
              rows={3}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="학습 상태, Confirm2, Teacher findings 등"
            />
            <Button
              type="primary"
              style={{ marginTop: 8 }}
              loading={askMut.isPending}
              onClick={() => question.trim() && askMut.mutate(question.trim())}
            >
              질문하기
            </Button>
            {askMut.isError ? (
              <Alert
                type="error"
                showIcon
                style={{ marginTop: 8 }}
                title={toApiError(askMut.error).message}
              />
            ) : null}
            {answerBlock ? (
              <Card size="small" style={{ marginTop: 12 }} title="답변">
                <Typography.Paragraph>
                  <Typography.Text strong>[현재 데이터]</Typography.Text>
                  <br />
                  {dash(answerBlock.current_data)}
                </Typography.Paragraph>
                <Typography.Paragraph>
                  <Typography.Text strong>[판단]</Typography.Text>
                  <br />
                  {dash(answerBlock.judgment)}
                </Typography.Paragraph>
                <Typography.Paragraph>
                  <Typography.Text strong>[표본 수]</Typography.Text>
                  <br />
                  {dash(answerBlock.sample_note)}
                </Typography.Paragraph>
                <Typography.Paragraph>
                  <Typography.Text strong>[주의사항]</Typography.Text>
                  <br />
                  {dash(answerBlock.caution)}
                </Typography.Paragraph>
                {contextRefs ? (
                  <Typography.Paragraph type="secondary" style={{ fontSize: 11 }}>
                    참조 데이터: {JSON.stringify(contextRefs)}
                  </Typography.Paragraph>
                ) : null}
              </Card>
            ) : null}
          </Card>

          <Card size="small" title="사용자 Comment (USER_REVIEWED)">
            <Form
              form={commentForm}
              layout="vertical"
              initialValues={{ market: market === "ALL" ? "UPBIT" : market, label: "OTHER" }}
              onFinish={(v) => commentMut.mutate(v)}
            >
              <Form.Item name="market" label="Market" rules={[{ required: true }]}>
                <Select
                  options={[
                    { value: "UPBIT", label: "UPBIT" },
                    { value: "KIWOOM", label: "KIWOOM" },
                  ]}
                />
              </Form.Item>
              <Form.Item name="symbol" label="Symbol">
                <Input placeholder="KRW-BTC" />
              </Form.Item>
              <Form.Item name="related_analysis_id" label="Analysis ID">
                <Input type="number" />
              </Form.Item>
              <Form.Item name="label" label="Label" rules={[{ required: true }]}>
                <Select options={FEEDBACK_LABELS.map((l) => ({ value: l, label: l }))} />
              </Form.Item>
              <Form.Item name="comment" label="Comment" rules={[{ required: true }]}>
                <Input.TextArea rows={3} />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={commentMut.isPending}>
                코멘트 저장
              </Button>
            </Form>
            {commentMut.isSuccess ? (
              <Alert type="success" showIcon style={{ marginTop: 8 }} title="저장됨 · 자동 GOLD 아님" />
            ) : null}
          </Card>
        </Space>
      </Col>
    </Row>
  );
}

export function LlmLearningCenterPage() {
  const [market, setMarket] = useState<StrategyMarket>("ALL");
  return (
    <AdminPageShell
      title="AI / LLM 학습센터"
      description="Dual LLM 학습·RAG·Feedback·Forward Shadow 현황과 Read-only Assistant"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <MarketSelector value={market} onChange={setMarket} />
        <LlmLearningCenterView market={market} />
      </Space>
    </AdminPageShell>
  );
}
