"use client";

import { Card, Col, Row, Space, Statistic, Tag, Typography } from "antd";
import Link from "next/link";

import { adminRoutes } from "@/config/routes";
import {
  autoTradingStateLabelKo,
  unattendedLeaseLabelKo,
} from "@/features/admin/autotrading/slotStatusLabels";
import {
  toneFromBoolOnOff,
  toneFromReadiness,
  toneFromRuntime,
  toneToAntdColor,
  type StatusTone,
} from "@/features/admin/autotrading/statusTone";

export type BrokerCardModel = {
  broker: "KIWOOM" | "UPBIT";
  title: string;
  href: string;
  marketLabel?: string;
  marketTone?: StatusTone;
  liveOn: boolean | null;
  armOn: boolean | null;
  runtime: string | null;
  strategy?: string | null;
  autoPositions: number | null;
  todayOrders: number | null;
  autoPnlLabel: string;
  blocker: string | null;
  readiness?: string | null;
  /** UPBIT extras */
  unattended?: string | null;
  unattendedAutoRenew?: boolean | null;
  unattendedRemainingSeconds?: number | null;
  unattendedRenewWarning?: boolean;
  worker?: string | null;
  runner?: string | null;
  exitMonitor?: string | null;
  feed?: string | null;
  evaluator?: string | null;
  /** open-order ownership (AUTO risk isolation) */
  manualOpenOrders?: number | null;
  autoOpenOrders?: number | null;
  autoOpenOrderLimit?: number | null;
};

function StatusLine({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: StatusTone;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
      <Typography.Text type="secondary">{label}</Typography.Text>
      <Tag color={toneToAntdColor(tone)} style={{ marginInlineEnd: 0 }}>
        {value}
      </Tag>
    </div>
  );
}

export function BrokerOpsCard({ model }: { model: BrokerCardModel }) {
  const overallTone = model.blocker
    ? "red"
    : toneFromRuntime(model.runtime) === "green" && model.liveOn
      ? "green"
      : model.liveOn
        ? "yellow"
        : "gray";

  return (
    <Card
      size="small"
      title={
        <Space>
          <span>{model.title}</span>
          <Tag color={toneToAntdColor(overallTone)}>
            {autoTradingStateLabelKo(model.readiness ?? model.runtime)}
          </Tag>
        </Space>
      }
      extra={<Link href={model.href}>워크스페이스</Link>}
      styles={{ body: { paddingBlock: 12 } }}
    >
      <Space orientation="vertical" size={8} style={{ width: "100%" }}>
        {model.broker === "KIWOOM" ? (
          <StatusLine
            label="시장"
            value={model.marketLabel ?? "—"}
            tone={model.marketTone ?? "gray"}
          />
        ) : (
          <StatusLine
            label="24H"
            value={(() => {
              const base = unattendedLeaseLabelKo(model.unattended);
              if (
                String(model.unattended).toUpperCase() === "ACTIVE" &&
                model.unattendedAutoRenew
              ) {
                return `${base} · Auto Renew ON`;
              }
              return base;
            })()}
            tone={
              String(model.unattended).toUpperCase() === "ACTIVE"
                ? model.unattendedRenewWarning
                  ? "yellow"
                  : "green"
                : String(model.unattended).toUpperCase() ===
                    "PROTECTIVE_EXIT_ONLY"
                  ? "yellow"
                  : "gray"
            }
          />
        )}
        <StatusLine
          label="LIVE"
          value={model.liveOn ? "켜짐" : model.liveOn === false ? "꺼짐" : "—"}
          tone={toneFromBoolOnOff(model.liveOn)}
        />
        <StatusLine
          label="ARM"
          value={model.armOn ? "무장" : model.armOn === false ? "해제" : "—"}
          tone={toneFromBoolOnOff(model.armOn)}
        />
        <StatusLine
          label="Runtime"
          value={model.runtime ?? "—"}
          tone={toneFromRuntime(model.runtime)}
        />
        <StatusLine
          label="일반매매 미체결"
          value={
            model.manualOpenOrders == null
              ? "—"
              : String(model.manualOpenOrders)
          }
          tone="gray"
        />
        <StatusLine
          label="자동매매 미체결"
          value={
            model.autoOpenOrders == null
              ? "—"
              : `${model.autoOpenOrders} / 한도 ${model.autoOpenOrderLimit ?? "—"}`
          }
          tone={
            model.autoOpenOrders != null &&
            model.autoOpenOrderLimit != null &&
            model.autoOpenOrders >= model.autoOpenOrderLimit
              ? "red"
              : "green"
          }
        />
        {model.broker === "UPBIT" ? (
          <>
            <StatusLine
              label="Worker"
              value={model.worker ?? "—"}
              tone={toneFromRuntime(model.worker)}
            />
            <StatusLine
              label="Execution Runner"
              value={model.runner ?? "—"}
              tone={toneFromRuntime(model.runner)}
            />
            <StatusLine
              label="Exit"
              value={model.exitMonitor ?? "—"}
              tone={toneFromRuntime(model.exitMonitor)}
            />
            <StatusLine
              label="Feed"
              value={model.feed ?? "—"}
              tone={toneFromRuntime(model.feed)}
            />
            <StatusLine
              label="Evaluator"
              value={model.evaluator ?? "—"}
              tone={toneFromRuntime(model.evaluator)}
            />
          </>
        ) : (
          <>
            <StatusLine
              label="전략"
              value={model.strategy ?? "—"}
              tone="gray"
            />
            <StatusLine
              label="Readiness"
              value={model.readiness ?? "—"}
              tone={toneFromReadiness(model.readiness)}
            />
          </>
        )}
        <Row gutter={8}>
          <Col span={8}>
            <Statistic
              title="AUTO 보유"
              value={model.autoPositions ?? "—"}
              styles={{ content: { fontSize: 18 } }}
            />
          </Col>
          <Col span={8}>
            <Statistic
              title="오늘 주문"
              value={model.todayOrders ?? "—"}
              styles={{ content: { fontSize: 18 } }}
            />
          </Col>
          <Col span={8}>
            <Statistic
              title="AUTO PnL"
              value={model.autoPnlLabel}
              styles={{ content: { fontSize: 14 } }}
            />
          </Col>
        </Row>
        <Typography.Text type={model.blocker ? "danger" : "secondary"}>
          현재 blocker: {model.blocker ?? "없음"}
        </Typography.Text>
        <Typography.Link href={adminRoutes.accounts}>
          계좌·LIVE WRITE →
        </Typography.Link>
      </Space>
    </Card>
  );
}
