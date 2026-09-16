"use client";

/**
 * 연구 데이터 수집 현황 — CLEAN / Context / News / LLM / Scheduler.
 * READ ONLY. REAL/LIVE/주문·정책 mutate 없음.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Collapse,
  Progress,
  Row,
  Space,
  Statistic,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord, cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

function statusColor(status: unknown): string {
  const s = String(status ?? "");
  if (s === "OK" || s === "COLLECTING") return "success";
  if (s === "WAITING") return "processing";
  if (s === "PARTIAL" || s === "STALE") return "warning";
  if (s === "ERROR" || s === "DISABLED") return "error";
  return "default";
}

function formatClock(iso: unknown): string {
  if (iso == null || iso === "") return "—";
  const s = String(iso);
  const m = s.match(/T(\d{2}:\d{2}(?::\d{2})?)/);
  if (m) return m[1].slice(0, 5);
  try {
    const d = new Date(s);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleTimeString("ko-KR", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: "Asia/Seoul",
      });
    }
  } catch {
    /* ignore */
  }
  return s;
}

function TipLabel({
  label,
  tip,
}: {
  label: string;
  tip?: string;
}) {
  if (!tip) return <span>{label}</span>;
  return (
    <Tooltip title={tip}>
      <span style={{ borderBottom: "1px dashed rgba(0,0,0,0.25)", cursor: "help" }}>
        {label}
      </span>
    </Tooltip>
  );
}

function SourceLine({
  label,
  tip,
  status,
  statusKo,
  detail,
}: {
  label: string;
  tip?: string;
  status: unknown;
  statusKo: unknown;
  detail: string;
}) {
  return (
    <div>
      <TipLabel label={label} tip={tip} />{" "}
      <Tag color={statusColor(status)}>● {cell(statusKo ?? "—")}</Tag>
      <Typography.Text type="secondary"> · {detail}</Typography.Text>
    </div>
  );
}

export function UpbitResearchCollectionStatusPanel({
  ubaId,
}: {
  ubaId: number;
}) {
  const q = useQuery({
    queryKey: queryKeys.admin.upbitResearchCollectionStatus(ubaId),
    queryFn: () => adminApi.getAdminUbaResearchCollectionStatus(ubaId),
    enabled: ubaId > 0,
    refetchInterval: 45_000,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  const data = asRecord(q.data) ?? {};
  const clean = asRecord(data.clean_forward) ?? {};
  const reference = asRecord(data.reference) ?? {};
  const market = asRecord(data.market_context) ?? {};
  const asset = asRecord(data.asset_context) ?? {};
  const news = asRecord(data.news) ?? {};
  const llm = asRecord(data.llm) ?? {};
  const experiment = asRecord(data.experiment) ?? {};
  const scheduler = asRecord(data.scheduler) ?? {};
  const tips = asRecord(data.tooltips_ko) ?? {};
  const labels = asRecord(data.labels_ko) ?? {};

  const cleanCount = Number(clean.count ?? 0);
  const target500 = Number(clean.target_primary ?? 500);
  const target1000 = Number(clean.target_recommended ?? 1000);
  const pct500 = Math.min(
    100,
    Number(clean.progress_primary_pct ?? (target500 ? (cleanCount / target500) * 100 : 0)),
  );
  const pct1000 = Math.min(
    100,
    Number(
      clean.progress_recommended_pct ??
        (target1000 ? (cleanCount / target1000) * 100 : 0),
    ),
  );

  const overallKo = String(data.overall_status_ko ?? data.overall_status ?? "—");
  const overallStatus = String(data.overall_status ?? "");
  const autoCollect = String(scheduler.auto_collect ?? "");
  const autoCollectKo = String(
    scheduler.auto_collect_ko ??
      (autoCollect === "ON" ? "자동수집 ON" : autoCollect || "—"),
  );
  const schedulerRunning = Boolean(scheduler.running);

  const summaryExtras = (
    <Space wrap size={4}>
      <Button size="small" loading={q.isFetching} onClick={() => void q.refetch()}>
        새로고침
      </Button>
      <Tag color={statusColor(overallStatus)}>● {overallKo}</Tag>
    </Space>
  );

  const headerMeta = !q.error ? (
    <Space orientation="vertical" size={2} style={{ width: "100%", marginBottom: 12 }}>
      <Space wrap size={8}>
        <Typography.Text>
          상태 <Tag color={statusColor(overallStatus)}>● {overallKo}</Tag>
        </Typography.Text>
        <Typography.Text>
          자동수집{" "}
          <Tag color={autoCollect === "ON" ? "success" : "default"}>
            {autoCollectKo}
          </Tag>
        </Typography.Text>
        <Typography.Text>
          Scheduler{" "}
          <Tag color={schedulerRunning ? "success" : "warning"}>
            {schedulerRunning ? "정상" : "확인 필요"}
          </Tag>
        </Typography.Text>
      </Space>
      <Typography.Text type="secondary">
        마지막 실행 {formatClock(scheduler.last_tick_at ?? data.last_collected_at)}
        {" · "}
        다음 실행{" "}
        {formatClock(
          market.next_run_at ??
            (asRecord(scheduler.market) ?? {}).next_run_at ??
            null,
        )}
      </Typography.Text>
    </Space>
  ) : null;

  const detailTabs = (
    <Tabs
      size="small"
      items={[
        {
          key: "overview",
          label: "수집 현황",
          children: (
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              <Typography.Text type="secondary">
                표본 단계: {cell(clean.sample_stage_ko)} —{" "}
                {cell(clean.sample_stage_desc_ko)}
              </Typography.Text>
              <Space wrap>
                <Tag>정상 신규(CLEAN): {cleanCount}</Tag>
                <Tag>
                  오늘 +{cell(clean.today_new ?? 0)} · 1h +
                  {cell(clean.hour_new ?? 0)} · 24h +{cell(clean.day_new ?? 0)}
                </Tag>
                <Tooltip title={String(tips.legacy ?? "")}>
                  <Tag color="default">
                    이전 연구 {cell(reference.legacy_count)} ·{" "}
                    {cell(reference.label_ko)}
                  </Tag>
                </Tooltip>
                <Tag color="default">
                  보완 {cell(reference.backfill_count)} · 참고용
                </Tag>
              </Space>
              <Typography.Text type="secondary">
                마지막 수집 {formatClock(data.last_collected_at)} · 마지막 CLEAN
                신규 {formatClock(clean.last_new_at)}
              </Typography.Text>
              <Typography.Text type="secondary">
                <TipLabel
                  label="CLEAN Forward"
                  tip={String(tips.clean_forward ?? "")}
                />
                : {cell(clean.trigger_ko ?? "Scanner 신규 후보 발생 시 자동 축적")}
              </Typography.Text>
            </Space>
          ),
        },
        {
          key: "clean",
          label: "CLEAN 검증",
          children: (
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              <div>
                <TipLabel
                  label={`정상 신규 검증 ${cleanCount} / ${target500.toLocaleString()}`}
                  tip={String(tips.clean_forward ?? "")}
                />
                <Progress percent={Number(pct500.toFixed(1))} size="small" />
              </div>
              <div>
                <TipLabel
                  label={`권장 검토 ${cleanCount} / ${target1000.toLocaleString()}`}
                  tip={String(tips.target_1000 ?? "")}
                />
                <Progress percent={Number(pct1000.toFixed(1))} size="small" />
              </div>
              <Alert
                type="info"
                showIcon
                title={cell(clean.sample_stage_ko)}
                description={cell(clean.sample_stage_desc_ko)}
              />
              {String(clean.status) === "WAITING" ? (
                <Alert
                  type="info"
                  showIcon
                  title="신규 후보 대기 중"
                  description={String(tips.waiting ?? "")}
                />
              ) : null}
            </Space>
          ),
        },
        {
          key: "market-news",
          label: "시장·뉴스",
          children: (
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              <SourceLine
                label="시장"
                tip={String(tips.market_interval ?? "")}
                status={market.status}
                statusKo={market.status_ko}
                detail={`${cell(market.rows)}건 · ${formatClock(market.last_collected_at)}`}
              />
              <SourceLine
                label="종목"
                tip={String(tips.asset_interval ?? "")}
                status={asset.status}
                statusKo={asset.status_ko}
                detail={`${cell(asset.symbols)}종목 · ${formatClock(asset.last_collected_at)}`}
              />
              <SourceLine
                label="뉴스"
                tip={String(tips.news_interval ?? "")}
                status={news.status}
                statusKo={news.status_ko}
                detail={`${cell(news.recent_count)}건(24h) · ${formatClock(news.last_collected_at)}`}
              />
              <SourceLine
                label="LLM"
                tip={String(tips.llm ?? "")}
                status={llm.status}
                statusKo={llm.status_ko}
                detail={String(llm.note_ko ?? "후보 발생 시 실행")}
              />
            </Space>
          ),
        },
        {
          key: "llm",
          label: "LLM 분석",
          children: (
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              <Tooltip title={String(tips.llm ?? "")}>
                <Tag color={statusColor(llm.status)}>
                  ● {cell(llm.status_ko ?? llm.status)}
                </Tag>
              </Tooltip>
              <Space wrap>
                <Tag>오늘 분석 {cell(llm.today_count)}</Tag>
                <Tag>매수 허용 {cell(llm.allow)}</Tag>
                <Tag>대기 {cell(llm.hold)}</Tag>
                <Tag>비중 축소 {cell(llm.reduce)}</Tag>
                <Tag>실패 {cell(llm.failed)}</Tag>
                <Tag>누적 {cell(llm.total)}</Tag>
              </Space>
              <Typography.Text type="secondary">
                마지막 분석 {formatClock(llm.last_analysis_at)}
              </Typography.Text>
            </Space>
          ),
        },
        {
          key: "experiment",
          label: "필터 실험",
          children: (
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              <Space wrap>
                <Tag>Baseline Net {cell(experiment.baseline_net)}</Tag>
                <Tag>PF {cell(experiment.baseline_pf)}</Tag>
                <Tag>
                  Early Dump {cell(experiment.baseline_early_dump_rate)}
                </Tag>
              </Space>
              <div>
                현재 진단 1위:{" "}
                <Typography.Text strong>
                  {cell(experiment.best_candidate_label_ko ?? "—")}
                </Typography.Text>{" "}
                {experiment.provisional_badge ? (
                  <Badge count="잠정" style={{ backgroundColor: "#faad14" }} />
                ) : null}
              </div>
              {experiment.sample_warning ? (
                <Alert
                  type="warning"
                  showIcon
                  title={cell(experiment.sample_warning_ko ?? "표본 부족 · 연구용")}
                />
              ) : null}
              <Typography.Text type="secondary">
                REAL 승격 권장: 아니오 · E1~E8 상세는 연구 리포트 참고
              </Typography.Text>
            </Space>
          ),
        },
        {
          key: "dev",
          label: "개발자",
          children: (
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              API:{" "}
              <Typography.Text code>
                GET /api/v1/admin/autotrading/uba/{ubaId}/research/collection-status
              </Typography.Text>
            </Typography.Paragraph>
          ),
        },
      ]}
    />
  );

  return (
    <Card
      size="small"
      title="연구 데이터 수집 현황"
      extra={summaryExtras}
      loading={q.isLoading}
    >
      {q.error ? (
        <Alert
          type="error"
          showIcon
          title={toApiError(q.error).message}
          description="연구 수집 현황 API를 불러오지 못했습니다. 백엔드 라우트·재시작을 확인하세요."
          style={{ marginBottom: 12 }}
        />
      ) : null}

      {headerMeta}

      <Row gutter={[12, 12]}>
        <Col xs={12} sm={8} md={5}>
          <Statistic
            title={
              <TipLabel
                label={String(labels.clean_forward ?? "정상 신규 검증")}
                tip={String(tips.clean_forward ?? "")}
              />
            }
            value={cleanCount}
            suffix={`/ ${target500.toLocaleString()}`}
            styles={{ content: { fontSize: 18 } }}
          />
          <Progress percent={Number(pct500.toFixed(1))} size="small" showInfo />
        </Col>
        <Col xs={12} sm={8} md={5}>
          <Statistic
            title={
              <TipLabel
                label="권장 검토"
                tip={String(tips.target_1000 ?? "")}
              />
            }
            value={cleanCount}
            suffix={`/ ${target1000.toLocaleString()}`}
            styles={{ content: { fontSize: 18 } }}
          />
          <Progress percent={Number(pct1000.toFixed(1))} size="small" showInfo />
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Statistic
            title="오늘 신규"
            value={Number(clean.today_new ?? 0)}
            prefix="+"
            styles={{ content: { fontSize: 18 } }}
          />
        </Col>
        <Col xs={24} sm={12} md={10}>
          <Typography.Text type="secondary">소스 상태</Typography.Text>
          <Space orientation="vertical" size={2} style={{ width: "100%" }}>
            <SourceLine
              label="시장"
              tip={String(tips.market_interval ?? "")}
              status={market.status}
              statusKo={market.status_ko}
              detail={`${cell(market.rows)}건 · ${formatClock(market.last_collected_at)}`}
            />
            <SourceLine
              label="종목"
              tip={String(tips.asset_interval ?? "")}
              status={asset.status}
              statusKo={asset.status_ko}
              detail={`${cell(asset.symbols)}종목 · ${formatClock(asset.last_collected_at)}`}
            />
            <SourceLine
              label="뉴스"
              tip={String(tips.news_interval ?? "")}
              status={news.status}
              statusKo={news.status_ko}
              detail={`${cell(news.recent_count)}건 · ${formatClock(news.last_collected_at)}`}
            />
            <SourceLine
              label="LLM"
              tip={String(tips.llm ?? "")}
              status={llm.status}
              statusKo={llm.status_ko}
              detail={String(llm.trigger_ko ?? "후보 발생 시")}
            />
          </Space>
        </Col>
      </Row>

      <Collapse
        size="small"
        style={{ marginTop: 12 }}
        items={[
          {
            key: "details",
            label: "세부 현황 펼치기",
            children: detailTabs,
          },
        ]}
      />
    </Card>
  );
}
