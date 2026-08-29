"use client";

/**
 * UPBIT 후보 슬롯 · 진입 조건 정책 (canonical portfolio/policy SoT).
 */

import {
  Alert,
  Card,
  Descriptions,
  Form,
  InputNumber,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  type FormInstance,
} from "antd";

import {
  entryBlockReasonKo,
} from "@/features/admin/autotrading/entryBlockReasonKo";
import {
  formatIsoAgeKo,
} from "@/features/admin/autotrading/slotStatusLabels";
import { asRecordOrEmpty } from "@/shared/utils/dataHelpers";

import {
  ENTRY_FUNNEL_STEPS,
  entryPolicyLabel,
  formatMinutesFromSeconds,
  formatWaitingAge,
  policyDisplayRecord,
} from "./upbitPortfolioPolicyHelpers";

type Props = {
  policy: Record<string, unknown>;
  slots: Record<string, unknown>[];
  entryForm: FormInstance;
  entryInitial: Record<string, unknown>;
  /** 오늘(KST) 실제 AUTO BUY 진입 사용량 */
  dailyEntry?: Record<string, unknown> | null;
  dailyEntryLabelKo?: string | null;
};

function num(v: unknown, digits = 2): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return String(Number(n.toFixed(digits)));
}

export function UpbitPortfolioPolicyPanel({
  policy,
  slots,
  entryForm,
  entryInitial,
  dailyEntry,
  dailyEntryLabelKo,
}: Props) {
  const p = policyDisplayRecord(policy);
  const capacity = Number(p.max_positions ?? p.slot_capacity ?? 3);
  const occupied = Number(p.slots_occupied ?? 0);
  const emptyN = Number(p.slots_empty ?? Math.max(0, capacity - occupied));
  const entryMode = String(
    entryInitial.portfolio_daily_entry_limit_mode ??
      policy.portfolio_daily_entry_limit_mode ??
      "LIMITED",
  ).toUpperCase();
  const unlimited = entryMode === "UNLIMITED";
  const entryCount =
    dailyEntry?.entry_count != null && Number.isFinite(Number(dailyEntry.entry_count))
      ? Number(dailyEntry.entry_count)
      : null;
  const entryLimit =
    unlimited
      ? null
      : dailyEntry?.entry_limit != null && Number.isFinite(Number(dailyEntry.entry_limit))
        ? Number(dailyEntry.entry_limit)
        : Number(entryInitial.portfolio_daily_entry_limit ?? 6);
  const remaining = unlimited
    ? null
    : dailyEntry?.remaining != null && Number.isFinite(Number(dailyEntry.remaining))
      ? Number(dailyEntry.remaining)
      : entryCount != null && entryLimit != null
        ? Math.max(0, entryLimit - entryCount)
        : null;

  const slotRows = [...slots]
    .sort(
      (a, b) =>
        Number(a.slot_no ?? 0) - Number(b.slot_no ?? 0),
    )
    .filter((row) => Number(row.slot_no ?? 0) <= capacity);

  while (slotRows.length < capacity) {
    slotRows.push({
      slot_no: slotRows.length + 1,
      status: "EMPTY",
      symbol: null,
    });
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="진입 조건 순서"
        description={
          <Typography.Text>
            {ENTRY_FUNNEL_STEPS.join(" → ")}
            <br />
            AI ALLOW만으로는 매수하지 않습니다. MA 추세·간격·RSI·거래량을
            모두 통과해야 Entry 신호가 발생합니다.
          </Typography.Text>
        }
      />

      <Card size="small" title="후보 슬롯 정책">
        <Descriptions size="small" bordered column={2}>
          <Descriptions.Item label="최대 후보 슬롯">
            {capacity}
          </Descriptions.Item>
          <Descriptions.Item label="현재 사용 슬롯">
            {occupied} / {capacity}
          </Descriptions.Item>
          <Descriptions.Item label="빈 슬롯">{emptyN}</Descriptions.Item>
          <Descriptions.Item label="최대 대기시간">
            {formatMinutesFromSeconds(p.candidate_max_wait_seconds)}
          </Descriptions.Item>
          <Descriptions.Item label="즉시 교체 점수차">
            +{num(p.candidate_switch_min_score_delta, 1)}
          </Descriptions.Item>
          <Descriptions.Item label="후보 신선도">
            {formatMinutesFromSeconds(p.candidate_max_age_seconds)}
          </Descriptions.Item>
          <Descriptions.Item label="AI 조건">
            {String(p.ai_requirement_label ?? (p.require_ai_allow ? "ALLOW" : "ANY"))}
          </Descriptions.Item>
          <Descriptions.Item label="Ownership">FREE</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card size="small" title="매수 진입 조건 (표시)">
        <Descriptions size="small" bordered column={2}>
          <Descriptions.Item label="진입 방식">
            {entryPolicyLabel(p.entry_signal_policy)}
          </Descriptions.Item>
          <Descriptions.Item label="단기/장기 MA">
            {num(p.short_ma_window, 0)} / {num(p.long_ma_window, 0)}
          </Descriptions.Item>
          <Descriptions.Item label="최소 MA 간격">
            {num(p.min_ma_separation_pct, 2)}%
          </Descriptions.Item>
          <Descriptions.Item label="RSI 상한">
            {num(p.rsi_max, 0)}
          </Descriptions.Item>
          <Descriptions.Item label="Volume 최소">
            {num(p.min_volume_surge, 2)}
          </Descriptions.Item>
          <Descriptions.Item label="Cooldown">
            {formatMinutesFromSeconds(p.entry_cooldown_seconds)}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card size="small" title="정책 편집">
        <Form form={entryForm} layout="vertical" initialValues={entryInitial}>
          <Typography.Text strong>후보 슬롯</Typography.Text>
          <Space wrap size={12} style={{ marginTop: 8, marginBottom: 16 }}>
            <Form.Item
              name="max_positions"
              label="최대 후보 슬롯 (1~10)"
              rules={[
                { required: true, message: "슬롯 수를 입력하세요" },
                {
                  type: "number",
                  min: 1,
                  max: 10,
                  message: "1~10 사이 값만 허용됩니다",
                },
              ]}
            >
              <InputNumber min={1} max={10} />
            </Form.Item>
            <Form.Item
              name="candidate_max_wait_seconds"
              label="최대 대기 (초)"
            >
              <InputNumber min={60} step={300} />
            </Form.Item>
            <Form.Item
              name="candidate_switch_min_score_delta"
              label="교체 점수차"
            >
              <InputNumber min={0} max={100} step={0.5} />
            </Form.Item>
            <Form.Item
              name="candidate_max_age_seconds"
              label="후보 신선도 (초)"
            >
              <InputNumber min={60} step={60} />
            </Form.Item>
            <Form.Item
              name="candidate_hold_seconds"
              label="최소 유지 (초)"
            >
              <InputNumber min={0} step={60} />
            </Form.Item>
          </Space>

          <Typography.Text strong>매수 진입</Typography.Text>
          <Space wrap size={12} style={{ marginTop: 8 }}>
            <Form.Item name="entry_signal_policy" label="Entry 정책">
              <Select
                options={[
                  { value: "BULLISH_STATE", label: "BULLISH_STATE" },
                  { value: "CROSS_EVENT", label: "CROSS_EVENT" },
                ]}
              />
            </Form.Item>
            <Form.Item name="short_ma_window" label="단기 MA">
              <InputNumber min={1} max={200} />
            </Form.Item>
            <Form.Item name="long_ma_window" label="장기 MA">
              <InputNumber min={2} max={500} />
            </Form.Item>
            <Form.Item name="min_ma_separation_pct" label="최소 MA 간격 (%)">
              <InputNumber min={0} max={50} step={0.01} />
            </Form.Item>
            <Form.Item name="rsi_max" label="RSI 상한">
              <InputNumber min={1} max={100} />
            </Form.Item>
            <Form.Item name="min_volume_surge" label="Volume Surge 최소">
              <InputNumber min={0.01} max={100} step={0.1} />
            </Form.Item>
            <Form.Item
              name="require_ai_allow"
              label="AI ALLOW 필수"
              valuePropName="checked"
            >
              <Switch checkedChildren="ON" unCheckedChildren="OFF" />
            </Form.Item>
            <Form.Item name="entry_cooldown_seconds" label="Cooldown (초)">
              <InputNumber min={0} step={30} />
            </Form.Item>
            <Form.Item
              name="portfolio_daily_entry_limit_mode"
              label="일일 신규매수 한도 방식"
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  제한 없음은 일일 AUTO BUY 건수 게이트만 해제합니다. Slot·Risk·AI·Kill은 유지됩니다.
                </Typography.Text>
              }
            >
              <Select
                options={[
                  { value: "LIMITED", label: "제한 있음" },
                  { value: "UNLIMITED", label: "제한 없음" },
                ]}
                style={{ width: 160 }}
              />
            </Form.Item>
            <Form.Item
              noStyle
              shouldUpdate={(prev, cur) =>
                prev.portfolio_daily_entry_limit_mode !==
                cur.portfolio_daily_entry_limit_mode
              }
            >
              {({ getFieldValue }) => {
                const mode = String(
                  getFieldValue("portfolio_daily_entry_limit_mode") ?? "LIMITED",
                ).toUpperCase();
                const isUnlimited = mode === "UNLIMITED";
                return (
                  <Form.Item
                    name="portfolio_daily_entry_limit"
                    label={
                      <Tooltip title="실제 자동매매 신규 진입 기준. 후보 교체/Shadow는 포함하지 않습니다. (KST 00:00~24:00)">
                        <span>일일 진입 한도</span>
                      </Tooltip>
                    }
                    extra={
                      entryCount != null ? (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {isUnlimited
                            ? `오늘 신규매수 ${entryCount}건 / 제한 없음`
                            : dailyEntryLabelKo ??
                              `오늘 신규매수 ${entryCount} / ${entryLimit} (남은 ${remaining ?? "—"})`}
                          {" · "}
                          기준 KST 00:00~24:00
                        </Typography.Text>
                      ) : (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          실제 BUY 진입만 집계 · KST 일자
                        </Typography.Text>
                      )
                    }
                  >
                    <InputNumber min={1} max={100} disabled={isUnlimited} />
                  </Form.Item>
                );
              }}
            </Form.Item>
            <Form.Item
              name="realtime_monitored_symbol_target"
              label={
                <Tooltip title="자동매매 후보 중 실시간 시세를 동시에 감시할 최대 종목 수입니다. 물리 WebSocket 연결과 다를 수 있습니다.">
                  <span>실시간 감시 종목 수</span>
                </Tooltip>
              }
            >
              <InputNumber min={1} max={10} />
            </Form.Item>
            <Form.Item
              name="consecutive_loss_limit"
              label="연속 손실 한도"
            >
              <InputNumber min={1} max={50} />
            </Form.Item>
          </Space>
        </Form>
      </Card>

      <Card size="small" title="슬롯별 매수 관측 (최대 5)">
        <Table
          size="small"
          pagination={false}
          rowKey={(r) => String(asRecordOrEmpty(r).slot_no ?? "x")}
          dataSource={slotRows}
          columns={[
            {
              title: "슬롯",
              dataIndex: "slot_no",
              width: 52,
            },
            {
              title: "종목",
              dataIndex: "symbol",
              render: (v) => (v ? String(v) : "— 빈 슬롯 —"),
            },
            {
              title: "점수",
              key: "score",
              width: 72,
              render: (_: unknown, row) => {
                const o = asRecordOrEmpty(row);
                const v = o.scanner_score ?? o.score;
                return v == null ? "—" : String(v);
              },
            },
            {
              title: "AI 판단",
              dataIndex: "ai_recommendation",
              width: 88,
              render: (v) => (v == null ? "—" : String(v)),
            },
            {
              title: "경과 시간",
              key: "wait",
              width: 100,
              render: (_: unknown, row) => {
                const o = asRecordOrEmpty(row);
                const st = String(o.status ?? "").toUpperCase();
                const kind = String(o.age_kind ?? "").toUpperCase();
                const label =
                  st === "OPEN" || kind === "HOLDING"
                    ? "보유"
                    : "대기";
                const age = formatWaitingAge(
                  o.age_seconds ?? o.waiting_age_seconds,
                );
                return age === "—" ? "—" : `${label} ${age}`;
              },
            },
            {
              title: "Entry 판정",
              key: "decision",
              width: 100,
              render: (_: unknown, row) => {
                const o = asRecordOrEmpty(row);
                const st = String(o.status ?? "").toUpperCase();
                if (st === "EMPTY") return "—";
                const d = o.last_entry_decision;
                return d == null ? "대기" : String(d);
              },
            },
            {
              title: "차단 이유",
              key: "reason",
              ellipsis: true,
              render: (_: unknown, row) => {
                const o = asRecordOrEmpty(row);
                if (String(o.status ?? "").toUpperCase() === "EMPTY") {
                  return "빈 슬롯";
                }
                const mapped = entryBlockReasonKo(
                  o.last_entry_block_reason == null
                    ? null
                    : String(o.last_entry_block_reason),
                );
                if (!mapped.rawCode) return "—";
                return (
                  <Tooltip title={mapped.detail}>
                    <span>{mapped.label}</span>
                  </Tooltip>
                );
              },
            },
            {
              title: "최근 평가",
              key: "eval_at",
              width: 120,
              render: (_: unknown, row) => {
                const at = asRecordOrEmpty(row).last_entry_evaluated_at;
                return at ? formatIsoAgeKo(String(at)) : "—";
              },
            },
            {
              title: "교체",
              key: "repl",
              width: 160,
              render: (_: unknown, row) => {
                const o = asRecordOrEmpty(row);
                if (String(o.status ?? "").toUpperCase() === "EMPTY") {
                  return <Tag>EMPTY 우선 배정</Tag>;
                }
                const exceeded = Boolean(o.replacement_max_wait_exceeded);
                const score = o.replacement_min_score_to_beat;
                return (
                  <Typography.Text style={{ fontSize: 12 }}>
                    {exceeded ? (
                      <Tag color="warning">Max wait 초과</Tag>
                    ) : (
                      <Tag>Max wait 이내</Tag>
                    )}
                    <br />
                    교체 score &gt;{" "}
                    {score == null ? "—" : String(score)}
                  </Typography.Text>
                );
              },
            },
          ]}
        />
      </Card>
    </Space>
  );
}
