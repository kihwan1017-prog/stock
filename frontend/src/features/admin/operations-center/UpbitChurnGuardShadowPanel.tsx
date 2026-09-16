/**
 * 반복매매 감시 (Churn Guard Shadow) — 성과 탭 보조 패널.
 * SHADOW/관측 전용. REAL 차단 없음. AntD 6 Drawer size API 사용.
 */

"use client";

import {
  Alert,
  Card,
  Col,
  Drawer,
  Empty,
  Grid,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getAdminUpbitChurnGuardEpisode,
  getAdminUpbitChurnGuardStatus,
} from "@/features/admin/api/adminApi";
import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

const CLASS_KO: Record<string, string> = {
  RAPID_REENTRY_CHURN: "빠른 재진입 반복",
  MA_DEAD_CROSS_REENTRY_CHURN: "MA 데드크로스 반복 재진입",
  TRAILING_STOP_REENTRY_CHURN: "트레일링 스탑 반복 재진입",
  REPEATED_LOSS_CHURN: "연속 손실 반복매매",
  FEE_DOMINATED_CHURN: "수수료 주도 손실",
  MICRO_TICK_CHURN: "미세 가격차 반복 손실",
  CANDIDATE_DOMINANCE_CHURN: "후보 독점 재선택",
  ORDER_LIFECYCLE_ANOMALY: "주문 수명주기 이상",
  COMPOSITE_CHURN: "복합 반복매매 패턴",
  UNKNOWN: "원인 미확정",
};

const SEV_COLOR: Record<string, string> = {
  INFO: "blue",
  WARNING: "orange",
  CRITICAL: "red",
};

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

type EpisodeRow = Record<string, unknown>;

type Props = {
  userBrokerAccountId?: number | null;
  enabled?: boolean;
  refreshMs?: number;
};

export function UpbitChurnGuardShadowPanel({
  userBrokerAccountId = 1380,
  enabled = true,
  refreshMs = 60_000,
}: Props) {
  const screens = Grid.useBreakpoint();
  const drawerSize = screens.md ? 720 : "100%";
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(async () => {
    if (!enabled || !userBrokerAccountId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getAdminUpbitChurnGuardStatus(userBrokerAccountId);
      setPayload(rec(data));
    } catch (e) {
      setError(toApiError(e).message);
    } finally {
      setLoading(false);
    }
  }, [enabled, userBrokerAccountId]);

  useEffect(() => {
    void load();
    if (!enabled || refreshMs <= 0) return;
    const t = window.setInterval(() => void load(), refreshMs);
    return () => window.clearInterval(t);
  }, [load, enabled, refreshMs]);

  const episodes = useMemo(() => {
    const rows = extractRows(payload?.active_episodes ?? payload?.episodes);
    return rows.map((r) => rec(r));
  }, [payload]);

  const openDetail = async (eventId: number) => {
    if (!userBrokerAccountId) return;
    setDetailOpen(true);
    setDetailLoading(true);
    setDetail(null);
    try {
      const data = await getAdminUpbitChurnGuardEpisode(
        eventId,
        userBrokerAccountId,
      );
      setDetail(rec(data));
    } catch (e) {
      setDetail({ error: toApiError(e).message });
    } finally {
      setDetailLoading(false);
    }
  };

  const columns: ColumnsType<EpisodeRow> = [
    {
      title: "종목",
      dataIndex: "symbol",
      width: 110,
      render: (v) => String(v ?? "—").replace(/^KRW-/, ""),
    },
    {
      title: "심각도",
      dataIndex: "severity",
      width: 90,
      render: (v) => (
        <Tag color={SEV_COLOR[String(v)] ?? "default"}>{String(v ?? "—")}</Tag>
      ),
    },
    {
      title: "유형",
      dataIndex: "primary_classification",
      ellipsis: true,
      render: (v) => CLASS_KO[String(v)] ?? String(v ?? "—"),
    },
    {
      title: "RT",
      dataIndex: "round_trip_count",
      width: 60,
      render: (v) => num(v) ?? 0,
    },
    {
      title: "연속손실",
      dataIndex: "consecutive_loss_count",
      width: 80,
      render: (v) => num(v) ?? 0,
    },
    {
      title: "순손익",
      dataIndex: "net_pnl",
      width: 100,
      render: (v) => {
        const n = num(v) ?? 0;
        return (
          <Typography.Text type={n < 0 ? "danger" : undefined}>
            {n.toLocaleString("ko-KR", { maximumFractionDigits: 0 })}원
          </Typography.Text>
        );
      },
    },
    {
      title: "주요매도",
      dataIndex: "dominant_exit_reason",
      width: 130,
      ellipsis: true,
      render: (v) => String(v ?? "—"),
    },
    {
      title: "상태",
      dataIndex: "status",
      width: 90,
      render: (v) => <Tag>{String(v ?? "—")}</Tag>,
    },
  ];

  const detailBody = detail?.detail ? rec(detail.detail) : {};
  const timeline = extractRows(detailBody.timeline).map((r) => rec(r));
  const variants = rec(detailBody.threshold_variants);

  return (
    <Card
      size="small"
      title="반복매매 감시"
      loading={loading && !payload}
      extra={
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          SHADOW · REAL 차단 없음
        </Typography.Text>
      }
    >
      <Space orientation="vertical" size={12} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          title="현재는 감시/경고 전용이며 자동 매매를 차단하지 않습니다."
        />
        {error ? (
          <Alert type="error" showIcon title={error} />
        ) : (
          <Row gutter={[12, 12]}>
            <Col xs={12} sm={6}>
              <Statistic
                title="ACTIVE"
                value={num(payload?.active_count) ?? episodes.length}
              />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic title="Mode" value={String(payload?.mode ?? "SHADOW")} />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic
                title="REAL_BLOCK"
                value={payload?.real_block_enabled ? "ON" : "OFF"}
              />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic
                title="Version"
                value={String(payload?.version ?? "—")}
                styles={{ content: { fontSize: 14 } }}
              />
            </Col>
          </Row>
        )}
        {episodes.length === 0 && !error ? (
          <Empty description="현재 ACTIVE 반복매매 이상 없음" />
        ) : (
          <Table<EpisodeRow>
            size="small"
            rowKey={(r) => String(r.event_id)}
            columns={columns}
            dataSource={episodes}
            pagination={false}
            scroll={{ x: 780 }}
            onRow={(r) => ({
              onClick: () => {
                const id = num(r.event_id);
                if (id != null) void openDetail(id);
              },
              style: { cursor: "pointer" },
            })}
          />
        )}
      </Space>

      <Drawer
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        size={drawerSize}
        destroyOnHidden
        title={`반복매매 상세 · ${String(detail?.symbol ?? "").replace(/^KRW-/, "")}`}
      >
        {detailLoading ? (
          <Typography.Text type="secondary">불러오는 중…</Typography.Text>
        ) : detail?.error ? (
          <Alert type="error" showIcon title={String(detail.error)} />
        ) : !detail ? (
          <Empty />
        ) : (
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              title="감시/경고 전용 · 자동매매 차단 없음"
            />
            <Typography.Paragraph>
              유형:{" "}
              {CLASS_KO[String(detail.primary_classification)] ??
                String(detail.primary_classification)}
              <br />
              심각도: {String(detail.severity)} · 상태: {String(detail.status)}
              <br />
              첫 감지: {String(detail.first_observed_at ?? "—")}
              <br />
              최근 관측: {String(detail.last_observed_at ?? "—")}
            </Typography.Paragraph>
            <Typography.Title level={5}>Threshold variants</Typography.Title>
            <Space wrap>
              {Object.entries(variants).map(([k, v]) => {
                const vr = rec(v);
                return (
                  <Tag
                    key={k}
                    color={vr.WOULD_ALERT ? "orange" : "default"}
                  >{`${k}: ${String(vr.decision ?? (vr.WOULD_ALERT ? "WOULD_ALERT" : "NO_ALERT"))}`}</Tag>
                );
              })}
            </Space>
            <Typography.Title level={5}>Timeline</Typography.Title>
            <Table
              size="small"
              rowKey={(_, i) => String(i)}
              pagination={false}
              dataSource={timeline}
              columns={[
                {
                  title: "Exit",
                  dataIndex: "exit_reason",
                  render: (v) => String(v ?? "—"),
                },
                {
                  title: "Hold(s)",
                  dataIndex: "holding_seconds",
                  width: 80,
                  render: (v) =>
                    num(v) != null ? Math.round(num(v)!) : "—",
                },
                {
                  title: "Reentry(s)",
                  dataIndex: "reentry_delay_seconds",
                  width: 90,
                  render: (v) =>
                    num(v) != null ? Math.round(num(v)!) : "—",
                },
                {
                  title: "Net",
                  dataIndex: "net_pnl",
                  width: 90,
                  render: (v) =>
                    (num(v) ?? 0).toLocaleString("ko-KR", {
                      maximumFractionDigits: 0,
                    }),
                },
                {
                  title: "C3",
                  dataIndex: "c3_shadow_decision",
                  width: 80,
                  render: (v) => String(v ?? "—"),
                },
              ]}
            />
          </Space>
        )}
      </Drawer>
    </Card>
  );
}
