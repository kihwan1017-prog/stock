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
  slotStatusTooltipKo,
  unattendedLeaseLabelKo,
} from "@/features/admin/autotrading/slotStatusLabels";
import {
  toneFromBoolOnOff,
  toneFromReadiness,
  toneFromRuntime,
  toneToAntdColor,
  type StatusTone,
} from "@/features/admin/autotrading/statusTone";
import {
  buildUpbitAutotradingAggregateStatus,
  parseOpsLiveArm,
} from "@/features/admin/upbit/upbitAutotradingCanonicalStatus";
import { parseBlockHistoryView } from "@/features/admin/upbit/upbitBlockHistoryView";
import { UPBIT_AUTOTRADING_EMPTY_LABELS } from "@/features/admin/upbit/upbitAutotradingSettingsConfig";
import {
  CANDIDATE_SLOT_TABLE_HINT_KO,
  resolveAutoPositionCoverage,
  resolveCandidateSlotCoverage,
  resolveDailyEntryCoverage,
  resolveRealtimeMonitorCoverage,
} from "@/features/admin/upbit/upbitSlotStatusSemantics";
import {
  UI_LABEL_KO,
  UI_TOOLTIP_KO,
} from "@/features/shared/display/displayUiLabelsKo";
import {
  decisionLabelKo,
  formatKrwKo,
  runtimeValueLabelKo,
} from "@/features/shared/display/tradingDisplayLabelsKo";
import { asRecord } from "@/shared/utils/dataHelpers";

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

function StatusCard({
  label,
  value,
  tone,
  tip,
  raw,
}: {
  label: string;
  value: string;
  tone: StatusTone;
  tip?: string;
  raw?: string;
}) {
  const tipText = [tip, raw && raw !== value ? `원본: ${raw}` : null]
    .filter(Boolean)
    .join(" · ");
  return (
    <Card size="small" styles={{ body: { padding: 10 } }}>
      <Tooltip title={tip || undefined}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {label}
        </Typography.Text>
      </Tooltip>
      <div>
        <Tooltip title={tipText || undefined}>
          <Tag color={toneToAntdColor(tone)} style={{ marginTop: 4 }}>
            {value}
          </Tag>
        </Tooltip>
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
  const slots = (Array.isArray(portfolio.slots) ? portfolio.slots : []).filter(
    (row): row is unknown =>
      row != null && typeof row === "object" && !Array.isArray(row),
  );
  const unattended = rec(ops.unattended);
  const control = rec(ops.control);
  const feed = rec(ops.market_feed);
  const stack = rec(ops.runtime_stack);
  const { liveOn, armOn } = parseOpsLiveArm(ops);

  const lease = String(
    unattended.lease_status ??
      unattended.status ??
      (unattended.unattended_enabled ? "ACTIVE" : "OFF"),
  );
  const runtime = String(
    ops.runtime ?? ops.strategy_runtime ?? control.strategy_runtime ?? "—",
  ).toUpperCase();
  const worker = String(
    ops.outbox_worker ?? control.outbox_worker ?? "—",
  ).toUpperCase();
  const runner = String(
    ops.runner ?? stack.runner ?? control.runner ?? "—",
  ).toUpperCase();
  const exitM = String(
    ops.exit_monitor ?? control.exit_monitor ?? "—",
  ).toUpperCase();
  const entryEvaluatorState = String(summary.entry_state ?? "—").toUpperCase();
  const readinessRaw = String(
    readiness?.status ?? readiness?.readiness ?? ops.auto_trading_state ?? "—",
  ).toUpperCase();
  const aggregate = buildUpbitAutotradingAggregateStatus({
    ops,
    readiness,
    entryEvaluatorState,
  });
  const blockView = parseBlockHistoryView(ops);
  const readyDisplay =
    aggregate.tier === "blocked" &&
    readinessRaw === "READY_FOR_AUTO_TRADING"
      ? "BLOCKED"
      : readinessRaw;
  const armDisplay = armOn
    ? `무장 · ${String(ops.arm_remaining_label ?? "ON")}`
    : "해제";

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

  const fm = rec(ops.full_market);
  const policyRec = rec(portfolio.policy);
  const coverageInput: import("@/features/admin/upbit/upbitSlotStatusSemantics").SlotCoverageSemanticsInput =
    {
      candidate_slot_assigned: Number(
        fm.candidate_slot_assigned ?? summary.candidate_slot_assigned ?? NaN,
      ),
      candidate_slot_capacity: Number(
        fm.candidate_slot_capacity ??
          summary.candidate_slot_capacity ??
          summary.max_positions ??
          fm.max_positions ??
          policyRec.max_positions ??
          NaN,
      ),
      candidates_waiting: Number(summary.candidates_waiting ?? NaN),
      positions_open: Number(summary.positions_open ?? NaN),
      pending_orders: Number(summary.pending_orders ?? NaN),
      auto_position_used: Number(
        fm.auto_position_used ?? summary.auto_position_used ?? NaN,
      ),
      auto_position_limit: Number(
        fm.auto_position_limit ?? summary.auto_position_limit ?? NaN,
      ),
      auto_slot_used: Number(fm.auto_slot_used ?? summary.auto_slot_used ?? NaN),
      auto_slot_limit: Number(
        fm.auto_slot_limit ?? summary.auto_slot_limit ?? NaN,
      ),
      daily_entry_used: Number(
        fm.daily_entry_used ?? summary.daily_entry_used ?? NaN,
      ),
      daily_entry_limit:
        fm.daily_entry_limit == null && summary.daily_entry_limit == null
          ? null
          : Number(fm.daily_entry_limit ?? summary.daily_entry_limit),
      daily_entry_limit_mode: String(
        fm.daily_entry_limit_mode ?? summary.daily_entry_limit_mode ?? "",
      ),
      daily_entry: rec(fm.daily_entry ?? summary.daily_entry) as {
        entry_count?: number | null;
        entry_limit?: number | null;
        mode?: string | null;
      },
      realtime_monitor_target:
        fm.realtime_monitor_target == null &&
        summary.realtime_monitor_target == null &&
        policyRec.realtime_monitored_symbol_target == null
          ? null
          : Number(
              fm.realtime_monitor_target ??
                summary.realtime_monitor_target ??
                policyRec.realtime_monitored_symbol_target,
            ),
      realtime_monitored_count:
        fm.realtime_monitored_count == null
          ? null
          : Number(fm.realtime_monitored_count),
    };
  // NaN → null (표시 헬퍼에서 처리)
  for (const [k, v] of Object.entries(coverageInput)) {
    if (typeof v === "number" && !Number.isFinite(v)) {
      (coverageInput as Record<string, unknown>)[k] = null;
    }
  }
  const candidateCov = resolveCandidateSlotCoverage(coverageInput);
  const autoPosCov = resolveAutoPositionCoverage(coverageInput);
  const dailyCov = resolveDailyEntryCoverage(coverageInput);
  const realtimeCov = resolveRealtimeMonitorCoverage(coverageInput);

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type={
          aggregate.tier === "blocked" || aggregate.tier === "system_blocked"
            ? "error"
            : aggregate.tier === "entry_restricted"
              ? "warning"
              : "success"
        }
        showIcon
        title={aggregate.headline}
        description={
          <>
            {aggregate.description}
            {blockView.status === "BLOCKED" ? (
              <Space
                orientation="vertical"
                size={4}
                style={{ display: "block", marginTop: 10 }}
              >
                <Typography.Text>
                  차단 일시:{" "}
                  <Typography.Text strong>
                    {blockView.blockedAt ?? "—"}
                  </Typography.Text>
                  {blockView.durationLabel
                    ? ` · 지속 ${blockView.durationLabel}`
                    : ""}
                </Typography.Text>
                <Typography.Text>
                  자동 복구 시작:{" "}
                  <Typography.Text strong>
                    {blockView.recoveryStartedAt ?? "—"}
                  </Typography.Text>
                </Typography.Text>
                <Typography.Text>
                  자동 복구 완료:{" "}
                  <Typography.Text strong>
                    {blockView.recoveredAt ?? "—"}
                  </Typography.Text>
                </Typography.Text>
                <Typography.Text>
                  복구 소요시간:{" "}
                  <Typography.Text strong>
                    {blockView.recoveryDurationLabel ?? "—"}
                  </Typography.Text>
                </Typography.Text>
                <Typography.Text>
                  복구 결과:{" "}
                  <Typography.Text strong>
                    {blockView.recoveryResultLabel}
                  </Typography.Text>
                  {" · 복구 방식: "}
                  <Typography.Text strong>
                    {blockView.recoveryMethodLabel}
                  </Typography.Text>
                </Typography.Text>
                <Typography.Text>
                  주요 차단 사유:{" "}
                  <Typography.Text strong>
                    {blockView.primaryText}
                  </Typography.Text>
                </Typography.Text>
                {blockView.secondaryText ? (
                  <Typography.Text type="secondary">
                    상세 사유: {blockView.secondaryText}
                  </Typography.Text>
                ) : null}
                {blockView.killScope ? (
                  <Typography.Text type="secondary">
                    Kill scope: {blockView.killScope}
                    {blockView.killReason
                      ? ` · ${blockView.killReason}`
                      : ""}
                  </Typography.Text>
                ) : null}
                <Typography.Text type="secondary">
                  현재 상태: 조치 필요 (운영자 승인 후 복구) · 위 시각은
                  차단/복구 이벤트이며 Activation·ARM 갱신 시각과 다릅니다.
                </Typography.Text>
              </Space>
            ) : null}
            {blockView.status === "RESOLVED" ? (
              <Space
                orientation="vertical"
                size={4}
                style={{ display: "block", marginTop: 8 }}
              >
                <Typography.Text type="secondary">
                  최근 차단: {blockView.blockedAt ?? "—"} ~{" "}
                  {blockView.unblockedAt ?? "—"}
                </Typography.Text>
                <Typography.Text type="secondary">
                  자동 복구 시작: {blockView.recoveryStartedAt ?? "—"}
                </Typography.Text>
                <Typography.Text type="secondary">
                  자동 복구 완료: {blockView.recoveredAt ?? "—"}
                  {blockView.recoveryDurationLabel
                    ? ` · 소요 ${blockView.recoveryDurationLabel}`
                    : ""}
                </Typography.Text>
                <Typography.Text type="secondary">
                  복구 결과: {blockView.recoveryResultLabel} · 복구 방식:{" "}
                  {blockView.recoveryMethodLabel}
                </Typography.Text>
              </Space>
            ) : null}
            {aggregate.blockers.length > 0 && blockView.status !== "BLOCKED" ? (
              <Typography.Paragraph
                type="secondary"
                style={{ marginBottom: 0, marginTop: 8 }}
              >
                차단 요인: {aggregate.blockers.join(" · ")}
              </Typography.Paragraph>
            ) : null}
            {!aggregate.entryOrdersPermitted &&
            entryEvaluatorState === "RUNNING" ? (
              <Typography.Paragraph
                type="warning"
                style={{ marginBottom: 0, marginTop: 8 }}
              >
                매수조건 평가기는 실행 중이지만, 실거래(LIVE)·자동주문
                승인(ARM)·준비상태가 충족되지 않으면 실제 매수 주문은
                차단됩니다.
              </Typography.Paragraph>
            ) : null}
          </>
        }
      />

      <Alert
        type="info"
        showIcon
        title={`업비트 계좌 현황`}
        description={
          <>
            계좌 식별자(내부) {ubaId}. LIVE/ARM WRITE는{" "}
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
            [
              UI_LABEL_KO.candidateWatchSlots,
              candidateCov.label,
              "yellow" as StatusTone,
              UI_TOOLTIP_KO.candidateWatchSlots,
            ],
            [
              UI_LABEL_KO.autoHoldPositions,
              autoPosCov.label,
              "green" as StatusTone,
              UI_TOOLTIP_KO.autoHoldPositions,
            ],
            [
              UI_LABEL_KO.dailyEntryToday,
              dailyCov.label,
              "gray" as StatusTone,
              UI_TOOLTIP_KO.dailyEntryToday,
            ],
            [
              UI_LABEL_KO.realtimeMonitorTarget,
              realtimeCov.label,
              "gray" as StatusTone,
              UI_TOOLTIP_KO.realtimeMonitorTarget,
            ],
          ] as [string, string, StatusTone, string][]
        ).map(([label, value, tone, tip]) => (
          <Col xs={12} sm={12} md={6} key={label}>
            <StatusCard label={label} value={value} tone={tone} tip={tip} />
          </Col>
        ))}
      </Row>

      <Row gutter={[8, 8]}>
        {(
          [
            [
              UI_LABEL_KO.h24,
              unattendedLeaseLabelKo(lease),
              toneFromRuntime(
                lease === "ACTIVE"
                  ? "RUNNING"
                  : lease === "PROTECTIVE_EXIT_ONLY"
                    ? "WARNING"
                    : "OFF",
              ),
              undefined,
              lease,
            ],
            [
              UI_LABEL_KO.live,
              liveOn ? "켜짐" : "꺼짐",
              toneFromBoolOnOff(liveOn),
              UI_TOOLTIP_KO.live,
              liveOn ? "LIVE ON" : "LIVE OFF",
            ],
            [
              UI_LABEL_KO.arm,
              armDisplay,
              toneFromBoolOnOff(armOn),
              UI_TOOLTIP_KO.arm,
              armOn ? "ARM ON" : "ARM OFF",
            ],
            [
              UI_LABEL_KO.runtime,
              runtimeValueLabelKo(runtime),
              toneFromRuntime(runtime),
              undefined,
              runtime,
            ],
            [
              UI_LABEL_KO.worker,
              runtimeValueLabelKo(worker),
              toneFromRuntime(worker),
              undefined,
              worker,
            ],
            [
              UI_LABEL_KO.executionRunner,
              runtimeValueLabelKo(runner),
              toneFromRuntime(runner),
              undefined,
              runner,
            ],
            [
              UI_LABEL_KO.exitMonitor,
              runtimeValueLabelKo(exitM),
              toneFromRuntime(exitM),
              undefined,
              exitM,
            ],
            [
              UI_LABEL_KO.feed,
              runtimeValueLabelKo(String(feed.status ?? "—")),
              toneFromRuntime(String(feed.status)),
              undefined,
              String(feed.status ?? "—"),
            ],
            [
              UI_LABEL_KO.entryEvaluator,
              runtimeValueLabelKo(entryEvaluatorState),
              aggregate.entryOrdersPermitted
                ? toneFromRuntime(entryEvaluatorState)
                : "yellow",
              undefined,
              entryEvaluatorState,
            ],
            [
              UI_LABEL_KO.readiness,
              runtimeValueLabelKo(readyDisplay),
              toneFromReadiness(readyDisplay),
              UI_TOOLTIP_KO.readiness,
              readyDisplay,
            ],
          ] as [string, string, StatusTone, string | undefined, string][]
        ).map(([label, value, tone, tip, raw]) => (
          <Col xs={12} sm={8} md={6} lg={4} key={label}>
            <StatusCard
              label={label}
              value={value}
              tone={tone}
              tip={tip}
              raw={raw}
            />
          </Col>
        ))}
      </Row>

      <Card
        size="small"
        title={UI_LABEL_KO.portfolioSlots}
        extra={
          candidateCov.capacity > 0 ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              최대 {candidateCov.capacity}개
            </Typography.Text>
          ) : null
        }
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          매수 후보를 최대 {candidateCov.capacity || "—"}개까지 등록하여 조건을
          감시합니다. 빈 슬롯은 오류가 아니며 현재 적격 후보가 없다는
          의미입니다.
        </Typography.Paragraph>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
          {CANDIDATE_SLOT_TABLE_HINT_KO}
        </Typography.Paragraph>
        <div style={{ overflowX: "auto" }}>
          <Table
            size="small"
            pagination={false}
            rowKey={(r) => String(rec(r).slot_id ?? rec(r).slot_no)}
            dataSource={slots as Record<string, unknown>[]}
            columns={[
              { title: UI_LABEL_KO.slot, dataIndex: "slot_no", width: 56 },
              {
                title: UI_LABEL_KO.symbol,
                dataIndex: "symbol",
                render: (v) => v ?? "—",
              },
              {
                title: UI_LABEL_KO.score,
                key: "score",
                width: 72,
                render: (_: unknown, row) => {
                  const o = rec(row);
                  return o.scanner_score ?? o.score ?? "—";
                },
              },
              {
                title: UI_LABEL_KO.ai,
                dataIndex: "ai_recommendation",
                width: 96,
                render: (v) =>
                  v == null ? "—" : decisionLabelKo(String(v)),
              },
              {
                title: UI_LABEL_KO.confidence,
                dataIndex: "ai_confidence",
                width: 88,
                render: (v) =>
                  v == null ? "—" : `${(Number(v) * 100).toFixed(0)}%`,
              },
              {
                title: UI_LABEL_KO.ownership,
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
                title: UI_LABEL_KO.status,
                dataIndex: "status",
                render: (v) => (
                  <Tooltip title={slotStatusTooltipKo(String(v))}>
                    <Tag>{slotStatusLabelKo(String(v))}</Tag>
                  </Tooltip>
                ),
              },
              {
                title: UI_LABEL_KO.ageTime,
                key: "age",
                render: (_: unknown, row) => {
                  const o = rec(row);
                  const st = String(o.status ?? "").toUpperCase();
                  const kind = String(o.age_kind ?? "").toUpperCase();
                  const prefix =
                    st === "OPEN" || kind === "HOLDING"
                      ? UI_LABEL_KO.holdingAge
                      : UI_LABEL_KO.waitingAge;
                  const age = formatAgeKo(
                    Number(o.age_seconds ?? o.waiting_age_seconds),
                  );
                  return age === "—" ? "—" : `${prefix} ${age}`;
                },
              },
              {
                title: UI_LABEL_KO.lastEvaluated,
                key: "last_eval",
                render: (_: unknown, row) =>
                  formatIsoAgeKo(
                    String(rec(row).last_entry_evaluated_at ?? ""),
                  ),
              },
              {
                title: UI_LABEL_KO.entryDecision,
                key: "dec",
                render: (_: unknown, row) => {
                  const raw = String(
                    rec(row).last_entry_decision ??
                      rec(row).entry_decision ??
                      "—",
                  );
                  return (
                    <Tooltip title={`원본: ${raw}`}>
                      <span>{decisionLabelKo(raw)}</span>
                    </Tooltip>
                  );
                },
              },
              {
                title: UI_LABEL_KO.blockReason,
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
                title: (
                  <Tooltip title={UI_TOOLTIP_KO.expectedOrderKrw}>
                    <span>{UI_LABEL_KO.expectedOrderKrw}</span>
                  </Tooltip>
                ),
                key: "order_amount_display",
                render: (_: unknown, row) => {
                  const o = rec(row);
                  const reserved = o.reserved_amount_krw;
                  const recommended = o.recommended_amount_krw;
                  const allocated = o.allocated_amount_krw;
                  const st = String(o.status ?? "").toUpperCase();
                  // 실제 예약만 "예약" — null이면 예약 금액으로 표시 금지
                  if (reserved != null && Number.isFinite(Number(reserved))) {
                    return (
                      <Tooltip title={UI_TOOLTIP_KO.reservedKrw}>
                        <span>
                          {UI_LABEL_KO.reservedKrw} {formatKrwKo(reserved)}
                        </span>
                      </Tooltip>
                    );
                  }
                  if (
                    st === "OPEN" &&
                    allocated != null &&
                    Number.isFinite(Number(allocated))
                  ) {
                    return (
                      <Tooltip title="체결·배정 기준 금액 (예약 아님)">
                        <span>
                          {UI_LABEL_KO.allocated} {formatKrwKo(allocated)}
                        </span>
                      </Tooltip>
                    );
                  }
                  if (
                    recommended != null &&
                    Number.isFinite(Number(recommended))
                  ) {
                    return (
                      <Tooltip title={UI_TOOLTIP_KO.expectedOrderKrw}>
                        <span>{formatKrwKo(recommended)}</span>
                      </Tooltip>
                    );
                  }
                  return "—";
                },
              },
              {
                title: UI_LABEL_KO.orderId,
                dataIndex: "entry_order_id",
                render: (v) => (v == null ? "—" : String(v)),
              },
            ]}
          />
        </div>
      </Card>

      {slots.some((row) => {
        const raw = String(
          rec(row as Record<string, unknown>).last_entry_block_reason ??
            rec(row as Record<string, unknown>).entry_block_reason ??
            "",
        ).toUpperCase();
        return raw === "MAX_OPEN_POSITIONS_REACHED";
      }) ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 0 }}
          title="신규 자동매수 제한"
          description={
            "거래소 보유 종목이 안전 한도(5/5, 수동 보유 포함)에 도달해 " +
            "기술조건이 통과해도 신규 자동매수가 제한됩니다. " +
            "자동매매 OPEN 슬롯 수와는 별개입니다."
          }
        />
      ) : null}

      <Card size="small" title={UI_LABEL_KO.entryBlockSummary}>
        {reasonTotal === 0 ? (
          <Typography.Text type="secondary">
            현재 슬롯의 최근 차단 사유만 표시합니다. 이력 집계 API가 없어
            비율은 현재 슬롯 기준입니다.
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

      <Card size="small" title={UI_LABEL_KO.autoPositions}>
        {openSlots.length === 0 ? (
          <Empty
            description={
              UPBIT_AUTOTRADING_EMPTY_LABELS.noAutoPositions ||
              "현재 보유 중인 자동매매 종목이 없습니다."
            }
          />
        ) : (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            title="보유 중 이유 · 손익"
            description={
              (() => {
                const first = openSlots[0] as {
                  why_still_holding_ko?: string;
                  exit_intent?: {
                    status_label_ko?: string;
                    retry_display?: string;
                    next_retry_at?: string | null;
                    why_still_holding_ko?: string;
                  };
                };
                const intent = first?.exit_intent;
                if (intent?.status_label_ko) {
                  const bits = [intent.status_label_ko];
                  if (intent.retry_display) {
                    bits.push(`재시도 ${intent.retry_display}`);
                  }
                  if (intent.next_retry_at) {
                    bits.push(`다음 재검증 ${intent.next_retry_at}`);
                  }
                  return (
                    intent.why_still_holding_ko ||
                    first?.why_still_holding_ko ||
                    bits.join(" · ")
                  );
                }
                return (
                  first?.why_still_holding_ko ||
                  "전략 청산(MA_DEAD_CROSS)이 체결되기 전까지 보유합니다. 수량·진입가·현재가·손익은 브로커 스냅샷 READ 값입니다."
                );
              })()
            }
          />
        )}
        {openSlots.length > 0 ? (
          <Table
            size="small"
            pagination={false}
            rowKey={(r) => String(r.slot_id ?? r.symbol)}
            dataSource={openSlots}
            columns={[
              { title: UI_LABEL_KO.symbol, dataIndex: "symbol" },
              {
                title: UI_LABEL_KO.qty,
                key: "qty",
                render: (_: unknown, row) => {
                  const v = rec(row).quantity;
                  return v == null ? "—" : String(v);
                },
              },
              {
                title: UI_LABEL_KO.entry,
                key: "entry",
                render: (_: unknown, row) => {
                  const v = rec(row).entry_price;
                  return v == null ? "—" : String(v);
                },
              },
              {
                title: UI_LABEL_KO.current,
                key: "cur",
                render: (_: unknown, row) => {
                  const v = rec(row).current_price;
                  return v == null ? "—" : String(v);
                },
              },
              {
                title: UI_LABEL_KO.unrealizedPnl,
                key: "pnl",
                render: (_: unknown, row) => {
                  const o = rec(row);
                  const pnl = o.unrealized_pnl_krw;
                  const pct = o.return_rate_pct;
                  if (pnl == null && pct == null) return "—";
                  const pctText =
                    pct == null ? "" : ` (${Number(pct).toFixed(2)}%)`;
                  return `${formatKrwKo(pnl)}${pctText}`;
                },
              },
              {
                title: UI_LABEL_KO.allocated,
                dataIndex: "allocated_amount_krw",
                render: (v) => formatKrwKo(v),
              },
              {
                title: UI_LABEL_KO.holdingAge,
                key: "hold_age",
                render: (_: unknown, row) => {
                  const ageSec = Number(
                    rec(row).age_seconds ?? rec(row).waiting_age_seconds,
                  );
                  const ageLabel = formatAgeKo(ageSec);
                  // 장기보유 감시 badge — 자동 청산 기준 아님
                  let badge: { color: string; text: string } | null = null;
                  if (Number.isFinite(ageSec)) {
                    const hours = ageSec / 3600;
                    if (hours >= 24) {
                      badge = { color: "orange", text: "24h+ 장기보유" };
                    } else if (hours >= 12) {
                      badge = { color: "gold", text: "12h+ 경고" };
                    } else if (hours >= 6) {
                      badge = { color: "default", text: "6h+ 주의" };
                    }
                  }
                  return (
                    <Space size={4} wrap>
                      <span>{ageLabel}</span>
                      {badge ? (
                        <Tooltip title="장기보유 감시 기준이며 자동 청산 기준이 아닙니다.">
                          <Tag color={badge.color}>{badge.text}</Tag>
                        </Tooltip>
                      ) : null}
                    </Space>
                  );
                },
              },
              {
                title: UI_LABEL_KO.slTpTrailing,
                key: "sl",
                render: () => "정책 화면 참고",
              },
              {
                title: UI_LABEL_KO.exitMonitor,
                key: "ex",
                render: () => runtimeValueLabelKo(exitM),
              },
              {
                title: UI_LABEL_KO.binding,
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
