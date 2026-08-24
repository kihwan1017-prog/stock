"use client";

/**
 * Upbit Dual LLM panel — ANALYSIS + TRADING SHADOW 현황.
 * Ant Design 6: Alert.title, Table named import (avoid deprecated Statistic styles).
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  Descriptions,
  Empty,
  Row,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

function dash(v: unknown): string {
  if (v == null || v === "") return "—";
  if (typeof v === "number" && !Number.isFinite(v)) return "—";
  return String(v);
}

function safeRows(data: unknown): Record<string, unknown>[] {
  const rec = asRecord(data);
  const items = rec?.items;
  return Array.isArray(items)
    ? items.filter(
        (x): x is Record<string, unknown> =>
          typeof x === "object" && x !== null,
      )
    : [];
}

function Tip({ label, tip }: { label: string; tip: string }) {
  return (
    <Tooltip title={tip}>
      <span
        style={{
          borderBottom: "1px dashed rgba(0,0,0,0.25)",
          cursor: "help",
        }}
      >
        {label}
      </span>
    </Tooltip>
  );
}

export function UpbitDualLlmPanel() {
  const statusQ = useQuery({
    queryKey: queryKeys.admin.upbitDualLlmStatus(),
    queryFn: () => adminApi.getAdminUpbitDualLlmStatus(),
    refetchInterval: 60_000,
  });
  const recentQ = useQuery({
    queryKey: queryKeys.admin.upbitDualLlmRecent({ limit: 20 }),
    queryFn: () => adminApi.getAdminUpbitDualLlmRecent({ limit: 20 }),
    refetchInterval: 60_000,
  });
  const cmpQ = useQuery({
    queryKey: queryKeys.admin.upbitDualLlmComparison(),
    queryFn: () => adminApi.getAdminUpbitDualLlmComparison(),
    refetchInterval: 120_000,
  });

  const st = asRecord(statusQ.data);
  const analysis = asRecord(st?.analysis);
  const trading = asRecord(st?.trading_shadow);
  const teacher = asRecord(st?.teacher);
  const fb = asRecord(st?.feedback_metrics);
  const rag = asRecord(st?.rag);
  const dataset = asRecord(st?.dataset);
  const cmp = asRecord(cmpQ.data);
  const heur = asRecord(cmp?.current_heuristic);
  const llmArm = asRecord(cmp?.trading_llm_shadow);
  const rows = safeRows(recentQ.data);

  if (statusQ.isLoading) {
    return <Typography.Text type="secondary">Dual LLM 로딩…</Typography.Text>;
  }
  if (statusQ.isError) {
    return (
      <Alert
        type="error"
        showIcon
        title="Dual LLM 상태 조회 실패"
        description={toApiError(statusQ.error).message}
      />
    );
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="연구·SHADOW 전용"
        description="Trading LLM은 SHADOW만 생성합니다. REAL 주문·LIVE/ARM·Risk·Slot에 영향을 주지 않습니다. 보호성 청산은 LLM을 기다리지 않습니다."
      />

      <Row gutter={[12, 12]}>
        <Col xs={24} md={8}>
          <Card size="small" title="분석 LLM">
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="모델">
                <Tag color="blue">{dash(st?.ANALYSIS_LLM_MODEL)}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="호출/성공">
                {dash(analysis?.calls)} / {dash(analysis?.ok)}
              </Descriptions.Item>
              <Descriptions.Item label="timeout / 오류">
                {dash(analysis?.timeouts)} / {dash(analysis?.errors)}
              </Descriptions.Item>
              <Descriptions.Item label="캐시 hit">
                {dash(analysis?.cache_hits)}
              </Descriptions.Item>
              <Descriptions.Item
                label={
                  <Tip label="median latency" tip="프로세스 내 최근 호출 중앙값" />
                }
              >
                {analysis?.median_latency_ms != null
                  ? `${Number(analysis.median_latency_ms).toFixed(0)} ms`
                  : "—"}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small" title="매매 판단 LLM">
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="모델">
                <Tag color="purple">{dash(st?.TRADING_LLM_MODEL)}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="모드">
                <Tag color="warning">SHADOW</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="호출/성공">
                {dash(trading?.calls)} / {dash(trading?.ok)}
              </Descriptions.Item>
              <Descriptions.Item label="timeout / 오류">
                {dash(trading?.timeouts)} / {dash(trading?.errors)}
              </Descriptions.Item>
              <Descriptions.Item label="median latency">
                {trading?.median_latency_ms != null
                  ? `${Number(trading.median_latency_ms).toFixed(0)} ms`
                  : "—"}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small" title="Teacher (선택 검증)">
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="모델">
                <Tag>{dash(st?.TEACHER_LLM_MODEL || st?.REFERENCE_MODEL)}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="역할">
                <Tag>선택 검증</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="호출/성공">
                {dash(teacher?.calls)} / {dash(teacher?.ok)}
              </Descriptions.Item>
              <Descriptions.Item label="review rate">
                {teacher?.review_rate != null
                  ? String(teacher.review_rate)
                  : "—"}
              </Descriptions.Item>
              <Descriptions.Item label="priority">
                LOW (Trading 대기 금지)
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
      </Row>

      <Card size="small" title="RAG / Feedback KPI">
        <Descriptions size="small" column={3}>
          <Descriptions.Item label="ALLOW / HOLD / REDUCE">
            {dash(fb?.ALLOW)} / {dash(fb?.HOLD)} / {dash(fb?.REDUCE)}
          </Descriptions.Item>
          <Descriptions.Item label="Early Dump detection">
            {dash(fb?.EARLY_DUMP_DETECTION_RATE)}
          </Descriptions.Item>
          <Descriptions.Item label="Avoided loser">
            {dash(fb?.avoided_losers)}
          </Descriptions.Item>
          <Descriptions.Item label="Missed winner">
            {dash(fb?.missed_winners)}
          </Descriptions.Item>
          <Descriptions.Item label="Net benefit">
            {dash(fb?.NET_FILTER_BENEFIT)}
          </Descriptions.Item>
          <Descriptions.Item label="Fee churn avoid">
            {dash(fb?.FEE_CHURN_AVOIDANCE)}
          </Descriptions.Item>
          <Descriptions.Item label="RAG hit rate">
            {dash(rag?.hit_rate)}
          </Descriptions.Item>
          <Descriptions.Item label="Avg similar cases">
            {dash(rag?.average_similar_cases)}
          </Descriptions.Item>
          <Descriptions.Item label="GOLD / SILVER">
            {dash(dataset?.GOLD)} / {dash(dataset?.SILVER)}
          </Descriptions.Item>
          <Descriptions.Item label="SAMPLE_STAGE">
            <Tag>{dash(st?.SAMPLE_STAGE)}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="LoRA training">
            <Tag>NO</Tag>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card size="small" title="승격 게이트 (자동 승격 없음)">
        <Descriptions size="small" column={2}>
          <Descriptions.Item label="CLEAN 표본">
            {dash(st?.clean_sample_count)}
          </Descriptions.Item>
          <Descriptions.Item label="상태">
            <Tag>{dash(st?.promotion_status)}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="설명" span={2}>
            {dash(st?.promotion_status_ko)}
          </Descriptions.Item>
          <Descriptions.Item label="Dual 저장 row">
            {dash(st?.dual_llm_rows_stored)}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        size="small"
        title={
          <Tip
            label="기존 판단 vs LLM Shadow"
            tip="CURRENT_HEURISTIC과 TRADING_LLM_SHADOW의 CLEAN Forward proxy 비교"
          />
        }
      >
        {cmpQ.isLoading ? (
          <Typography.Text type="secondary">비교 로딩…</Typography.Text>
        ) : cmpQ.isError ? (
          <Alert
            type="error"
            showIcon
            title="비교 조회 실패"
            description={toApiError(cmpQ.error).message}
          />
        ) : !cmp?.CURRENT_HEURISTIC_VS_LLM_SHADOW_AVAILABLE ? (
          <Empty description="Dual LLM SHADOW 표본이 아직 없습니다. 신규 Scanner 후보 발생 시 축적됩니다." />
        ) : (
          <Table
            size="small"
            pagination={false}
            rowKey={(r) => String(r.key)}
            dataSource={[
              {
                key: "heuristic",
                arm: "CURRENT_HEURISTIC",
                accepted: heur?.accepted,
                allow_precision: heur?.allow_precision,
                avoided_loss_krw: heur?.avoided_loss_krw,
                missed_winner_krw: heur?.missed_winner_krw,
                net_pnl: heur?.net_pnl,
                pf_proxy: heur?.pf_proxy,
                early_dump_rate: heur?.early_dump_rate,
              },
              {
                key: "llm",
                arm: "TRADING_LLM_SHADOW",
                accepted: llmArm?.accepted,
                allow_precision: llmArm?.allow_precision,
                avoided_loss_krw: llmArm?.avoided_loss_krw,
                missed_winner_krw: llmArm?.missed_winner_krw,
                net_pnl: llmArm?.net_pnl,
                pf_proxy: llmArm?.pf_proxy,
                early_dump_rate: llmArm?.early_dump_rate,
              },
            ]}
            columns={[
              { title: "Arm", dataIndex: "arm", render: dash },
              { title: "Accepted", dataIndex: "accepted", render: dash },
              {
                title: "ALLOW precision",
                dataIndex: "allow_precision",
                render: dash,
              },
              {
                title: "Avoided loss",
                dataIndex: "avoided_loss_krw",
                render: dash,
              },
              {
                title: "Missed winner",
                dataIndex: "missed_winner_krw",
                render: dash,
              },
              { title: "Net", dataIndex: "net_pnl", render: dash },
              { title: "PF proxy", dataIndex: "pf_proxy", render: dash },
              {
                title: "Early dump rate",
                dataIndex: "early_dump_rate",
                render: dash,
              },
            ]}
          />
        )}
        <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
          Dual 표본 {dash(cmp?.dual_shadow_sample_count)} · net benefit proxy{" "}
          {dash(cmp?.net_benefit_proxy)} · auto_promote=NO
        </Typography.Paragraph>
      </Card>

      <Card size="small" title="최근 Dual LLM 분석">
        {recentQ.isLoading ? (
          <Typography.Text type="secondary">최근 목록 로딩…</Typography.Text>
        ) : recentQ.isError ? (
          <Alert
            type="error"
            showIcon
            title="최근 목록 실패"
            description={toApiError(recentQ.error).message}
          />
        ) : rows.length === 0 ? (
          <Empty description="아직 저장된 분석이 없습니다" />
        ) : (
          <Table
            size="small"
            rowKey={(r) => String(r.analysis_id)}
            dataSource={rows}
            scroll={{ x: 1100 }}
            pagination={{ pageSize: 10 }}
            columns={[
              { title: "ID", dataIndex: "analysis_id", width: 70 },
              { title: "종목", dataIndex: "symbol", render: dash },
              {
                title: "Heuristic",
                dataIndex: "heuristic_recommendation",
                render: (v) => (v ? <Tag>{String(v)}</Tag> : "—"),
              },
              {
                title: "LLM Shadow",
                dataIndex: "trading_recommendation",
                render: (v) => (v ? <Tag color="purple">{String(v)}</Tag> : "—"),
              },
              {
                title: "Entry Q",
                dataIndex: "entry_quality_score",
                render: dash,
              },
              {
                title: "Early dump",
                dataIndex: "early_dump_risk",
                render: dash,
              },
              {
                title: "신뢰도",
                dataIndex: "trading_confidence",
                render: dash,
              },
              {
                title: "A latency",
                dataIndex: "analysis_latency_ms",
                render: dash,
              },
              {
                title: "T latency",
                dataIndex: "trading_latency_ms",
                render: dash,
              },
              {
                title: "일치",
                dataIndex: "agree",
                render: (v) =>
                  v === true ? (
                    <Tag color="success">예</Tag>
                  ) : v === false ? (
                    <Tag>아니오</Tag>
                  ) : (
                    "—"
                  ),
              },
            ]}
          />
        )}
      </Card>
    </Space>
  );
}
