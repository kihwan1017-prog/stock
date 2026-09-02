"use client";

/**
 * KIWOOM 자동매매 Workspace — READ-ONLY 운영 조회.
 * LIVE/ARM WRITE는 계좌 현황만.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  Empty,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useMemo, useState } from "react";

import { adminRoutes } from "@/config/routes";
import {
  ownershipBadgeColor,
  ownershipLabelKo,
} from "@/features/admin/accounts/symbolOwnershipLabels";
import * as adminApi from "@/features/admin/api/adminApi";
import { KiwoomTop10RealPanel } from "@/features/admin/autotrading/KiwoomTop10RealPanel";
import {
  armDisplayLabel,
  getKiwoomLeaseDisplay,
  getKiwoomLeaseTone,
  getKiwoomReadyDisplay,
  getRuntimeStackLabel,
  isArmOn,
  isLiveOn,
  liveDisplayLabel,
  toneFromTriStateOnOff,
} from "@/features/admin/autotrading/kiwoomAutotradingCanonicalStatus";
import { autoTradingStateLabelKo } from "@/features/admin/autotrading/slotStatusLabels";
import {
  toneFromReadiness,
  toneFromRuntime,
  toneToAntdColor,
} from "@/features/admin/autotrading/statusTone";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { resolveOrderTradingKind } from "@/features/admin/autotrading/orderOwnership";
import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";
import { UI_LABEL_KO } from "@/features/shared/display/displayUiLabelsKo";
import { runtimeValueLabelKo } from "@/features/shared/display/tradingDisplayLabelsKo";

const DEFAULT_KIWOOM_UBA = Number(
  process.env.NEXT_PUBLIC_DEFAULT_KIWOOM_UBA_ID ?? "1381",
);

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

function krxPhaseLabelKo(phase: unknown, sessionType: unknown, isTradingDay: unknown): string {
  if (isTradingDay === false) return "휴장";
  const p = String(phase ?? "").toUpperCase();
  const s = String(sessionType ?? "").toUpperCase();
  if (p.includes("REGULAR") || p === "OPEN" || p === "CONTINUOUS") return "장중";
  if (p.includes("PRE") || p === "PREOPEN") return "장전";
  if (p.includes("CLOSE") || p.includes("AFTER") || p === "CLOSED") return "장마감";
  if (s === "HOLIDAY") return "휴장";
  return p || s || "확인 불가 (API 제한)";
}

export default function AdminAutotradingKiwoomPage() {
  const [ubaId, setUbaId] = useState(DEFAULT_KIWOOM_UBA);

  const accountsQ = useQuery({
    queryKey: ["admin", "broker-accounts", "KIWOOM", "workspace"],
    queryFn: () =>
      adminApi.listAdminBrokerAccounts({
        broker_code: "KIWOOM",
        include_inactive: false,
        limit: 50,
      }),
  });

  const ubaOptions = useMemo(() => {
    const root = rec(accountsQ.data);
    const items = Array.isArray(root.items) ? root.items : [];
    const opts = items
      .map((row) => {
        const r = rec(row);
        const id = Number(r.user_broker_account_id ?? r.id ?? 0);
        if (!id) return null;
        return { value: id, label: `UBA ${id}` };
      })
      .filter((x): x is { value: number; label: string } => x != null);
    if (!opts.some((o) => o.value === DEFAULT_KIWOOM_UBA)) {
      opts.unshift({ value: DEFAULT_KIWOOM_UBA, label: `UBA ${DEFAULT_KIWOOM_UBA}` });
    }
    return opts;
  }, [accountsQ.data]);

  const activeUbaId = useMemo(() => {
    if (!ubaOptions.length) return ubaId;
    if (ubaOptions.some((o) => o.value === ubaId)) return ubaId;
    return ubaOptions[0].value;
  }, [ubaOptions, ubaId]);

  const opsQ = useQuery({
    queryKey: ["admin", "uba-ops-status", activeUbaId, "kiwoom-ws"],
    queryFn: () => adminApi.getAdminUbaOpsStatus(activeUbaId),
    enabled: activeUbaId > 0,
    refetchInterval: 20_000,
  });
  const ownQ = useQuery({
    queryKey: ["admin", "symbol-ownership", activeUbaId, "KIWOOM"],
    queryFn: () => adminApi.listAdminSymbolOwnership(activeUbaId, "KIWOOM"),
    enabled: activeUbaId > 0,
    refetchInterval: 30_000,
  });
  const krxQ = useQuery({
    queryKey: ["admin", "market-calendar", "KRX", "kiwoom-ws"],
    queryFn: () => adminApi.getUserMarketCalendarStatus("KRX"),
    refetchInterval: 60_000,
  });
  const ordersQ = useQuery({
    queryKey: ["admin", "orders", "kiwoom", activeUbaId],
    queryFn: () =>
      adminApi.listOrders({ broker_code: "KIWOOM", limit: 100 }),
    refetchInterval: 30_000,
  });

  const ops = rec(opsQ.data);
  const krx = rec(krxQ.data);
  const control = rec(ops.control);
  const liveState = isLiveOn(ops);
  const armState = isArmOn(ops);
  const runtime = String(ops.strategy_runtime ?? control.strategy_runtime ?? "—");
  const readyDisplay = getKiwoomReadyDisplay(ops);
  const activation = String(ops.activation ?? control.activation ?? "—");
  const feed = String(rec(ops.market_feed).status ?? "—");
  const leaseLabel = getKiwoomLeaseDisplay(ops);
  const stackLabel = getRuntimeStackLabel(ops);
  const armExpires = String(ops.arm_expires_at ?? "");
  const blocker =
    String(
      ops.primary_blocker ??
        (Array.isArray(ops.blockers) ? ops.blockers[0] : "") ??
        "",
    ) || null;

  const autoPositions = useMemo(() => {
    return extractRows(rec(ownQ.data).items ?? ownQ.data).filter(
      (r) => String(rec(r).owner).toUpperCase() === "AUTO",
    );
  }, [ownQ.data]);

  const todayAuto = useMemo(() => {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    let orders = 0;
    let fills = 0;
    for (const raw of extractRows(ordersQ.data)) {
      const row = rec(raw);
      const created = Date.parse(String(row.created_at ?? row.requested_at ?? ""));
      if (Number.isFinite(created) && created < start.getTime()) continue;
      if (resolveOrderTradingKind(row).kind !== "AUTO") continue;
      orders += 1;
      const st = String(row.status_code ?? "").toUpperCase();
      if (st.includes("FILL") || Number(row.filled_quantity ?? 0) > 0) fills += 1;
    }
    return { orders, fills };
  }, [ordersQ.data]);

  return (
    <AdminPageShell
      title="키움 자동매매"
      description="KRX 장 상태 · 계좌 활성화 · 실거래(LIVE)/자동주문 승인(ARM) · 자동매매 런타임 조회. 변경은 계좌 현황에서만."
      extra={
        <select
          value={activeUbaId}
          onChange={(e) => setUbaId(Number(e.target.value))}
          style={{ minWidth: 140 }}
        >
          {ubaOptions.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          title="조회 전용 (변경 없음)"
          description={
            <>
              실거래(LIVE)/자동주문 승인(ARM)/자격증명/계좌 활성화 변경 →{" "}
              <Link href={`${adminRoutes.accounts}?broker=KIWOOM`}>계좌 현황</Link>
              . 보유자산(일반매매 포함) →{" "}
              <Link href={adminRoutes.portfolio}>보유자산·손익</Link>. 사전점검 →{" "}
              <Link href={adminRoutes.operationsPreflight}>안전 제어</Link>.
            </>
          }
        />

        <Card
          size="small"
          title="분석·연구"
          extra={
            <Link href={`${adminRoutes.researchData}?market=KIWOOM`}>
              전략·분석에서 자세히 보기
            </Link>
          }
        >
          <Typography.Text type="secondary">
            후보·시장·뉴스·AI·검증은 자동매매가 아니라{" "}
            <Link href={`${adminRoutes.strategyCandidates}?market=KIWOOM`}>
              전략·분석
            </Link>
            에서 관리합니다. 이 화면은 LIVE/ARM/장 세션·런타임 운영 조회용입니다.
          </Typography.Text>
        </Card>

        <Row gutter={[8, 8]}>
          {(
            [
              [
                "KRX 장 상태",
                krxPhaseLabelKo(krx.phase, krx.session_type, krx.is_trading_day),
                toneFromRuntime(
                  String(krx.phase ?? "").includes("REGULAR")
                    ? "RUNNING"
                    : "WAITING_SIGNAL",
                ),
              ],
              [
                "계좌 활성화",
                runtimeValueLabelKo(activation),
                toneFromRuntime(activation),
              ],
              [
                "AUTO",
                autoTradingStateLabelKo(String(ops.auto_trading_state ?? "")),
                toneFromReadiness(String(ops.auto_trading_state ?? "")),
              ],
              [
                UI_LABEL_KO.live,
                liveDisplayLabel(liveState),
                toneFromTriStateOnOff(liveState),
              ],
              [
                UI_LABEL_KO.arm,
                armDisplayLabel(armState),
                toneFromTriStateOnOff(armState),
              ],
              [
                "ARM 만료",
                armExpires
                  ? new Date(armExpires).toLocaleString("ko-KR", {
                      hour12: false,
                    })
                  : "—",
                "gray" as const,
              ],
              [
                "LEASE",
                leaseLabel,
                getKiwoomLeaseTone(ops),
              ],
              [
                "STACK",
                stackLabel,
                toneFromRuntime(
                  stackLabel.includes("RUNNING")
                    ? "RUNNING"
                    : stackLabel === "확인 불가"
                      ? "UNKNOWN"
                      : "WAITING_SIGNAL",
                ),
              ],
              [
                UI_LABEL_KO.runtime,
                runtimeValueLabelKo(runtime),
                toneFromRuntime(runtime),
              ],
              [
                UI_LABEL_KO.feed,
                runtimeValueLabelKo(feed),
                toneFromRuntime(feed),
              ],
              [UI_LABEL_KO.strategy, String(ops.strategy_id ?? "—"), "gray" as const],
              [
                UI_LABEL_KO.readiness,
                readyDisplay.label,
                toneFromReadiness(readyDisplay.toneSource),
              ],
            ] as const
          ).map(([label, value, tone]) => (
            <Col xs={12} sm={8} md={6} lg={4} xl={3} key={label}>
              <Card size="small">
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {label}
                </Typography.Text>
                <div>
                  <Tag color={toneToAntdColor(tone)}>{value}</Tag>
                </div>
              </Card>
            </Col>
          ))}
        </Row>

        <KiwoomTop10RealPanel ubaId={activeUbaId} />

        <Row gutter={16}>
          <Col xs={12} md={6}>
            <Statistic
              title={UI_LABEL_KO.autoPositions}
              value={autoPositions.length}
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="오늘 자동매매 주문" value={todayAuto.orders} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="오늘 자동매매 체결" value={todayAuto.fills} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="전략 일일 손익(PnL)"
              value="—"
              suffix={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  전용 조회 API 미연결
                </Typography.Text>
              }
            />
          </Col>
        </Row>

        <Card size="small" title="주문 한도 V2 / 차단 요인">
          <Typography.Paragraph style={{ marginBottom: 8 }}>
            주문 한도 V2 사용량:{" "}
            <Typography.Text type="secondary">
              전용 조회 필드 없으면 — (백엔드 조회 API 공백)
            </Typography.Text>
          </Typography.Paragraph>
          <Typography.Text type={blocker ? "danger" : "secondary"}>
            현재 차단 요인: {blocker ?? "없음"}
          </Typography.Text>
        </Card>

        <Card size="small" title={`${UI_LABEL_KO.autoPositions} (수동매매 제외)`}>
          {autoPositions.length === 0 ? (
            <Empty description="현재 자동매매 보유 종목이 없습니다." />
          ) : (
            <Table
              size="small"
              pagination={false}
              rowKey={(r) => String(rec(r).symbol)}
              dataSource={autoPositions as Record<string, unknown>[]}
              columns={[
                { title: "종목", dataIndex: "symbol" },
                {
                  title: "구분",
                  dataIndex: "owner",
                  render: (v) => (
                    <Tag color={ownershipBadgeColor(String(v))}>
                      {ownershipLabelKo(String(v))}
                    </Tag>
                  ),
                },
                { title: "수량", dataIndex: "auto_position_qty" },
                {
                  title: "전략",
                  dataIndex: "strategy_id",
                  render: (v) => (v == null ? "—" : `strategy:${v}`),
                },
                {
                  title: "슬롯",
                  dataIndex: "slot_no",
                  render: (v) => (v == null ? "—" : String(v)),
                },
              ]}
            />
          )}
        </Card>
      </Space>
    </AdminPageShell>
  );
}
