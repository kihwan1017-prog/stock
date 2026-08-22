"use client";

import {
  Alert,
  Card,
  Collapse,
  Radio,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useMemo, useState } from "react";

import { adminRoutes } from "@/config/routes";
import {
  entryBlockReasonShortKo,
} from "@/features/admin/autotrading/entryBlockReasonKo";
import { slotStatusLabelKo } from "@/features/admin/autotrading/slotStatusLabels";
import {
  toneFromBoolOnOff,
  toneFromReadiness,
  toneFromRuntime,
  toneToAntdColor,
} from "@/features/admin/autotrading/statusTone";

import type { BrokerCardModel } from "./BrokerOpsCard";
import { rec } from "./dashboardBrokerOpsUtils";
import { useDashboardBrokerOps } from "./useDashboardBrokerOps";
import {
  formatKrw,
} from "./autoTradingPerformanceHelpers";

type BrokerFilter = "ALL" | "UPBIT" | "KIWOOM";

type Props = {
  enabled: boolean;
  refreshMs?: number;
  killActive?: boolean;
  systemInfra?: React.ReactNode;
};

function opsRow(card: BrokerCardModel) {
  return {
    key: card.broker,
    broker: card.broker,
    live: card.liveOn == null ? "—" : card.liveOn ? "ON" : "OFF",
    arm: card.armOn == null ? "—" : card.armOn ? "ON" : "OFF",
    runtime: card.runtime ?? "—",
    worker: card.worker ?? "—",
    runner: card.runner ?? "—",
    exit: card.exitMonitor ?? "—",
    feed: card.feed ?? "—",
    evaluator: card.evaluator ?? "—",
    readiness: card.readiness ?? "—",
    blocker: card.blocker ?? "—",
    unattended: card.unattended ?? "—",
  };
}

export function DashboardOperationsTab({
  enabled,
  refreshMs = 12_000,
  killActive = false,
  systemInfra,
}: Props) {
  const [brokerFilter, setBrokerFilter] = useState<BrokerFilter>("ALL");
  const [slotsOpen, setSlotsOpen] = useState(false);

  const ops = useDashboardBrokerOps({
    enabled,
    detailed: enabled,
    refreshMs,
  });

  const statusRows = useMemo(() => {
    const rows = [opsRow(ops.upbitCard), opsRow(ops.kiwoomCard)];
    if (brokerFilter === "ALL") return rows;
    return rows.filter((r) => r.broker === brokerFilter);
  }, [brokerFilter, ops.kiwoomCard, ops.upbitCard]);

  const openPositions = useMemo(() => {
    if (brokerFilter === "ALL") return ops.autoOpenPositions;
    return ops.autoOpenPositions.filter(
      (p) => String(rec(p).broker_code).toUpperCase() === brokerFilter,
    );
  }, [brokerFilter, ops.autoOpenPositions]);

  const blockers = useMemo(() => {
    const list: string[] = [];
    if (killActive) list.push("Kill Switch 활성");
    list.push(...ops.blockers);
    return list;
  }, [killActive, ops.blockers]);

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card size="small" title="안전 · Blocker">
        {blockers.length === 0 ? (
          <Typography.Text>✅ 현재 안전 차단 없음</Typography.Text>
        ) : (
          <Space wrap>
            {blockers.map((b) => (
              <Tag key={b} color="warning">
                ⚠ {b}
              </Tag>
            ))}
          </Space>
        )}
        <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
          상세 Risk 설정은{" "}
          <Link href="/admin/risk">Risk 화면</Link>에서 관리합니다.
        </Typography.Paragraph>
      </Card>

      <Card
        size="small"
        title="브로커 운영 상태"
        extra={
          <Radio.Group
            size="small"
            optionType="button"
            value={brokerFilter}
            onChange={(e) => setBrokerFilter(e.target.value)}
            options={[
              { label: "전체", value: "ALL" },
              { label: "UPBIT", value: "UPBIT" },
              { label: "KIWOOM", value: "KIWOOM" },
            ]}
          />
        }
      >
        <Table
          size="small"
          pagination={false}
          scroll={{ x: 1100 }}
          dataSource={statusRows}
          columns={[
            { title: "Broker", dataIndex: "broker", width: 80 },
            {
              title: "LIVE",
              dataIndex: "live",
              render: (v) => (
                <Tag color={toneToAntdColor(toneFromBoolOnOff(v === "ON"))}>
                  {v}
                </Tag>
              ),
            },
            {
              title: "ARM",
              dataIndex: "arm",
              render: (v) => (
                <Tag color={toneToAntdColor(toneFromBoolOnOff(v === "ON"))}>
                  {v}
                </Tag>
              ),
            },
            { title: "24H", dataIndex: "unattended", width: 90 },
            { title: "Runtime", dataIndex: "runtime" },
            { title: "Worker", dataIndex: "worker" },
            { title: "Runner", dataIndex: "runner" },
            { title: "Exit", dataIndex: "exit" },
            { title: "Feed", dataIndex: "feed" },
            { title: "Evaluator", dataIndex: "evaluator" },
            {
              title: "Readiness",
              dataIndex: "readiness",
              render: (v) => (
                <Tag color={toneToAntdColor(toneFromReadiness(String(v)))}>
                  {v}
                </Tag>
              ),
            },
            {
              title: "Blocker",
              dataIndex: "blocker",
              ellipsis: true,
              render: (v) =>
                v && v !== "—" ? <Tag color="warning">{v}</Tag> : "—",
            },
          ]}
        />
      </Card>

      <Card size="small" title="현재 AUTO 포지션">
        {openPositions.length ? (
          <Table
            size="small"
            pagination={false}
            scroll={{ x: 900 }}
            rowKey={(r) =>
              `${rec(r).broker_code}-${rec(r).symbol}`
            }
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

      <Card
        size="small"
        title={`UPBIT 후보 슬롯 ${ops.slotsOccupied} / ${ops.slotCapacity || "—"}`}
        extra={
          <Link href={adminRoutes.autotradingUpbit}>상세 관리 →</Link>
        }
      >
        <Typography.Text type="secondary">
          슬롯 상세·정책 편집은 업비트 자동매매 워크스페이스에서 수행합니다.
        </Typography.Text>
        <Collapse
          style={{ marginTop: 8 }}
          activeKey={slotsOpen ? ["slots"] : []}
          onChange={(keys) => setSlotsOpen(keys.includes("slots"))}
          items={[
            {
              key: "slots",
              label: "상세 보기",
              children: ops.slots.length ? (
                <Table
                  size="small"
                  pagination={false}
                  rowKey={(r) => String(rec(r).slot_no ?? rec(r).slot_id)}
                  dataSource={ops.slots.map((s) => rec(s))}
                  columns={[
                    { title: "Slot", dataIndex: "slot_no", width: 50 },
                    { title: "Symbol", dataIndex: "symbol" },
                    { title: "Score", dataIndex: "score" },
                    { title: "AI", dataIndex: "ai_recommendation" },
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
                <Typography.Text type="secondary">슬롯 데이터 없음</Typography.Text>
              ),
            },
          ]}
        />
      </Card>

      <Card size="small" title="계좌 전체 손익 (Safety)">
        <StatisticManualPnl value={ops.manualUnrealized} />
      </Card>

      {systemInfra ? (
        <Collapse
          items={[
            {
              key: "infra",
              label: "시스템·인프라 상세",
              children: systemInfra,
            },
          ]}
        />
      ) : null}
    </Space>
  );
}

function StatisticManualPnl({ value }: { value: number }) {
  return (
    <Alert
      type="info"
      showIcon
      title="MANUAL 평가손익 (계좌 전체)"
      description={`${formatKrw(value)} — AUTO 성과 차트와 분리된 Safety 정보입니다.`}
    />
  );
}
