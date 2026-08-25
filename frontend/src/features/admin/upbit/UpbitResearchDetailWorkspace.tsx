"use client";

/**
 * Upbit Research Detail Workspace — CLEAN / Market / Asset / News / LLM / Experiment.
 * READ ONLY. Ant Design 6: Alert.title only (avoid deprecated Statistic styles).
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Collapse,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useMemo, useState, type ReactNode } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import {
  dash,
  formatKstClock,
  formatNumResearch,
  formatPctResearch,
  formatPriceResearch,
  safeArray,
} from "@/features/admin/upbit/researchDetailFormat";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type PageState = { page: number; pageSize: number };

function Tip({ label, tip }: { label: string; tip: string }) {
  return (
    <Tooltip title={tip}>
      <span style={{ borderBottom: "1px dashed rgba(0,0,0,0.25)", cursor: "help" }}>
        {label}
      </span>
    </Tooltip>
  );
}

function QueryState({
  isLoading,
  isError,
  error,
  empty,
  emptyHint,
  children,
}: {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  empty: boolean;
  emptyHint?: string;
  children: ReactNode;
}) {
  if (isLoading) {
    return <Typography.Text type="secondary">불러오는 중…</Typography.Text>;
  }
  if (isError) {
    return (
      <Alert
        type="error"
        showIcon
        title="조회 실패"
        description={toApiError(error).message}
      />
    );
  }
  if (empty) {
    return (
      <Empty
        description={emptyHint || "표시할 데이터가 없습니다"}
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    );
  }
  return <>{children}</>;
}

function JsonCollapse({ title, data }: { title: string; data: unknown }) {
  if (data == null) return null;
  return (
    <Collapse
      size="small"
      items={[
        {
          key: "raw",
          label: title,
          children: (
            <pre
              style={{
                margin: 0,
                maxHeight: 320,
                overflow: "auto",
                fontSize: 12,
              }}
            >
              {JSON.stringify(data, null, 2)}
            </pre>
          ),
        },
      ]}
    />
  );
}

function CleanForwardTab() {
  const [pageState, setPageState] = useState<PageState>({
    page: 1,
    pageSize: 20,
  });
  const [symbol, setSymbol] = useState("");
  const [recommendation, setRecommendation] = useState<string | undefined>();
  const [outcome, setOutcome] = useState<string | undefined>();
  const [earlyDump, setEarlyDump] = useState<string | undefined>();
  const [dataQuality, setDataQuality] = useState<string | undefined>();
  const [drawerId, setDrawerId] = useState<number | null>(null);

  const params = useMemo(
    () => ({
      page: pageState.page,
      page_size: pageState.pageSize,
      symbol: symbol.trim() || undefined,
      recommendation: recommendation || undefined,
      outcome: outcome || undefined,
      early_dump:
        earlyDump === "true" ? true : earlyDump === "false" ? false : undefined,
      data_quality: dataQuality || undefined,
    }),
    [pageState, symbol, recommendation, outcome, earlyDump, dataQuality],
  );

  const listQ = useQuery({
    queryKey: queryKeys.admin.upbitResearchCleanForward(params),
    queryFn: () => adminApi.getAdminUpbitResearchCleanForward(params),
  });

  const detailQ = useQuery({
    queryKey: queryKeys.admin.upbitResearchCleanForwardDetail(drawerId ?? 0),
    queryFn: () =>
      adminApi.getAdminUpbitResearchCleanForwardDetail(drawerId as number),
    enabled: drawerId != null && drawerId > 0,
  });

  const body = asRecord(listQ.data);
  const items = safeArray<Record<string, unknown>>(body?.items);
  const total = Number(body?.total ?? 0);

  const detail = asRecord(detailQ.data);
  const atEntry = asRecord(detail?.at_entry);
  const candidate = asRecord(atEntry?.candidate);
  const technical = asRecord(atEntry?.technical_features);
  const marketCtx = asRecord(atEntry?.market_context);
  const news = asRecord(atEntry?.news_notice);
  const llm = asRecord(atEntry?.llm_analysis);
  const outcomeSec = asRecord(detail?.forward_outcome);
  const quality = asRecord(detail?.research_quality);

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        <Tip
          label="정상 신규 검증 표본 (CLEAN Forward)"
          tip="Legacy 459·Backfill을 제외한 canonical 신규 표본입니다. REAL 승격 근거로 쓰기 전 목표 표본을 확인하세요."
        />
      </Typography.Paragraph>

      <Form layout="inline" size="small" style={{ rowGap: 8 }}>
        <Form.Item label="종목">
          <Input
            allowClear
            placeholder="KRW-BTC"
            value={symbol}
            onChange={(e) => {
              setSymbol(e.target.value);
              setPageState((s) => ({ ...s, page: 1 }));
            }}
            style={{ width: 140 }}
          />
        </Form.Item>
        <Form.Item label="AI 추천">
          <Select
            allowClear
            placeholder="전체"
            style={{ width: 120 }}
            value={recommendation}
            onChange={(v) => {
              setRecommendation(v);
              setPageState((s) => ({ ...s, page: 1 }));
            }}
            options={[
              { value: "ALLOW", label: "ALLOW" },
              { value: "HOLD", label: "HOLD" },
              { value: "REDUCE", label: "REDUCE" },
            ]}
          />
        </Form.Item>
        <Form.Item label="결과">
          <Input
            allowClear
            placeholder="outcome"
            value={outcome}
            onChange={(e) => {
              setOutcome(e.target.value || undefined);
              setPageState((s) => ({ ...s, page: 1 }));
            }}
            style={{ width: 140 }}
          />
        </Form.Item>
        <Form.Item label="Early dump">
          <Select
            allowClear
            placeholder="전체"
            style={{ width: 100 }}
            value={earlyDump}
            onChange={(v) => {
              setEarlyDump(v);
              setPageState((s) => ({ ...s, page: 1 }));
            }}
            options={[
              { value: "true", label: "예" },
              { value: "false", label: "아니오" },
            ]}
          />
        </Form.Item>
        <Form.Item label="품질">
          <Input
            allowClear
            placeholder="CANONICAL…"
            value={dataQuality}
            onChange={(e) => {
              setDataQuality(e.target.value || undefined);
              setPageState((s) => ({ ...s, page: 1 }));
            }}
            style={{ width: 140 }}
          />
        </Form.Item>
      </Form>

      <QueryState
        isLoading={listQ.isLoading}
        isError={listQ.isError}
        error={listQ.error}
        empty={!listQ.isLoading && items.length === 0}
        emptyHint="CLEAN 표본이 아직 없습니다"
      >
        <Table
          size="small"
          rowKey={(r) => String(r.shadow_id)}
          dataSource={items}
          scroll={{ x: 1400 }}
          pagination={{
            current: pageState.page,
            pageSize: pageState.pageSize,
            total,
            showSizeChanger: true,
            onChange: (page, pageSize) => setPageState({ page, pageSize }),
          }}
          onRow={(record) => ({
            onClick: () => setDrawerId(Number(record.shadow_id)),
            style: { cursor: "pointer" },
          })}
          columns={[
            {
              title: "감지시각(KST)",
              dataIndex: "detected_at",
              render: (v) => formatKstClock(v),
            },
            { title: "종목", dataIndex: "symbol", render: dash },
            {
              title: "scanner_run",
              dataIndex: "scanner_run_id",
              ellipsis: true,
              render: dash,
            },
            {
              title: "후보점수",
              dataIndex: "candidate_score",
              render: formatNumResearch,
            },
            {
              title: "AI 추천",
              dataIndex: "ai_recommendation",
              render: (v) => (v ? <Tag>{String(v)}</Tag> : "—"),
            },
            {
              title: "신뢰도",
              dataIndex: "ai_confidence",
              render: formatNumResearch,
            },
            {
              title: "진입가",
              dataIndex: "canonical_entry_price",
              render: formatPriceResearch,
            },
            {
              title: "가격출처",
              dataIndex: "entry_price_quality",
              render: dash,
            },
            {
              title: "5m",
              dataIndex: "return_5m_pct",
              render: (v) => formatPctResearch(v),
            },
            {
              title: "15m",
              dataIndex: "return_15m_pct",
              render: (v) => formatPctResearch(v),
            },
            {
              title: "30m",
              dataIndex: "return_30m_pct",
              render: (v) => formatPctResearch(v),
            },
            {
              title: "60m",
              dataIndex: "return_60m_pct",
              render: (v) => formatPctResearch(v),
            },
            {
              title: "MFE",
              dataIndex: "mfe_pct",
              render: (v) => formatPctResearch(v),
            },
            {
              title: "MAE",
              dataIndex: "mae_pct",
              render: (v) => formatPctResearch(v),
            },
            {
              title: "결과",
              dataIndex: "outcome_label",
              render: dash,
            },
            {
              title: "Early dump",
              dataIndex: "early_dump",
              render: (v) => (v ? <Tag color="warning">예</Tag> : "—"),
            },
            {
              title: "품질",
              dataIndex: "data_quality",
              render: dash,
            },
            {
              title: "CLEAN",
              dataIndex: "is_clean",
              render: (v) =>
                v ? <Tag color="success">예</Tag> : <Tag>아니오</Tag>,
            },
          ]}
        />
      </QueryState>

      <Typography.Text type="secondary" data-testid="clean-forward-total">
        CLEAN 총 {Number.isFinite(total) ? total : 0}건
      </Typography.Text>

      <Drawer
        title={`CLEAN 상세 #${drawerId ?? ""}`}
        size="large"
        open={drawerId != null}
        onClose={() => setDrawerId(null)}
        destroyOnHidden
      >
        {detailQ.isLoading ? (
          <Typography.Text type="secondary">상세 로딩…</Typography.Text>
        ) : detailQ.isError ? (
          <Alert
            type="error"
            showIcon
            title="상세 조회 실패"
            description={toApiError(detailQ.error).message}
          />
        ) : !detail ? (
          <Empty description="상세 없음" />
        ) : (
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              title="Look-ahead 분리"
              description="위쪽은 진입 당시 Context, 아래 Forward Outcome은 진입 이후 결과입니다."
            />

            <Card size="small" title="후보 정보">
              <Descriptions size="small" column={1}>
                <Descriptions.Item label="scanner run">
                  {dash(candidate?.scanner_run_id)}
                </Descriptions.Item>
                <Descriptions.Item label="detected_at">
                  {formatKstClock(candidate?.detected_at)}
                </Descriptions.Item>
                <Descriptions.Item label="종목">
                  {dash(candidate?.symbol)}
                </Descriptions.Item>
                <Descriptions.Item label="점수">
                  {formatNumResearch(candidate?.score)}
                </Descriptions.Item>
                <Descriptions.Item label="후보 사유">
                  {dash(candidate?.candidate_reason)}
                </Descriptions.Item>
              </Descriptions>
            </Card>

            <Card size="small" title="진입 당시 기술지표">
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="MA5">
                  {formatNumResearch(technical?.ma5)}
                </Descriptions.Item>
                <Descriptions.Item label="MA20">
                  {formatNumResearch(technical?.ma20)}
                </Descriptions.Item>
                <Descriptions.Item label="RSI14">
                  {formatNumResearch(technical?.rsi14)}
                </Descriptions.Item>
                <Descriptions.Item label="거래량급증">
                  {formatNumResearch(technical?.volume_surge)}
                </Descriptions.Item>
                <Descriptions.Item label="MA 이격">
                  {formatPctResearch(technical?.ma_separation_pct)}
                </Descriptions.Item>
                <Descriptions.Item label="near-high">
                  {formatNumResearch(technical?.near_high)}
                </Descriptions.Item>
              </Descriptions>
              <JsonCollapse
                title="저장된 feature 원본"
                data={technical?.stored_features}
              />
            </Card>

            <Card size="small" title="시장 Context (진입 시점)">
              <Typography.Text type="secondary">
                연결 신뢰도: {dash(marketCtx?.relation_confidence)}
              </Typography.Text>
              <JsonCollapse title="시장 Context 상세" data={marketCtx} />
            </Card>

            <Card size="small" title="종목 Context (진입 시점)">
              <JsonCollapse
                title="종목 Context 상세"
                data={atEntry?.asset_context ?? marketCtx?.asset_context}
              />
            </Card>

            <Card size="small" title="뉴스·공지 (detected_at 이전만)">
              <Typography.Paragraph type="secondary">
                {dash(news?.note_ko)}
              </Typography.Paragraph>
              <Table
                size="small"
                rowKey={(r) => String(r.article_id)}
                pagination={false}
                dataSource={safeArray<Record<string, unknown>>(news?.items)}
                columns={[
                  {
                    title: "발행",
                    dataIndex: "published_at",
                    render: formatKstClock,
                  },
                  { title: "유형", dataIndex: "type", render: dash },
                  { title: "제목", dataIndex: "title", ellipsis: true },
                ]}
                locale={{ emptyText: "관련 사전 뉴스 없음" }}
              />
            </Card>

            <Card size="small" title="LLM 분석">
              {llm?.found ? (
                <>
                  <Descriptions size="small" column={1}>
                    <Descriptions.Item label="추천">
                      {dash(asRecord(llm.analysis)?.recommendation)}
                    </Descriptions.Item>
                    <Descriptions.Item label="신뢰도">
                      {formatNumResearch(asRecord(llm.analysis)?.confidence)}
                    </Descriptions.Item>
                    <Descriptions.Item label="사유">
                      {dash(asRecord(llm.analysis)?.reason)}
                    </Descriptions.Item>
                    <Descriptions.Item label="분석시각">
                      {formatKstClock(asRecord(llm.analysis)?.analysis_at)}
                    </Descriptions.Item>
                    <Descriptions.Item label="context_as_of">
                      {formatKstClock(asRecord(llm.analysis)?.context_as_of)}
                    </Descriptions.Item>
                    <Descriptions.Item label="연결">
                      {dash(llm.relation_confidence)}
                    </Descriptions.Item>
                  </Descriptions>
                  <JsonCollapse
                    title="structured context"
                    data={asRecord(llm.analysis)?.structured_input}
                  />
                </>
              ) : (
                <Empty
                  description={dash(
                    llm?.empty_hint_ko ||
                      "신규 Scanner Shadow 후보 발생 시 분석됩니다.",
                  )}
                />
              )}
            </Card>

            <Card size="small" title="Forward Outcome (진입 이후)">
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="진입가">
                  {formatPriceResearch(outcomeSec?.entry_price)}
                </Descriptions.Item>
                <Descriptions.Item label="결과라벨">
                  {dash(outcomeSec?.outcome_label)}
                </Descriptions.Item>
                <Descriptions.Item label="5m">
                  {formatPctResearch(outcomeSec?.return_5m_pct)}
                </Descriptions.Item>
                <Descriptions.Item label="15m">
                  {formatPctResearch(outcomeSec?.return_15m_pct)}
                </Descriptions.Item>
                <Descriptions.Item label="30m">
                  {formatPctResearch(outcomeSec?.return_30m_pct)}
                </Descriptions.Item>
                <Descriptions.Item label="60m">
                  {formatPctResearch(outcomeSec?.return_60m_pct)}
                </Descriptions.Item>
                <Descriptions.Item label="MFE">
                  {formatPctResearch(outcomeSec?.mfe_pct)}
                </Descriptions.Item>
                <Descriptions.Item label="MAE">
                  {formatPctResearch(outcomeSec?.mae_pct)}
                </Descriptions.Item>
              </Descriptions>
            </Card>

            <Card size="small" title="연구 품질">
              <Descriptions size="small" column={1}>
                <Descriptions.Item label="backfill">
                  {quality?.research_stamp_backfill ? "예" : "아니오"}
                </Descriptions.Item>
                <Descriptions.Item label="clean eligible">
                  {quality?.clean_eligible ? "예" : "아니오"}
                </Descriptions.Item>
              </Descriptions>
              <JsonCollapse
                title="provenance / stamps"
                data={{
                  provenance: quality?.canonical_price_provenance,
                  exit_ab: quality?.exit_ab,
                  entry_ab: quality?.entry_ab,
                  entry_forward_features: quality?.entry_forward_features,
                }}
              />
            </Card>
          </Space>
        )}
      </Drawer>
    </Space>
  );
}

function PaginatedContextTab({
  kind,
}: {
  kind: "market" | "asset" | "news" | "llm";
}) {
  const [pageState, setPageState] = useState<PageState>({
    page: 1,
    pageSize: 20,
  });
  const [symbol, setSymbol] = useState("");
  const [llmDrawer, setLlmDrawer] = useState<number | null>(null);

  const params = useMemo(() => {
    const base: Record<string, unknown> = {
      page: pageState.page,
      page_size: pageState.pageSize,
    };
    if (symbol.trim() && (kind === "asset" || kind === "news" || kind === "llm")) {
      base.symbol = symbol.trim();
    }
    return base;
  }, [pageState, symbol, kind]);

  const q = useQuery({
    queryKey:
      kind === "market"
        ? queryKeys.admin.upbitResearchMarketContext(params)
        : kind === "asset"
          ? queryKeys.admin.upbitResearchAssetContext(params)
          : kind === "news"
            ? queryKeys.admin.upbitResearchNews(params)
            : queryKeys.admin.upbitResearchLlmAnalysis(params),
    queryFn: () => {
      if (kind === "market") return adminApi.getAdminUpbitResearchMarketContext(params);
      if (kind === "asset") return adminApi.getAdminUpbitResearchAssetContext(params);
      if (kind === "news") return adminApi.getAdminUpbitResearchNews(params);
      return adminApi.getAdminUpbitResearchLlmAnalysis(params);
    },
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  const llmDetailQ = useQuery({
    queryKey: queryKeys.admin.upbitResearchLlmDetail(llmDrawer ?? 0),
    queryFn: () =>
      adminApi.getAdminUpbitResearchLlmAnalysisDetail(llmDrawer as number),
    enabled: kind === "llm" && llmDrawer != null,
  });

  const body = asRecord(q.data);
  const items = safeArray<Record<string, unknown>>(body?.items);
  const total = Number(body?.total ?? 0);
  const emptyHint =
    kind === "llm"
      ? String(
          body?.empty_hint_ko ||
            "신규 Scanner Shadow 후보 발생 시 분석됩니다.",
        )
      : undefined;

  const columns =
    kind === "market"
      ? [
          {
            title: "수집시각",
            dataIndex: "collected_at",
            render: formatKstClock,
          },
          {
            title: (
              <Tip label="Fear & Greed" tip="시장 심리 지표 (저장된 feature만)" />
            ),
            dataIndex: "fear_greed",
            render: formatNumResearch,
          },
          {
            title: "시장 상승 비중",
            dataIndex: "market_breadth",
            render: formatNumResearch,
          },
          {
            title: "24h 거래대금",
            dataIndex: "total_turnover",
            render: formatNumResearch,
          },
          {
            title: "시장 수익률 proxy",
            dataIndex: "market_return_proxy",
            render: (v: unknown) => formatPctResearch(v),
          },
          { title: "출처", dataIndex: "source", render: dash },
          { title: "신선도", dataIndex: "freshness", render: dash },
          { title: "품질", dataIndex: "quality", render: dash },
          {
            title: "원본",
            key: "raw",
            render: (_: unknown, row: Record<string, unknown>) => (
              <JsonCollapse title="원본 데이터" data={row.value_json} />
            ),
          },
        ]
      : kind === "asset"
        ? [
            {
              title: "수집시각",
              dataIndex: "collected_at",
              render: formatKstClock,
            },
            { title: "종목", dataIndex: "symbol", render: dash },
            {
              title: "현재가",
              dataIndex: "trade_price",
              render: formatPriceResearch,
            },
            {
              title: "등락률",
              dataIndex: "daily_change_pct",
              render: (v: unknown) => formatPctResearch(v),
            },
            {
              title: "24h 거래대금",
              dataIndex: "turnover_24h",
              render: formatNumResearch,
            },
            {
              title: "순위",
              dataIndex: "turnover_rank",
              render: dash,
            },
            {
              title: "거래량",
              dataIndex: "volume",
              render: formatNumResearch,
            },
            {
              title: "품질",
              dataIndex: "context_quality",
              render: dash,
            },
          ]
        : kind === "news"
          ? [
              {
                title: "발행",
                dataIndex: "published_at",
                render: formatKstClock,
              },
              {
                title: "수집",
                dataIndex: "collected_at",
                render: formatKstClock,
              },
              { title: "출처", dataIndex: "source", render: dash },
              { title: "유형", dataIndex: "type", render: dash },
              {
                title: "제목",
                dataIndex: "title",
                ellipsis: true,
                render: dash,
              },
              {
                title: "종목",
                dataIndex: "related_symbol",
                render: dash,
              },
              {
                title: "요약",
                dataIndex: "summary",
                ellipsis: true,
                render: dash,
              },
              {
                title: "LLM",
                dataIndex: "llm_used",
                render: (v: unknown) => (v == null ? "—" : String(v)),
              },
              {
                title: "원문",
                dataIndex: "url",
                render: (v: unknown) =>
                  v ? (
                    <a href={String(v)} target="_blank" rel="noreferrer">
                      열기
                    </a>
                  ) : (
                    "—"
                  ),
              },
            ]
          : [
              {
                title: "분석시각",
                dataIndex: "analysis_at",
                render: formatKstClock,
              },
              { title: "종목", dataIndex: "symbol", render: dash },
              {
                title: "shadow",
                dataIndex: "shadow_id",
                render: dash,
              },
              {
                title: "추천",
                dataIndex: "recommendation",
                render: (v: unknown) => (v ? <Tag>{String(v)}</Tag> : "—"),
              },
              {
                title: "점수",
                dataIndex: "score",
                render: formatNumResearch,
              },
              {
                title: "신뢰도",
                dataIndex: "confidence",
                render: formatNumResearch,
              },
              {
                title: "risk",
                dataIndex: "risk_flags",
                render: (v: unknown) =>
                  Array.isArray(v) ? v.join(", ") || "—" : dash(v),
              },
              {
                title: "context_as_of",
                dataIndex: "context_as_of",
                render: formatKstClock,
              },
              { title: "model", dataIndex: "model", render: dash },
              { title: "상태", dataIndex: "status", render: dash },
            ];

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      {(kind === "asset" || kind === "news" || kind === "llm") && (
        <Input
          allowClear
          size="small"
          placeholder="종목 필터 (예: KRW-BTC)"
          value={symbol}
          onChange={(e) => {
            setSymbol(e.target.value);
            setPageState((s) => ({ ...s, page: 1 }));
          }}
          style={{ maxWidth: 240 }}
        />
      )}
      <QueryState
        isLoading={q.isLoading}
        isError={q.isError}
        error={q.error}
        empty={!q.isLoading && items.length === 0}
        emptyHint={emptyHint}
      >
        <Table
          size="small"
          rowKey={(r) =>
            String(
              r.snapshot_id ??
                r.article_id ??
                r.analysis_id ??
                `${r.symbol}-${r.collected_at ?? r.analysis_at}`,
            )
          }
          dataSource={items}
          scroll={{ x: 1100 }}
          pagination={{
            current: pageState.page,
            pageSize: pageState.pageSize,
            total,
            showSizeChanger: true,
            onChange: (page, pageSize) => setPageState({ page, pageSize }),
          }}
          onRow={
            kind === "llm"
              ? (record) => ({
                  onClick: () => setLlmDrawer(Number(record.analysis_id)),
                  style: { cursor: "pointer" },
                })
              : undefined
          }
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          columns={columns as any}
        />
      </QueryState>

      {kind === "llm" ? (
        <Drawer
          title={`AI 분석 #${llmDrawer ?? ""}`}
          open={llmDrawer != null}
          onClose={() => setLlmDrawer(null)}
          size="large"
          destroyOnHidden
        >
          {llmDetailQ.isLoading ? (
            <Typography.Text type="secondary">로딩…</Typography.Text>
          ) : llmDetailQ.isError ? (
            <Alert
              type="error"
              showIcon
              title="상세 실패"
              description={toApiError(llmDetailQ.error).message}
            />
          ) : (
            <>
              <Descriptions size="small" column={1}>
                <Descriptions.Item label="추천">
                  {dash(asRecord(llmDetailQ.data)?.recommendation)}
                </Descriptions.Item>
                <Descriptions.Item label="사유">
                  {dash(asRecord(llmDetailQ.data)?.reason)}
                </Descriptions.Item>
              </Descriptions>
              <JsonCollapse
                title="제공 Context (structured)"
                data={asRecord(llmDetailQ.data)?.structured_context}
              />
              <JsonCollapse
                title="structured output"
                data={asRecord(llmDetailQ.data)?.structured_output}
              />
            </>
          )}
        </Drawer>
      ) : null}
    </Space>
  );
}

function ExperimentsTab() {
  const q = useQuery({
    queryKey: queryKeys.admin.upbitResearchExperiments(),
    queryFn: () => adminApi.getAdminUpbitResearchExperiments(),
  });
  const body = asRecord(q.data);
  const arms = safeArray<Record<string, unknown>>(body?.arms);
  const under = Boolean(body?.under_promotion_sample);
  const best = body?.best_filter_currently;

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      {under ? (
        <Alert
          type="warning"
          showIcon
          title="연구 표본 수집 중 — REAL 전략 승격 근거로 사용할 수 없습니다."
        />
      ) : null}
      {best != null ? (
        <Alert
          type="info"
          showIcon
          title="현재 연구 후보"
          description="BEST_FILTER_CURRENTLY는 연구 후보 표시일 뿐이며 운영 전략으로 쓰지 마세요."
        />
      ) : null}
      <Typography.Text type="secondary">
        CLEAN 표본 {dash(body?.clean_sample_count)} · gate{" "}
        {dash(body?.sample_gate)}
      </Typography.Text>
      <QueryState
        isLoading={q.isLoading}
        isError={q.isError}
        error={q.error}
        empty={!q.isLoading && arms.length === 0}
      >
        <Table
          size="small"
          rowKey={(r) => String(r.experiment)}
          dataSource={arms}
          pagination={false}
          columns={[
            { title: "실험", dataIndex: "experiment", render: dash },
            { title: "이름", dataIndex: "name", ellipsis: true, render: dash },
            {
              title: "Accepted",
              dataIndex: "accepted",
              render: formatNumResearch,
            },
            {
              title: "Filtered",
              dataIndex: "filtered",
              render: formatNumResearch,
            },
            {
              title: "Avoided Loss",
              dataIndex: "avoided_loss",
              render: formatNumResearch,
            },
            {
              title: "Missed Winner",
              dataIndex: "missed_winner",
              render: formatNumResearch,
            },
            {
              title: "Benefit",
              dataIndex: "benefit",
              render: formatNumResearch,
            },
            { title: "Net", dataIndex: "net", render: formatNumResearch },
            { title: "PF", dataIndex: "pf", render: formatNumResearch },
            {
              title: "Early Dump Rate",
              dataIndex: "early_dump_rate",
              render: (v) => formatPctResearch(Number(v) * 100),
            },
          ]}
        />
      </QueryState>
    </Space>
  );
}

function RagFeedbackTab() {
  const [verdict, setVerdict] = useState<string | undefined>();
  const [tier, setTier] = useState<string | undefined>();
  const [teacherOnly, setTeacherOnly] = useState<string | undefined>();
  const [drawerId, setDrawerId] = useState<number | null>(null);

  const params = useMemo(
    () => ({
      limit: 50,
      verdict: verdict || undefined,
      tier: tier || undefined,
      teacher_reviewed:
        teacherOnly === "true"
          ? true
          : teacherOnly === "false"
            ? false
            : undefined,
    }),
    [verdict, tier, teacherOnly],
  );

  const listQ = useQuery({
    queryKey: queryKeys.admin.upbitDualLlmRagFeedback(params),
    queryFn: () => adminApi.getAdminUpbitDualLlmRagFeedback(params),
  });
  const detailQ = useQuery({
    queryKey: queryKeys.admin.upbitDualLlmRagFeedbackDetail(drawerId ?? 0),
    queryFn: () =>
      adminApi.getAdminUpbitDualLlmRagFeedbackDetail(drawerId as number),
    enabled: drawerId != null,
  });

  const items = safeArray<Record<string, unknown>>(
    asRecord(listQ.data)?.items,
  );
  const flow = asRecord(asRecord(detailQ.data)?.flow);

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="RAG / Feedback — 연구 전용"
        description="CLEAN 유사사례 + Trading SHADOW 예측 vs 실제 결과. Teacher는 정답이 아닙니다. LoRA 학습은 이 화면에서 시작하지 않습니다."
      />
      <Form layout="inline" size="small">
        <Form.Item label="Verdict">
          <Select
            allowClear
            style={{ width: 200 }}
            placeholder="전체"
            value={verdict}
            onChange={setVerdict}
            options={[
              { value: "ALLOW_SUCCESS", label: "ALLOW_SUCCESS" },
              { value: "ALLOW_EARLY_DUMP", label: "ALLOW_EARLY_DUMP" },
              { value: "HOLD_AVOIDED_LOSS", label: "HOLD_AVOIDED_LOSS" },
              { value: "HOLD_MISSED_WINNER", label: "HOLD_MISSED_WINNER" },
              { value: "REDUCE_AVOIDED_LOSS", label: "REDUCE_AVOIDED_LOSS" },
              { value: "REDUCE_MISSED_WINNER", label: "REDUCE_MISSED_WINNER" },
              { value: "EARLY_DUMP", label: "Early Dump (부분)" },
              { value: "MISSED", label: "Missed Winner (부분)" },
            ]}
          />
        </Form.Item>
        <Form.Item label="Tier">
          <Select
            allowClear
            style={{ width: 120 }}
            placeholder="전체"
            value={tier}
            onChange={setTier}
            options={[
              { value: "GOLD", label: "GOLD" },
              { value: "SILVER", label: "SILVER" },
              { value: "EXCLUDED", label: "EXCLUDED" },
            ]}
          />
        </Form.Item>
        <Form.Item label="Teacher">
          <Select
            allowClear
            style={{ width: 120 }}
            placeholder="전체"
            value={teacherOnly}
            onChange={setTeacherOnly}
            options={[
              { value: "true", label: "Reviewed" },
              { value: "false", label: "Not reviewed" },
            ]}
          />
        </Form.Item>
      </Form>
      <QueryState
        isLoading={listQ.isLoading}
        isError={listQ.isError}
        error={listQ.error}
        empty={!listQ.isLoading && items.length === 0}
        emptyHint="Dual LLM RAG/Feedback row가 아직 없습니다. 신규 Scanner 후보 → outcome 완료 후 축적됩니다."
      >
        <Table
          size="small"
          rowKey={(r) => String(r.analysis_id)}
          dataSource={items}
          pagination={false}
          onRow={(r) => ({
            onClick: () => setDrawerId(Number(r.analysis_id)),
            style: { cursor: "pointer" },
          })}
          columns={[
            { title: "ID", dataIndex: "analysis_id", width: 70, render: dash },
            { title: "Symbol", dataIndex: "symbol", render: dash },
            {
              title: "Detected",
              dataIndex: "detected_at",
              render: (v) => formatKstClock(v),
            },
            {
              title: "Trading",
              dataIndex: "trading_prediction",
              render: dash,
            },
            {
              title: "Actual",
              dataIndex: "actual_result",
              render: (v) => dash(asRecord(v)?.label),
            },
            {
              title: "Verdict",
              dataIndex: "prediction_verdict",
              render: dash,
            },
            {
              title: "RAG",
              dataIndex: "rag_examples",
              render: (v) =>
                Array.isArray(v) ? String(v.length) : "0",
            },
            {
              title: "Teacher",
              dataIndex: "teacher_reviewed",
              render: (v) => (v ? <Tag color="blue">Y</Tag> : "—"),
            },
            {
              title: "Tier",
              dataIndex: "dataset_tier",
              render: (v) => (v ? <Tag>{String(v)}</Tag> : "—"),
            },
          ]}
        />
      </QueryState>

      <Drawer
        title={`RAG / Feedback #${drawerId ?? ""}`}
        open={drawerId != null}
        onClose={() => setDrawerId(null)}
        size={720}
      >
        {detailQ.isLoading ? (
          <Typography.Text type="secondary">불러오는 중…</Typography.Text>
        ) : detailQ.isError ? (
          <Alert
            type="error"
            showIcon
            title="상세 조회 실패"
            description={toApiError(detailQ.error).message}
          />
        ) : (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Typography.Text type="secondary">
              후보 → 유사사례 → 1.7B 분석 → 2B 판단 → 4B 검토(optional) → 실제
              결과 → Feedback
            </Typography.Text>
            <JsonCollapse title="현재 후보" data={flow?.candidate} />
            <JsonCollapse title="RAG 유사사례" data={flow?.rag_examples} />
            <JsonCollapse title="1.7B Analysis" data={flow?.analysis_1_7b} />
            <JsonCollapse title="2B Trading SHADOW" data={flow?.trading_2b} />
            <JsonCollapse title="4B Teacher (optional)" data={flow?.teacher_4b} />
            <JsonCollapse title="실제 결과" data={flow?.actual_outcome} />
            <JsonCollapse title="Feedback" data={flow?.feedback} />
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="Dataset tier">
                {dash(flow?.dataset_tier)}
              </Descriptions.Item>
            </Descriptions>
          </Space>
        )}
      </Drawer>
    </Space>
  );
}

export const upbitResearchDetailTabs = {
  CleanForwardTab,
  MarketTab: () => <PaginatedContextTab kind="market" />,
  AssetTab: () => <PaginatedContextTab kind="asset" />,
  NewsTab: () => <PaginatedContextTab kind="news" />,
  LlmTab: () => <PaginatedContextTab kind="llm" />,
  ExperimentsTab,
  RagFeedbackTab,
};
