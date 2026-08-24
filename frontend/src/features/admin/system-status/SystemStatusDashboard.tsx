"use client";

/**
 * 시스템 상태 — 한글 중심 Dashboard.
 * API contract 변경 없음. Raw JSON은 개발자 Collapse에만.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  List,
  Row,
  Space,
  Tabs,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { buildOpsStatusSummary } from "@/features/admin/accounts/opsStatusSummary";
import { DeveloperRawCollapse } from "@/features/admin/system-status/DeveloperRawCollapse";
import {
  BoolOnOffTag,
  StatusToneTag,
} from "@/features/admin/system-status/StatusToneTag";
import {
  mapBlocker,
  overallStatusKo,
} from "@/features/admin/system-status/statusLabelMap";
import {
  mergeAutotradingBlockers,
  parseOpsLiveArm,
} from "@/features/admin/upbit/upbitAutotradingCanonicalStatus";
import { DEFAULT_UPBIT_AUTOTRADING_UBA_ID } from "@/features/admin/upbit/upbitAutotradingSettingsConfig";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const DEFAULT_KIWOOM_UBA = Number(
  process.env.NEXT_PUBLIC_DEFAULT_KIWOOM_UBA_ID ?? "1381",
);

function dash(v: unknown): string {
  if (v == null || v === "") return "—";
  if (typeof v === "number" && !Number.isFinite(v)) return "—";
  const s = String(v);
  if (s === "undefined" || s === "null" || s === "NaN") return "—";
  if (/^0E-?\d+$/i.test(s)) return "—";
  return s;
}

function formatClock(iso: unknown): string {
  if (iso == null || iso === "") return "—";
  try {
    const d = new Date(String(iso));
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleTimeString("ko-KR", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return "—";
  }
}

function SummaryMetricCard({
  title,
  value,
}: {
  title: string;
  value: ReactNode;
}) {
  return (
    <Card size="small" styles={{ body: { padding: "12px 14px" } }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {title}
      </Typography.Text>
      <div style={{ marginTop: 6 }}>{value}</div>
    </Card>
  );
}

function BrokerOpsSection({
  market,
  ubaId,
  ops,
  readiness,
  overviewBroker,
}: {
  market: "UPBIT" | "KIWOOM";
  ubaId: number;
  ops: unknown;
  readiness: unknown;
  overviewBroker: Record<string, unknown> | null;
}) {
  const summary = buildOpsStatusSummary(ops);
  const liveArm = parseOpsLiveArm(ops);
  const blockers = mergeAutotradingBlockers(ops, readiness).map(mapBlocker);
  const root = asRecord(ops) ?? {};
  const feed = asRecord(root.market_feed) ?? {};
  const unattended = asRecord(root.unattended) ?? {};
  const stack = asRecord(root.runtime_stack) ?? {};
  const readyRoot = asRecord(readiness) ?? {};
  const readyStatus = String(
    readyRoot.status ?? readyRoot.readiness_status ?? summary.autoTradingState,
  );
  const slots = asRecord(root.slots) ?? asRecord(root.slot) ?? {};
  const openOrders =
    root.open_order_count ?? root.open_orders_count ?? root.open_orders;
  const positions =
    root.position_count ?? root.positions_count ?? root.auto_position_count;

  const brokerSlice =
    market === "UPBIT"
      ? asRecord(overviewBroker?.upbit) ?? overviewBroker
      : asRecord(overviewBroker?.kiwoom) ?? overviewBroker;

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }} bordered>
        <Descriptions.Item label="계좌">UBA {ubaId}</Descriptions.Item>
        <Descriptions.Item label="연결">
          <StatusToneTag
            value={
              brokerSlice?.broker_connected === true ||
              brokerSlice?.status === "UP"
                ? "CONNECTED"
                : brokerSlice?.status === "DOWN"
                  ? "DISCONNECTED"
                  : brokerSlice?.status ?? "UNKNOWN"
            }
          />
        </Descriptions.Item>
        <Descriptions.Item label="LIVE">
          <BoolOnOffTag on={liveArm.liveOn} onLabel="ON" offLabel="OFF" />
        </Descriptions.Item>
        <Descriptions.Item label="ARM">
          <BoolOnOffTag on={liveArm.armOn} onLabel="ON" offLabel="OFF" />
        </Descriptions.Item>
        <Descriptions.Item
          label={market === "UPBIT" ? "24시간 승인" : "Market Hours 승인"}
        >
          <StatusToneTag
            value={
              unattended.unattended_enabled
                ? "ACTIVE"
                : root.activation
                  ? String(root.activation)
                  : "OFF"
            }
          />
        </Descriptions.Item>
        <Descriptions.Item label="자동연장">
          <BoolOnOffTag
            on={Boolean(
              unattended.auto_renew_enabled ?? unattended.auto_renew,
            )}
            onLabel="ON"
            offLabel="OFF"
          />
        </Descriptions.Item>
        <Descriptions.Item label="Runtime">
          <StatusToneTag value={root.runtime ?? stack.runtime} />
        </Descriptions.Item>
        <Descriptions.Item label="Runner">
          <StatusToneTag value={root.runner ?? stack.runner} />
        </Descriptions.Item>
        <Descriptions.Item label="Feed">
          <StatusToneTag value={feed.status ?? feed.feed_status ?? "UNKNOWN"} />
        </Descriptions.Item>
        <Descriptions.Item label="Worker">
          <StatusToneTag
            value={root.outbox_worker ?? stack.outbox_worker ?? "UNKNOWN"}
          />
        </Descriptions.Item>
        {market === "UPBIT" ? (
          <Descriptions.Item label="Slots">
            {dash(
              slots.used != null && slots.max != null
                ? `${slots.used} / ${slots.max}`
                : slots.label ?? stack.label,
            )}
          </Descriptions.Item>
        ) : null}
        {market === "KIWOOM" ? (
          <Descriptions.Item label="KRX 상태">
            <StatusToneTag
              value={
                root.krx_session ??
                root.market_session ??
                feed.krx_session ??
                feed.session_phase ??
                "UNKNOWN"
              }
            />
          </Descriptions.Item>
        ) : null}
        {market === "KIWOOM" ? (
          <Descriptions.Item label="Warmup">
            {dash(
              root.warmup_label ??
                root.warmup_status ??
                feed.warmup_status ??
                "—",
            )}
          </Descriptions.Item>
        ) : null}
        {market === "KIWOOM" ? (
          <Descriptions.Item label="익일 자동시작">
            <BoolOnOffTag
              on={Boolean(
                root.next_day_auto_start ??
                  root.next_day_autostart ??
                  unattended.next_day_auto_start,
              )}
              onLabel="ON"
              offLabel="OFF"
            />
          </Descriptions.Item>
        ) : null}
        <Descriptions.Item label="미체결">
          {dash(openOrders)}
        </Descriptions.Item>
        <Descriptions.Item
          label={market === "UPBIT" ? "보유 AUTO" : "Position"}
        >
          {dash(positions)}
        </Descriptions.Item>
        <Descriptions.Item label="준비상태" span={2}>
          <StatusToneTag value={readyStatus} />
        </Descriptions.Item>
      </Descriptions>

      <Card size="small" title="자동매매 준비 · 차단 원인">
        {blockers.length === 0 ? (
          <Alert
            type="success"
            showIcon
            title="자동매매 가능"
            description="현재 확인된 차단 원인이 없습니다. (조회 시점 기준)"
          />
        ) : (
          <Alert
            type="warning"
            showIcon
            title="확인 필요"
            description={
              <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                {blockers.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            }
          />
        )}
      </Card>

      {market === "UPBIT" ? (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          연구(CLEAN) 상세는{" "}
          <Link href={`${adminRoutes.researchData}?market=UPBIT`}>
            연구 데이터
          </Link>
          에서 확인하세요.
        </Typography.Paragraph>
      ) : (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          익일 자동시작·Warmup 상세는{" "}
          <Link href={adminRoutes.autotradingKiwoom}>키움 자동매매</Link>에서
          확인하세요.
        </Typography.Paragraph>
      )}
    </Space>
  );
}

export function SystemStatusDashboard() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState("all");

  const overview = useQuery({
    queryKey: queryKeys.system.monitoringOverview({}),
    queryFn: () => adminApi.getMonitoringOverview({ evaluate_alerts: true }),
    refetchInterval: 20_000,
  });
  const live = useQuery({
    queryKey: queryKeys.system.healthLive(),
    queryFn: adminApi.getHealthLive,
    refetchInterval: 20_000,
  });
  const ready = useQuery({
    queryKey: queryKeys.system.healthReady(),
    queryFn: adminApi.getHealthReady,
    refetchInterval: 20_000,
  });
  const health = useQuery({
    queryKey: queryKeys.system.health(),
    queryFn: adminApi.getHealth,
    refetchInterval: 30_000,
  });
  const version = useQuery({
    queryKey: queryKeys.system.version(),
    queryFn: adminApi.getVersion,
  });
  const alerts = useQuery({
    queryKey: queryKeys.system.monitoringAlerts(),
    queryFn: () => adminApi.getMonitoringAlerts({ limit: 10 }),
    refetchInterval: 30_000,
  });
  const upbitOps = useQuery({
    queryKey: ["admin", "uba-ops-status", DEFAULT_UPBIT_AUTOTRADING_UBA_ID, "sys"],
    queryFn: () =>
      adminApi.getAdminUbaOpsStatus(DEFAULT_UPBIT_AUTOTRADING_UBA_ID),
    refetchInterval: 20_000,
    retry: false,
  });
  const kiwoomOps = useQuery({
    queryKey: ["admin", "uba-ops-status", DEFAULT_KIWOOM_UBA, "sys"],
    queryFn: () => adminApi.getAdminUbaOpsStatus(DEFAULT_KIWOOM_UBA),
    refetchInterval: 20_000,
    retry: false,
  });
  const upbitReady = useQuery({
    queryKey: ["admin", "uba-readiness", DEFAULT_UPBIT_AUTOTRADING_UBA_ID, "sys"],
    queryFn: () =>
      adminApi.getAdminUbaAutotradingReadiness(DEFAULT_UPBIT_AUTOTRADING_UBA_ID),
    refetchInterval: 30_000,
    retry: false,
  });
  const kiwoomReady = useQuery({
    queryKey: ["admin", "uba-readiness", DEFAULT_KIWOOM_UBA, "sys"],
    queryFn: () => adminApi.getAdminUbaAutotradingReadiness(DEFAULT_KIWOOM_UBA),
    refetchInterval: 30_000,
    retry: false,
  });

  const ov = asRecord(overview.data);
  const system = asRecord(ov?.system);
  const database = asRecord(ov?.database);
  const broker = asRecord(ov?.broker);
  const scheduler = asRecord(ov?.scheduler);
  const risk = asRecord(ov?.risk);
  const liveObj = asRecord(live.data);
  const readyObj = asRecord(ready.data);
  const healthObj = asRecord(health.data);
  const components = asRecord(healthObj?.components) ?? {};
  const versionObj = asRecord(version.data);

  const overall = overallStatusKo(ov?.status ?? liveObj?.status ?? healthObj?.status);

  const lastUpdatedCandidates = [
    ov?.generated_at,
    ov?.updated_at,
    system?.checked_at,
    overview.dataUpdatedAt
      ? new Date(overview.dataUpdatedAt).toISOString()
      : null,
  ];
  let lastUpdated = "—";
  for (const c of lastUpdatedCandidates) {
    if (c) {
      lastUpdated = formatClock(c);
      break;
    }
  }
  if (lastUpdated === "—") {
    lastUpdated = formatClock(new Date().toISOString());
  }

  const loading = overview.isLoading && !overview.data;
  const hasError = overview.isError && !overview.data;

  const alertRoot = asRecord(alerts.data);
  const alertItems = Array.isArray(alertRoot?.items)
    ? (alertRoot.items as unknown[])
    : Array.isArray(alerts.data)
      ? (alerts.data as unknown[])
      : [];
  const recentEvents = alertItems.slice(0, 8).map((row, idx) => {
    const r = asRecord(row) ?? {};
    const detail = asRecord(r.detail) ?? {};
    return {
      key: String(r.audit_event_id ?? idx),
      time: formatClock(r.created_at),
      text:
        dash(detail.message ?? detail.rule ?? r.event_type) ||
        "모니터링 이벤트",
    };
  });

  const refreshAll = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.system.monitoringOverview({}),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.system.healthLive(),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.system.healthReady(),
    });
    void queryClient.invalidateQueries({
      queryKey: ["admin", "uba-ops-status"],
    });
  };

  if (loading) {
    return (
      <Typography.Text type="secondary">
        시스템 상태를 불러오는 중입니다.
      </Typography.Text>
    );
  }

  if (hasError) {
    return (
      <Alert
        type="error"
        showIcon
        title="시스템 상태를 불러오지 못했습니다."
        description={toApiError(overview.error).message}
        action={
          <Button size="small" onClick={refreshAll}>
            새로고침
          </Button>
        }
      />
    );
  }

  if (!overview.data && !live.data) {
    return (
      <Empty description="표시할 상태 정보가 없습니다." />
    );
  }

  const commonPanel = (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }} bordered>
        <Descriptions.Item label="백엔드">
          <StatusToneTag value={liveObj?.status ?? system?.server_status} />
        </Descriptions.Item>
        <Descriptions.Item label="데이터베이스">
          <StatusToneTag
            value={
              database?.status ??
              asRecord(components.database)?.status ??
              "UNKNOWN"
            }
          />
        </Descriptions.Item>
        <Descriptions.Item label="Scheduler">
          <StatusToneTag
            value={
              scheduler?.status ??
              asRecord(components.scheduler)?.status ??
              "UNKNOWN"
            }
          />
        </Descriptions.Item>
        <Descriptions.Item label="Live 프로브">
          <StatusToneTag value={liveObj?.status} />
        </Descriptions.Item>
        <Descriptions.Item label="Ready 프로브">
          <StatusToneTag value={readyObj?.status} />
        </Descriptions.Item>
        <Descriptions.Item label="Kill Switch">
          <StatusToneTag
            value={
              risk?.kill_switch_active === true ||
              risk?.kill_active === true
                ? "ACTIVE"
                : "INACTIVE"
            }
          />
        </Descriptions.Item>
        <Descriptions.Item label="환경">
          {dash(system?.environment ?? versionObj?.environment)}
        </Descriptions.Item>
        <Descriptions.Item label="버전">
          {dash(system?.version ?? versionObj?.version)}
        </Descriptions.Item>
        <Descriptions.Item label="최근 갱신">
          {lastUpdated}
        </Descriptions.Item>
      </Descriptions>
    </Space>
  );

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card
        size="small"
        title="전체 상태"
        extra={
          <Space wrap>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              마지막 갱신: {lastUpdated}
            </Typography.Text>
            <Button size="small" onClick={refreshAll}>
              새로고침
            </Button>
          </Space>
        }
      >
        <Space wrap size={8}>
          <Tag
            color={
              overall.tone === "success"
                ? "success"
                : overall.tone === "warning"
                  ? "warning"
                  : overall.tone === "error"
                    ? "error"
                    : "default"
            }
            style={{ fontSize: 14, padding: "4px 10px" }}
          >
            ● {overall.title}
          </Tag>
          <Typography.Text type="secondary">
            조회 전용 · 이 화면에서 LIVE/ARM/Runtime을 변경하지 않습니다
          </Typography.Text>
        </Space>
      </Card>

      <Row gutter={[12, 12]}>
        <Col xs={12} sm={8} md={6} lg={4}>
          <SummaryMetricCard
            title="백엔드"
            value={<StatusToneTag value={liveObj?.status ?? "UNKNOWN"} />}
          />
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <SummaryMetricCard
            title="데이터베이스"
            value={<StatusToneTag value={database?.status ?? "UNKNOWN"} />}
          />
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <SummaryMetricCard
            title="Worker"
            value={
              <StatusToneTag
                value={
                  asRecord(upbitOps.data)?.outbox_worker ??
                  asRecord(asRecord(upbitOps.data)?.runtime_stack)?.outbox_worker ??
                  "UNKNOWN"
                }
              />
            }
          />
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <SummaryMetricCard
            title="Feed"
            value={
              <StatusToneTag
                value={
                  asRecord(asRecord(upbitOps.data)?.market_feed)?.status ??
                  asRecord(asRecord(kiwoomOps.data)?.market_feed)?.status ??
                  "UNKNOWN"
                }
              />
            }
          />
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <SummaryMetricCard
            title="Runtime"
            value={
              <StatusToneTag
                value={
                  asRecord(upbitOps.data)?.runtime ??
                  asRecord(kiwoomOps.data)?.runtime ??
                  "UNKNOWN"
                }
              />
            }
          />
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <SummaryMetricCard
            title="Runner"
            value={
              <StatusToneTag
                value={
                  asRecord(upbitOps.data)?.runner ??
                  asRecord(kiwoomOps.data)?.runner ??
                  "UNKNOWN"
                }
              />
            }
          />
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <SummaryMetricCard
            title="준비상태"
            value={<StatusToneTag value={readyObj?.status ?? overall.title} />}
          />
        </Col>
      </Row>

      <Tabs
        activeKey={tab}
        onChange={setTab}
        size="small"
        items={[
          {
            key: "all",
            label: "전체",
            children: (
              <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                <Card size="small" title="공통 시스템">
                  {commonPanel}
                </Card>
                <Card size="small" title="업비트">
                  {upbitOps.isError ? (
                    <Alert
                      type="warning"
                      showIcon
                      title="업비트 상태를 불러오지 못했습니다"
                      description={toApiError(upbitOps.error).message}
                    />
                  ) : (
                    <BrokerOpsSection
                      market="UPBIT"
                      ubaId={DEFAULT_UPBIT_AUTOTRADING_UBA_ID}
                      ops={upbitOps.data}
                      readiness={upbitReady.data}
                      overviewBroker={broker}
                    />
                  )}
                </Card>
                <Card size="small" title="키움">
                  {kiwoomOps.isError ? (
                    <Alert
                      type="warning"
                      showIcon
                      title="키움 상태를 불러오지 못했습니다"
                      description={toApiError(kiwoomOps.error).message}
                    />
                  ) : (
                    <BrokerOpsSection
                      market="KIWOOM"
                      ubaId={DEFAULT_KIWOOM_UBA}
                      ops={kiwoomOps.data}
                      readiness={kiwoomReady.data}
                      overviewBroker={broker}
                    />
                  )}
                </Card>
              </Space>
            ),
          },
          {
            key: "common",
            label: "공통",
            children: (
              <Card size="small" title="공통 시스템">
                {commonPanel}
              </Card>
            ),
          },
          {
            key: "upbit",
            label: "업비트",
            children: (
              <Card size="small" title="업비트">
                <BrokerOpsSection
                  market="UPBIT"
                  ubaId={DEFAULT_UPBIT_AUTOTRADING_UBA_ID}
                  ops={upbitOps.data}
                  readiness={upbitReady.data}
                  overviewBroker={broker}
                />
              </Card>
            ),
          },
          {
            key: "kiwoom",
            label: "키움",
            children: (
              <Card size="small" title="키움">
                <BrokerOpsSection
                  market="KIWOOM"
                  ubaId={DEFAULT_KIWOOM_UBA}
                  ops={kiwoomOps.data}
                  readiness={kiwoomReady.data}
                  overviewBroker={broker}
                />
              </Card>
            ),
          },
        ]}
      />

      <Card size="small" title="최근 중요 이벤트">
        {recentEvents.length === 0 ? (
          <Typography.Text type="secondary">
            표시할 최근 이벤트가 없습니다.
          </Typography.Text>
        ) : (
          <List
            size="small"
            dataSource={recentEvents}
            renderItem={(item) => (
              <List.Item>
                <Typography.Text type="secondary" style={{ width: 72 }}>
                  {item.time}
                </Typography.Text>
                <Typography.Text>{item.text}</Typography.Text>
              </List.Item>
            )}
          />
        )}
      </Card>

      <DeveloperRawCollapse
        title="개발자 상세 보기"
        endpoint="GET /api/v1/monitoring/overview · /health · ops-status"
        updatedAt={lastUpdated}
        data={{
          overview: overview.data,
          health_live: live.data,
          health_ready: ready.data,
          health: health.data,
          version: version.data,
          upbit_ops: upbitOps.data,
          kiwoom_ops: kiwoomOps.data,
          alerts: alerts.data,
        }}
      />
    </Space>
  );
}
