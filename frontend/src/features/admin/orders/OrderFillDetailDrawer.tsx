/**
 * 주문 상세 Drawer — 사용자 친화 요약 + Trace/PnL 연결 (READ only).
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Descriptions,
  Drawer,
  Space,
  Tag,
  Timeline,
  Typography,
} from "antd";
import Link from "next/link";

import * as adminApi from "@/features/admin/api/adminApi";
import { resolveOrderTradingKind } from "@/features/admin/autotrading/orderOwnership";
import { AdminJsonCard } from "@/features/admin/components/AdminPanels";
import {
  formatKrw,
  formatPct,
  pnlColor,
} from "@/features/admin/operations-center/autoTradingPerformanceHelpers";
import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";
import {
  orderStatusLabelKo,
  sideLabelKo,
} from "@/features/shared/display/tradingDisplayLabelsKo";
import { adminRoutes } from "@/config/routes";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { cell } from "@/shared/utils/dataHelpers";

import { numOrNull } from "./orderFillMonitoringHelpers";

type Props = {
  orderId: number | null;
  onClose: () => void;
};

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

export function OrderFillDetailDrawer({ orderId, onClose }: Props) {
  const detailQ = useQuery({
    queryKey: queryKeys.admin.orderDetail(orderId ?? 0),
    queryFn: () => adminApi.getOrder(orderId!),
    enabled: orderId != null,
  });

  const detail = rec(detailQ.data);
  const broker = String(detail.broker_code ?? detail.exchange_code ?? "UPBIT")
    .toUpperCase()
    .replace("KRX", "KIWOOM");
  const market = broker === "KIWOOM" ? "KIWOOM" : "UPBIT";
  const ownership = resolveOrderTradingKind(detail);

  const perfQ = useQuery({
    queryKey: queryKeys.admin.autotradingPerformance({
      broker: market,
      period: "ALL",
    }),
    queryFn: () =>
      adminApi.getAdminAutotradingPerformance({
        broker: market as "UPBIT" | "KIWOOM",
        period: "ALL",
      }),
    enabled: orderId != null && ownership.kind === "AUTO",
    staleTime: 60_000,
  });

  const tracesQ = useQuery({
    queryKey: ["admin", "autotrading-traces", market, orderId],
    queryFn: () => adminApi.getAdminAutotradingTraces(market, 100),
    enabled: orderId != null && ownership.kind === "AUTO",
    staleTime: 60_000,
  });

  const trip = (() => {
    if (orderId == null) return null;
    const rows = extractRows(rec(perfQ.data).round_trips).concat(
      extractRows(rec(perfQ.data).recent_closed_trades),
    );
    for (const t of rows) {
      const row = rec(t);
      if (
        Number(row.entry_order_id) === orderId ||
        Number(row.exit_order_id) === orderId
      ) {
        return row;
      }
    }
    return null;
  })();

  const traceListItem = (() => {
    if (orderId == null) return null;
    for (const t of extractRows(tracesQ.data)) {
      const row = rec(t);
      if (
        Number(row.buy_order_id) === orderId ||
        Number(row.sell_order_id) === orderId
      ) {
        return row;
      }
    }
    return null;
  })();

  const traceId = Number(traceListItem?.trace_id ?? traceListItem?.id);
  const traceDetailQ = useQuery({
    queryKey: ["admin", "autotrading-trace", traceId],
    queryFn: () => adminApi.getAdminAutotradingTrace(traceId),
    enabled: Number.isFinite(traceId) && traceId > 0,
  });

  const trace = rec(traceDetailQ.data);
  const summary = rec(trace.summary ?? trace.summary_json);
  const events = extractRows(trace.events);
  const pvId = Number(
    trace.process_version_id ?? traceListItem?.process_version_id,
  );

  return (
    <Drawer
      title={orderId != null ? `주문 상세 #${orderId}` : "주문 상세"}
      open={orderId != null}
      onClose={onClose}
      size={560}
      destroyOnHidden
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        {detailQ.isError ? (
          <Alert type="error" showIcon title={toApiError(detailQ.error).message} />
        ) : null}

        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="종목">
            {cell(detail.symbol)}
          </Descriptions.Item>
          <Descriptions.Item label="시장">
            {cell(detail.broker_code ?? detail.exchange_code)}
          </Descriptions.Item>
          <Descriptions.Item label="자동/수동">
            <Tag>{ownership.labelKo}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="매수/매도">
            {sideLabelKo(
              detail.side_code == null ? null : String(detail.side_code),
            )}
          </Descriptions.Item>
          <Descriptions.Item label="상태">
            {orderStatusLabelKo(
              detail.status_code == null ? null : String(detail.status_code),
            )}
          </Descriptions.Item>
          <Descriptions.Item label="수량">
            {cell(detail.filled_quantity ?? detail.order_quantity)}
          </Descriptions.Item>
          <Descriptions.Item label="가격/체결가">
            {cell(detail.average_fill_price ?? detail.order_price)}
          </Descriptions.Item>
          <Descriptions.Item label="생성">
            {cell(detail.created_at)}
          </Descriptions.Item>
          <Descriptions.Item label="체결">
            {cell(detail.filled_at)}
          </Descriptions.Item>
        </Descriptions>

        <CardishTitle title="청산·손익 (binding SoT)" />
        {trip ? (
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="binding">
              {cell(trip.binding_id)}
            </Descriptions.Item>
            <Descriptions.Item label="청산 사유">
              {cell(trip.exit_reason_label_ko ?? trip.exit_reason_category)}
            </Descriptions.Item>
            <Descriptions.Item label="Gross">
              {formatKrw(numOrNull(trip.gross_pnl))}
            </Descriptions.Item>
            <Descriptions.Item label="수수료">
              {formatKrw(numOrNull(trip.fees))}
            </Descriptions.Item>
            <Descriptions.Item label="Net">
              <span style={{ color: pnlColor(numOrNull(trip.net_pnl)) }}>
                {formatKrw(numOrNull(trip.net_pnl))}
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="수익률">
              {formatPct(numOrNull(trip.return_pct))}
            </Descriptions.Item>
          </Descriptions>
        ) : (
          <Typography.Text type="secondary">
            연결된 CLOSED AUTO binding이 없거나 아직 청산되지 않았습니다.
          </Typography.Text>
        )}

        <CardishTitle title="Decision Trace" />
        {events.length > 0 ? (
          <Timeline
            items={events.map((e) => {
              const ev = rec(e);
              return {
                color:
                  String(ev.status) === "BLOCK" || String(ev.status) === "ERROR"
                    ? "red"
                    : "green",
                content: (
                  <Space orientation="vertical" size={0}>
                    <Typography.Text strong>
                      {String(ev.stage ?? "—")} · {String(ev.status ?? "")}
                    </Typography.Text>
                    <Typography.Text>
                      {String(ev.summary ?? "")}
                    </Typography.Text>
                    {ev.reason_code ? (
                      <Typography.Text type="secondary">
                        {String(ev.reason_code)}
                      </Typography.Text>
                    ) : null}
                  </Space>
                ),
              };
            })}
          />
        ) : (
          <Typography.Text type="secondary">
            연결된 Execution Trace가 없습니다.
          </Typography.Text>
        )}

        {summary.entry_reason || summary.exit_reason ? (
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="진입 이유 (trace)">
              {cell(summary.entry_reason)}
            </Descriptions.Item>
            <Descriptions.Item label="매도 이유 (trace)">
              {cell(summary.exit_reason)}
            </Descriptions.Item>
          </Descriptions>
        ) : null}

        <Space wrap>
          {detail.symbol ? (
            <Link
              href={`${adminRoutes.marketData}?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(String(detail.symbol))}${
                detail.filled_at || detail.created_at
                  ? `&date=${encodeURIComponent(String(detail.filled_at ?? detail.created_at).slice(0, 10))}`
                  : ""
              }`}
            >
              시장 데이터 보기
            </Link>
          ) : null}
          <Link href={adminRoutes.autotradingProcess}>프로세스·버전 화면</Link>
          {Number.isFinite(pvId) && pvId > 0 ? (
            <Link
              href={`${adminRoutes.autotradingProcess}?process_version_id=${pvId}`}
            >
              <Tag color="blue">process_version_id={pvId}</Tag>
            </Link>
          ) : null}
          {Number.isFinite(traceId) && traceId > 0 ? (
            <Link href={`${adminRoutes.autotradingProcess}?trace_id=${traceId}`}>
              <Tag>trace_id={traceId}</Tag>
            </Link>
          ) : null}
        </Space>

        <AdminJsonCard
          title="기술 상세 (주문 원본)"
          loading={detailQ.isLoading}
          error={detailQ.error ? toApiError(detailQ.error) : null}
          data={detailQ.data}
        />
      </Space>
    </Drawer>
  );
}

function CardishTitle({ title }: { title: string }) {
  return (
    <Typography.Title level={5} style={{ margin: 0 }}>
      {title}
    </Typography.Title>
  );
}
