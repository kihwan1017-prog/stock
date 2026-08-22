"use client";

/**
 * UPBIT 현황 — status cards + slots + AUTO positions + entry reason.
 */

import {
  Alert,
  Card,
  Col,
  Empty,
  Progress,
  Row,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import Link from "next/link";

import { adminRoutes } from "@/config/routes";
import {
  ownershipBadgeColor,
  ownershipLabelKo,
} from "@/features/admin/accounts/symbolOwnershipLabels";
import {
  entryBlockReasonKo,
  entryBlockReasonShortKo,
} from "@/features/admin/autotrading/entryBlockReasonKo";
import {
  formatAgeKo,
  formatIsoAgeKo,
  slotStatusLabelKo,
  unattendedLeaseLabelKo,
} from "@/features/admin/autotrading/slotStatusLabels";
import {
  toneFromBoolOnOff,
  toneFromReadiness,
  toneFromRuntime,
  toneToAntdColor,
  type StatusTone,
} from "@/features/admin/autotrading/statusTone";
import { asRecord } from "@/shared/utils/dataHelpers";

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

function StatusCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: StatusTone;
}) {
  return (
    <Card size="small" styles={{ body: { padding: 10 } }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {label}
      </Typography.Text>
      <div>
        <Tag color={toneToAntdColor(tone)} style={{ marginTop: 4 }}>
          {value}
        </Tag>
      </div>
    </Card>
  );
}

type Props = {
  ubaId: number;
  ops: Record<string, unknown>;
  portfolio: Record<string, unknown>;
  readiness?: Record<string, unknown>;
  ownershipBySymbol?: Map<string, string>;
};

export function UpbitOpsStatusPanel({
  ubaId,
  ops,
  portfolio,
  readiness,
  ownershipBySymbol,
}: Props) {
  const summary = rec(portfolio.summary);
  const slots = Array.isArray(portfolio.slots) ? portfolio.slots : [];
  const unattended = rec(ops.unattended);
  const control = rec(ops.control);
  const feed = rec(ops.market_feed);

  const lease = String(
    unattended.lease_status ??
      unattended.status ??
      (unattended.unattended_enabled ? "ACTIVE" : "OFF"),
  );
  const liveOn = Boolean(ops.live_on ?? ops.live_order_enabled);
  const armOn = Boolean(ops.arm_on ?? ops.live_armed);
  const runtime = String(
    ops.strategy_runtime ?? control.strategy_runtime ?? "—",
  );
  const worker = String(ops.outbox_worker ?? control.outbox_worker ?? "—");
  const exitM = String(ops.exit_monitor ?? control.exit_monitor ?? "—");
  const ready = String(
    readiness?.readiness ?? readiness?.status ?? ops.auto_trading_state ?? "—",
  );

  const openSlots = slots
    .map((s) => rec(s))
    .filter((s) => String(s.status).toUpperCase() === "OPEN");

  // latest block reasons only (history API 없음 — 가짜 % 금지)
  const latestBlocks = slots
    .map((s) => rec(s))
    .map((s) => ({
      symbol: String(s.symbol ?? "—"),
      reason: String(s.last_entry_block_reason ?? s.entry_block_reason ?? ""),
    }))
    .filter((x) => x.reason);

  const reasonCounts = new Map<string, number>();
  for (const b of latestBlocks) {
    const key = entryBlockReasonShortKo(b.reason);
    reasonCounts.set(key, (reasonCounts.get(key) ?? 0) + 1);
  }
  const reasonTotal = [...reasonCounts.values()].reduce((a, b) => a + b, 0);

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title={`UBA ${ubaId} 현황`}
        description={
          <>
            LIVE/ARM WRITE는{" "}
            <Link href={`${adminRoutes.accounts}?broker=UPBIT`}>계좌 현황</Link>
            , 리스크 WRITE는{" "}
            <Link href={adminRoutes.risk}>리스크</Link>, 안전 제어는{" "}
            <Link href={adminRoutes.liveValidationUpbit}>안전 제어</Link>.
          </>
        }
      />

      <Row gutter={[8, 8]}>
        {(
          [
            ["24H", unattendedLeaseLabelKo(lease), toneFromRuntime(lease === "ACTIVE" ? "RUNNING" : lease === "PROTECTIVE_EXIT_ONLY" ? "WARNING" : "OFF")],
            ["LIVE", liveOn ? "켜짐" : "꺼짐", toneFromBoolOnOff(liveOn)],
            ["ARM", armOn ? "무장" : "해제", toneFromBoolOnOff(armOn)],
            ["Runtime", runtime, toneFromRuntime(runtime)],
            ["Worker", worker, toneFromRuntime(worker)],
            ["Execution Runner", runtime, toneFromRuntime(runtime)],
            ["Exit Monitor", exitM, toneFromRuntime(exitM)],
            ["Feed", String(feed.status ?? "—"), toneFromRuntime(String(feed.status))],
            [
              "Entry Evaluator",
              String(summary.entry_state ?? "—"),
              toneFromRuntime(String(summary.entry_state)),
            ],
            ["Readiness", ready, toneFromReadiness(ready)],
          ] as [string, string, StatusTone][]
        ).map(([label, value, tone]) => (
          <Col xs={12} sm={8} md={6} lg={4} key={label}>
            <StatusCard label={label} value={value} tone={tone} />
          </Col>
        ))}
      </Row>

      <Card size="small" title="Portfolio Slots">
        <div style={{ overflowX: "auto" }}>
          <Table
            size="small"
            pagination={false}
            rowKey={(r) => String(rec(r).slot_id ?? rec(r).slot_no)}
            dataSource={slots as Record<string, unknown>[]}
            columns={[
              { title: "Slot", dataIndex: "slot_no", width: 56 },
              {
                title: "Symbol",
                dataIndex: "symbol",
                render: (v) => v ?? "—",
              },
              {
                title: "Score",
                key: "score",
                width: 72,
                render: (_: unknown, row) => {
                  const o = rec(row);
                  return o.scanner_score ?? o.score ?? "—";
                },
              },
              {
                title: "AI",
                dataIndex: "ai_recommendation",
                width: 88,
                render: (v) => (v == null ? "—" : String(v)),
              },
              {
                title: "Confidence",
                dataIndex: "ai_confidence",
                width: 88,
                render: (v) =>
                  v == null ? "—" : `${(Number(v) * 100).toFixed(0)}%`,
              },
              {
                title: "Ownership",
                key: "own",
                width: 100,
                render: (_: unknown, row) => {
                  const sym = String(rec(row).symbol ?? "").toUpperCase();
                  const owner =
                    ownershipBySymbol?.get(sym) ??
                    (String(rec(row).status).toUpperCase() === "OPEN"
                      ? "AUTO"
                      : "—");
                  if (owner === "—") return "—";
                  return (
                    <Tag color={ownershipBadgeColor(owner)}>
                      {ownershipLabelKo(owner)}
                    </Tag>
                  );
                },
              },
              {
                title: "Status",
                dataIndex: "status",
                render: (v) => (
                  <Tooltip title={String(v)}>
                    <Tag>{slotStatusLabelKo(String(v))}</Tag>
                  </Tooltip>
                ),
              },
              {
                title: "Waiting age",
                dataIndex: "waiting_age_seconds",
                render: (v) => formatAgeKo(v as number),
              },
              {
                title: "Last evaluated",
                key: "last_eval",
                render: (_: unknown, row) =>
                  formatIsoAgeKo(
                    String(rec(row).last_entry_evaluated_at ?? ""),
                  ),
              },
              {
                title: "Entry decision",
                key: "dec",
                render: (_: unknown, row) =>
                  String(
                    rec(row).last_entry_decision ??
                      rec(row).entry_decision ??
                      "—",
                  ),
              },
              {
                title: "Block reason",
                key: "block",
                ellipsis: true,
                render: (_: unknown, row) => {
                  const raw = String(
                    rec(row).last_entry_block_reason ??
                      rec(row).entry_block_reason ??
                      "",
                  );
                  const mapped = entryBlockReasonKo(raw);
                  if (!mapped.rawCode) return "—";
                  return (
                    <Tooltip title={`${mapped.detail} (${mapped.rawCode})`}>
                      <span>{mapped.label}</span>
                    </Tooltip>
                  );
                },
              },
              {
                title: "Reserved KRW",
                dataIndex: "reserved_amount_krw",
                render: (v) => (v == null ? "—" : String(v)),
              },
              {
                title: "Order id",
                dataIndex: "entry_order_id",
                render: (v) => (v == null ? "—" : String(v)),
              },
            ]}
          />
        </div>
      </Card>

      <Card size="small" title="최근 Entry 평가 차단 요약">
        {reasonTotal === 0 ? (
          <Typography.Text type="secondary">
            현재 슬롯의 latest block reason만 표시합니다. 이력 집계 API는
            BACKEND_READ_API_GAP 입니다 (가짜 % 없음).
          </Typography.Text>
        ) : (
          <Space orientation="vertical" style={{ width: "100%" }}>
            {[...reasonCounts.entries()].map(([label, count]) => (
              <div key={label}>
                <Space style={{ width: "100%", justifyContent: "space-between" }}>
                  <span>{label}</span>
                  <span>{Math.round((count / reasonTotal) * 100)}%</span>
                </Space>
                <Progress
                  percent={Math.round((count / reasonTotal) * 100)}
                  showInfo={false}
                  size="small"
                />
              </div>
            ))}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              * 현재 슬롯 latest 기준 비율 (히스토리 아님)
            </Typography.Text>
          </Space>
        )}
      </Card>

      <Card size="small" title="AUTO 보유 포지션">
        {openSlots.length === 0 ? (
          <Empty description="현재 자동매매 보유 종목이 없습니다." />
        ) : (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            title="상세 PnL/SL/TP"
            description="OPEN slot의 qty·entry·current·SL·TP·Trailing은 portfolio READ에 없음 (BACKEND_READ_API_GAP). 가용 필드만 표시합니다."
          />
        )}
        {openSlots.length > 0 ? (
          <Table
            size="small"
            pagination={false}
            rowKey={(r) => String(r.slot_id ?? r.symbol)}
            dataSource={openSlots}
            columns={[
              { title: "Symbol", dataIndex: "symbol" },
              {
                title: "Qty",
                key: "qty",
                render: () => "—",
              },
              {
                title: "Entry",
                key: "entry",
                render: () => "—",
              },
              {
                title: "Current",
                key: "cur",
                render: () => "—",
              },
              {
                title: "PnL",
                key: "pnl",
                render: () => "—",
              },
              {
                title: "Allocated",
                dataIndex: "allocated_amount_krw",
              },
              {
                title: "SL / TP / Trailing",
                key: "sl",
                render: () => "API gap",
              },
              {
                title: "Highest",
                key: "hi",
                render: () => "—",
              },
              {
                title: "Exit Monitor",
                key: "ex",
                render: () => exitM,
              },
              {
                title: "Binding",
                dataIndex: "position_binding_id",
                render: (v) => (v == null ? "—" : String(v)),
              },
            ]}
          />
        ) : null}
      </Card>
    </Space>
  );
}
