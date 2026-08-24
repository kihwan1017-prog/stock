"use client";

/**
 * Kiwoom Dual LLM panel — ANALYSIS + TRADING SHADOW (market-isolated).
 * Ant Design 6: Alert.title only.
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

export function KiwoomDualLlmPanel() {
  const statusQ = useQuery({
    queryKey: queryKeys.admin.kiwoomDualLlmStatus(),
    queryFn: () => adminApi.getAdminKiwoomDualLlmStatus(),
    refetchInterval: 60_000,
  });
  const recentQ = useQuery({
    queryKey: queryKeys.admin.kiwoomDualLlmRecent({ limit: 20 }),
    queryFn: () => adminApi.getAdminKiwoomDualLlmRecent({ limit: 20 }),
    refetchInterval: 60_000,
  });

  const st = asRecord(statusQ.data);
  const analysis = asRecord(st?.analysis);
  const trading = asRecord(st?.trading_shadow);
  const teacher = asRecord(st?.teacher);
  const fb = asRecord(st?.feedback_metrics);
  const dataset = asRecord(st?.dataset);
  const rows = safeRows(recentQ.data);

  if (statusQ.isLoading) {
    return <Typography.Text type="secondary">Kiwoom Dual LLM 로딩…</Typography.Text>;
  }
  if (statusQ.isError) {
    return (
      <Alert
        type="error"
        showIcon
        title="Kiwoom Dual LLM 상태 조회 실패"
        description={toApiError(statusQ.error).message}
      />
    );
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="KIWOOM 연구·SHADOW 전용"
        description="MA REAL 판단과 분리됩니다. Trading LLM은 SHADOW만 기록하며 REAL 주문·LIVE/ARM·Risk에 영향이 없습니다. UPBIT RAG와 혼합되지 않습니다."
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
              <Descriptions.Item label="median latency">
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
            </Descriptions>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small" title="Teacher (선택 검증)">
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="모델">
                <Tag>{dash(st?.TEACHER_LLM_MODEL)}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="호출">
                {dash(teacher?.calls)}
              </Descriptions.Item>
              <Descriptions.Item label="priority">LOW</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
      </Row>

      <Card size="small" title="KIWOOM RAG / Feedback KPI">
        <Descriptions size="small" column={3}>
          <Descriptions.Item label="CLEAN 표본">
            {dash(st?.clean_sample_count)}
          </Descriptions.Item>
          <Descriptions.Item label="SAMPLE_STAGE">
            <Tag>{dash(st?.SAMPLE_STAGE)}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Dual rows">
            {dash(st?.dual_llm_rows_stored)}
          </Descriptions.Item>
          <Descriptions.Item label="ALLOW/HOLD/REDUCE">
            {dash(fb?.ALLOW)} / {dash(fb?.HOLD)} / {dash(fb?.REDUCE)}
          </Descriptions.Item>
          <Descriptions.Item label="Early Dump detection">
            {dash(fb?.EARLY_DUMP_DETECTION_RATE)}
          </Descriptions.Item>
          <Descriptions.Item label="Net benefit">
            {dash(fb?.NET_FILTER_BENEFIT)}
          </Descriptions.Item>
          <Descriptions.Item label="GOLD / SILVER">
            {dash(dataset?.GOLD)} / {dash(dataset?.SILVER)}
          </Descriptions.Item>
          <Descriptions.Item
            label={
              <Tip
                label="Cross-market RAG"
                tip="UPBIT↔KIWOOM 혼합 금지 — 항상 0이어야 함"
              />
            }
          >
            0
          </Descriptions.Item>
          <Descriptions.Item label="LoRA training">
            <Tag>NO</Tag>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card size="small" title="최근 KIWOOM SHADOW">
        {recentQ.isLoading ? (
          <Typography.Text type="secondary">로딩…</Typography.Text>
        ) : rows.length === 0 ? (
          <Empty description="자연 MA ENTRY 평가 후 SHADOW row가 축적됩니다." />
        ) : (
          <Table
            size="small"
            pagination={false}
            rowKey={(r) => String(r.analysis_id)}
            dataSource={rows}
            columns={[
              { title: "ID", dataIndex: "analysis_id", width: 70, render: dash },
              { title: "Symbol", dataIndex: "symbol", render: dash },
              {
                title: "Trading",
                dataIndex: "trading_recommendation",
                render: dash,
              },
              {
                title: "Event risk",
                dataIndex: "event_risk",
                render: dash,
              },
              {
                title: "Disclosure",
                dataIndex: "disclosure_state",
                render: dash,
              },
              {
                title: "RAG",
                dataIndex: "rag_example_count",
                render: dash,
              },
              {
                title: "Tier",
                dataIndex: "dataset_tier",
                render: (v) => (v ? <Tag>{String(v)}</Tag> : "—"),
              },
            ]}
          />
        )}
      </Card>
    </Space>
  );
}
