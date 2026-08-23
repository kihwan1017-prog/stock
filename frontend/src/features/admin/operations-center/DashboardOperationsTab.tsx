"use client";

import {
  Alert,
  Card,
  Collapse,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";

import { adminRoutes } from "@/config/routes";
import {
  entryBlockReasonShortKo,
} from "@/features/admin/autotrading/entryBlockReasonKo";
import { slotStatusLabelKo } from "@/features/admin/autotrading/slotStatusLabels";
import {
  toneFromBoolOnOff,
  toneFromReadiness,
  toneToAntdColor,
} from "@/features/admin/autotrading/statusTone";

import { formatKrw, type BrokerFilter } from "./autoTradingPerformanceHelpers";
import { EntryBlockerChart } from "./dashboardCharts";
import { rec } from "./dashboardBrokerOpsUtils";
import { useAutotradingPerformanceQuery } from "./useAutotradingPerformanceQuery";
import { useDashboardBrokerOps } from "./useDashboardBrokerOps";

type Props = {
  enabled: boolean;
  broker: BrokerFilter;
  refreshMs?: number;
  killActive?: boolean;
  systemInfra?: React.ReactNode;
};

function PipelineFlow({ pipeline }: { pipeline: Record<string, unknown> }) {
  const stages = [
    { label: "후보 슬롯", value: `${pipeline.slots_occupied ?? 0} / ${pipeline.slots_capacity ?? "—"}` },
    { label: "Entry 평가", value: pipeline.entry_evaluations ?? 0 },
    { label: "차단", value: pipeline.entry_blocked ?? 0 },
    { label: "AUTO 보유", value: pipeline.auto_open_positions ?? 0 },
    { label: "오늘 주문", value: pipeline.orders_today_auto ?? 0 },
    { label: "오늘 체결", value: pipeline.fills_today_auto ?? 0 },
  ];
  return (
    <Space wrap size={[8, 8]}>
      {stages.map((s, i) => (
        <span key={s.label}>
          <Tag>{s.label}: {String(s.value)}</Tag>
          {i < stages.length - 1 ? <Typography.Text type="secondary">→</Typography.Text> : null}
        </span>
      ))}
    </Space>
  );
}

export function DashboardOperationsTab({
  enabled,
  broker,
  refreshMs = 12_000,
  killActive = false,
  systemInfra,
}: Props) {
  const ops = useDashboardBrokerOps({
    enabled,
    detailed: enabled,
    refreshMs,
  });

  const opsInsightQ = useAutotradingPerformanceQuery({
    broker,
    period: "7D",
    enabled,
    includeOps: true,
    refreshMs: 60_000,
  });

  const insight = rec(rec(opsInsightQ.data).ops_insight);
  const pipeline = rec(insight.pipeline);
  const blockers = Array.isArray(insight.entry_blockers)
    ? (insight.entry_blockers as Record<string, unknown>[])
    : [];

  const showUpbit = broker === "ALL" || broker === "UPBIT";
  const showKiwoom = broker === "ALL" || broker === "KIWOOM";

  const statusRows = [];
  if (showUpbit) {
    const c = ops.upbitCard;
    statusRows.push({
      key: "UPBIT",
      broker: "UPBIT",
      live: c.liveOn == null ? "—" : c.liveOn ? "ON" : "OFF",
      arm: c.armOn == null ? "—" : c.armOn ? "ON" : "OFF",
      runtime: c.runtime ?? "—",
      worker: c.worker ?? "—",
      runner: c.runner ?? "—",
      exit: c.exitMonitor ?? "—",
      feed: c.feed ?? "—",
      evaluator: c.evaluator ?? "—",
      readiness: c.readiness ?? "—",
      blocker: c.blocker ?? "—",
      unattended: c.unattended ?? "—",
    });
  }
  if (showKiwoom) {
    const c = ops.kiwoomCard;
    statusRows.push({
      key: "KIWOOM",
      broker: "KIWOOM",
      live: c.liveOn == null ? "—" : c.liveOn ? "ON" : "OFF",
      arm: c.armOn == null ? "—" : c.armOn ? "ON" : "OFF",
      runtime: c.runtime ?? "—",
      worker: "—",
      runner: "—",
      exit: "—",
      feed: "—",
      evaluator: "—",
      readiness: c.readiness ?? "—",
      blocker: c.blocker ?? "—",
      unattended: "—",
    });
  }

  const openPositions = ops.autoOpenPositions.filter((p) => {
    if (broker === "ALL") return true;
    return String(rec(p).broker_code).toUpperCase() === broker;
  });

  const blockerList = [...ops.blockers];
  if (killActive) blockerList.push("Kill Switch 활성");

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card size="small" title="안전 · Blocker">
        {blockerList.length === 0 ? (
          <Typography.Text>✅ 현재 안전 차단 없음</Typography.Text>
        ) : (
          <Space wrap>
            {blockerList.map((b) => (
              <Tag key={b} color="warning">
                ⚠ {b}
              </Tag>
            ))}
          </Space>
        )}
      </Card>

      <Card size="small" title="브로커 운영 상태">
        <Table
          size="small"
          pagination={false}
          scroll={{ x: 1100 }}
          dataSource={statusRows}
          columns={[
            { title: "Broker", dataIndex: "broker", width: 72 },
            {
              title: "실거래(LIVE)",
              dataIndex: "live",
              render: (v) => (
                <Tag color={toneToAntdColor(toneFromBoolOnOff(v === "ON"))}>
                  {v === "ON" ? "켜짐" : v === "OFF" ? "꺼짐" : v}
                </Tag>
              ),
            },
            {
              title: "자동주문 승인(ARM)",
              dataIndex: "arm",
              render: (v) => (
                <Tag color={toneToAntdColor(toneFromBoolOnOff(v === "ON"))}>
                  {v === "ON" ? "켜짐" : v === "OFF" ? "꺼짐" : v}
                </Tag>
              ),
            },
            { title: "24시간", dataIndex: "unattended", width: 80 },
            { title: "런타임", dataIndex: "runtime" },
            { title: "워커", dataIndex: "worker" },
            { title: "실행기", dataIndex: "runner" },
            { title: "청산", dataIndex: "exit" },
            { title: "시세", dataIndex: "feed" },
            { title: "평가기", dataIndex: "evaluator" },
            {
              title: "준비상태",
              dataIndex: "readiness",
              render: (v) => (
                <Tag color={toneToAntdColor(toneFromReadiness(String(v)))}>
                  {v}
                </Tag>
              ),
            },
            {
              title: "차단 요인",
              dataIndex: "blocker",
              ellipsis: true,
              render: (v) =>
                v && v !== "—" ? <Tag color="warning">{v}</Tag> : "—",
            },
          ]}
        />
      </Card>

      {(broker === "ALL" || broker === "UPBIT") && Object.keys(pipeline).length > 0 ? (
        <Card size="small" title="자동매매 처리 현황 (업비트)">
          <PipelineFlow pipeline={pipeline} />
          <Typography.Text type="secondary" style={{ display: "block", marginTop: 8, fontSize: 12 }}>
            스캐너 → 후보 → 슬롯 → 매수 평가 → 주문 → 체결 → 포지션 → 청산 → 손익(PnL)
          </Typography.Text>
        </Card>
      ) : null}

      {(broker === "KIWOOM" || broker === "ALL") && showKiwoom ? (
        <Alert
          type="info"
          showIcon
          title="키움 Pipeline"
          description="키움 Pipeline 상세 telemetry 미지원 — 성과·운영 상태만 표시됩니다."
        />
      ) : null}

      {blockers.length > 0 ? (
        <Card size="small" title="Entry 차단 원인 (최근 평가)">
          <EntryBlockerChart blockers={blockers} />
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            {String(insight.blocker_note ?? "")}
          </Typography.Text>
        </Card>
      ) : null}

      <Card size="small" title="현재 AUTO 포지션">
        {openPositions.length ? (
          <Table
            size="small"
            pagination={false}
            rowKey={(r) => `${rec(r).broker_code}-${rec(r).symbol}`}
            dataSource={openPositions.map((r) => rec(r))}
            columns={[
              { title: "Broker", dataIndex: "broker_code" },
              { title: "Symbol", dataIndex: "symbol" },
              { title: "Qty", dataIndex: "quantity" },
              { title: "Avg", dataIndex: "average_price" },
              {
                title: "평가손익",
                dataIndex: "unrealized_pnl",
                render: (v) => formatKrw(Number(v)),
              },
            ]}
          />
        ) : (
          <Typography.Text type="secondary">OPEN AUTO 포지션 없음</Typography.Text>
        )}
      </Card>

      {(broker === "ALL" || broker === "UPBIT") ? (
        <Card
          size="small"
          title={`후보 슬롯 ${ops.slotsOccupied} / ${ops.slotCapacity || "—"}`}
          extra={<Link href={adminRoutes.autotradingUpbit}>상세 →</Link>}
        >
          <Collapse
            items={[
              {
                key: "slots",
                label: "상세 보기",
                children: ops.slots.length ? (
                  <Table
                    size="small"
                    pagination={false}
                    rowKey={(r) => String(rec(r).slot_no)}
                    dataSource={ops.slots.map((s) => rec(s))}
                    columns={[
                      { title: "슬롯", dataIndex: "slot_no", width: 48 },
                      { title: "종목", dataIndex: "symbol" },
                      { title: "점수", dataIndex: "score" },
                      { title: "AI 판단", dataIndex: "ai_recommendation" },
                      {
                        title: "상태",
                        dataIndex: "status",
                        render: (v) => slotStatusLabelKo(String(v)),
                      },
                      {
                        title: "차단",
                        dataIndex: "last_entry_block_reason",
                        render: (v, row) => {
                          const reason =
                            v ?? rec(row).entry_block_reason ?? "";
                          return reason
                            ? entryBlockReasonShortKo(String(reason))
                            : "—";
                        },
                      },
                    ]}
                  />
                ) : (
                  <Typography.Text type="secondary">슬롯 없음</Typography.Text>
                ),
              },
            ]}
          />
        </Card>
      ) : null}

      <Card size="small" title="계좌 전체 손익 (Safety)">
        <Alert
          type="info"
          showIcon
          title="MANUAL 평가손익"
          description={`${formatKrw(ops.manualUnrealized)} — AUTO 성과와 분리`}
        />
      </Card>

      {systemInfra ? (
        <Collapse
          items={[
            { key: "infra", label: "시스템·인프라 상세", children: systemInfra },
          ]}
        />
      ) : null}
    </Space>
  );
}
