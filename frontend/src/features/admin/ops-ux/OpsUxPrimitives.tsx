"use client";

/**
 * 운영 UX 공통 KPI / Summary / Funnel — Ant Design 기반, 장식용 차트 금지.
 */

import { Card, Col, Progress, Row, Space, Statistic, Tag, Typography } from "antd";
import Link from "next/link";
import type { ReactNode } from "react";

type Tone = "success" | "warning" | "error" | "default" | "processing";

const TONE_COLOR: Record<Tone, string | undefined> = {
  success: "success",
  warning: "warning",
  error: "error",
  default: undefined,
  processing: "processing",
};

export function OpsKpiCard(props: {
  title: string;
  value: ReactNode;
  hint?: string;
}) {
  const numeric =
    typeof props.value === "number" || typeof props.value === "string";
  return (
    <Card size="small" styles={{ body: { padding: "12px 16px" } }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {props.title}
      </Typography.Text>
      <div style={{ fontSize: 20, fontWeight: 600, marginTop: 4 }}>
        {numeric ? (
          <Statistic value={props.value as string | number} styles={{ content: { fontSize: 20 } }} />
        ) : (
          props.value
        )}
      </div>
      {props.hint ? (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {props.hint}
        </Typography.Text>
      ) : null}
    </Card>
  );
}

export function StatusSummaryCard(props: {
  title: string;
  statusLabel: string;
  tone?: Tone;
  description?: string;
  extra?: ReactNode;
  href?: string;
  linkLabel?: string;
}) {
  const body = (
    <Space orientation="vertical" size={4} style={{ width: "100%" }}>
      <Space wrap>
        <Typography.Text strong>{props.title}</Typography.Text>
        <Tag color={TONE_COLOR[props.tone ?? "default"]}>{props.statusLabel}</Tag>
      </Space>
      {props.description ? (
        <Typography.Text type="secondary" style={{ fontSize: 13 }}>
          {props.description}
        </Typography.Text>
      ) : null}
      {props.extra}
      {props.href ? (
        <Link href={props.href}>{props.linkLabel ?? "자세히 보기 →"}</Link>
      ) : null}
    </Space>
  );
  return (
    <Card size="small" styles={{ body: { padding: 16 } }}>
      {body}
    </Card>
  );
}

export function SummaryLinkCard(props: {
  title: string;
  value: ReactNode;
  href: string;
  linkLabel?: string;
  hint?: string;
}) {
  return (
    <Card size="small" styles={{ body: { padding: 16 } }}>
      <Space orientation="vertical" size={6} style={{ width: "100%" }}>
        <Typography.Text type="secondary">{props.title}</Typography.Text>
        <Typography.Title level={4} style={{ margin: 0 }}>
          {props.value}
        </Typography.Title>
        {props.hint ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {props.hint}
          </Typography.Text>
        ) : null}
        <Link href={props.href}>{props.linkLabel ?? "자세히 보기 →"}</Link>
      </Space>
    </Card>
  );
}

export function MetricProgress(props: {
  label: string;
  used: number;
  limit: number;
  formatValue?: (n: number) => string;
}) {
  const limit = props.limit > 0 ? props.limit : 1;
  const pct = Math.min(100, Math.round((props.used / limit) * 100));
  const fmt = props.formatValue ?? ((n: number) => String(n));
  const status = pct >= 90 ? "exception" : pct >= 70 ? "active" : "success";
  return (
    <div style={{ marginBottom: 8 }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }}>
        <Typography.Text>{props.label}</Typography.Text>
        <Typography.Text type="secondary">
          {fmt(props.used)} / {fmt(props.limit)}
        </Typography.Text>
      </Space>
      <Progress percent={pct} size="small" status={status} showInfo={false} />
    </div>
  );
}

export type FunnelStep = {
  key: string;
  label: string;
  count: number;
};

/** Pipeline Funnel — 단계 수와 전환율 표시 (장식용 아님) */
export function OpsFunnelSteps(props: { title?: string; steps: FunnelStep[] }) {
  const steps = props.steps.filter((s) => Number.isFinite(s.count));
  if (steps.length === 0) {
    return (
      <Card size="small" title={props.title ?? "거래 흐름"}>
        <Typography.Text type="secondary">표시할 흐름 데이터가 없습니다.</Typography.Text>
      </Card>
    );
  }
  const max = Math.max(...steps.map((s) => s.count), 1);
  return (
    <Card size="small" title={props.title ?? "거래 흐름 (오늘 누적)"}>
      <Space orientation="vertical" size={8} style={{ width: "100%" }}>
        {steps.map((step, idx) => {
          const prev = idx > 0 ? steps[idx - 1].count : null;
          const conv =
            prev != null && prev > 0
              ? `${Math.round((step.count / prev) * 100)}%`
              : null;
          return (
            <div key={step.key}>
              <Space style={{ width: "100%", justifyContent: "space-between" }}>
                <Typography.Text>
                  {step.label}
                  {conv ? (
                    <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                      ← {conv}
                    </Typography.Text>
                  ) : null}
                </Typography.Text>
                <Typography.Text strong>{step.count.toLocaleString("ko-KR")}</Typography.Text>
              </Space>
              <Progress
                percent={Math.round((step.count / max) * 100)}
                showInfo={false}
                size="small"
                strokeColor="#1677ff"
              />
            </div>
          );
        })}
      </Space>
    </Card>
  );
}

export function OpsKpiRow(props: { items: Array<{ title: string; value: ReactNode; hint?: string }> }) {
  return (
    <Row gutter={[12, 12]}>
      {props.items.map((item) => (
        <Col xs={12} sm={8} md={6} lg={4} key={item.title}>
          <OpsKpiCard title={item.title} value={item.value} hint={item.hint} />
        </Col>
      ))}
    </Row>
  );
}
