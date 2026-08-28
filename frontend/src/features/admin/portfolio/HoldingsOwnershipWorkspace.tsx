"use client";

/**
 * 보유자산·손익 — 시장(UPBIT/KIWOOM) + ownership 분리 조회.
 * WRITE 없음. symbol-ownership + ops positions 조합.
 */

import { useQueries, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Checkbox,
  Col,
  Empty,
  Radio,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  theme,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import Link from "next/link";
import { useMemo, useState } from "react";

import { adminRoutes } from "@/config/routes";
import {
  ownershipBadgeColor,
  ownershipLabelKo,
  ownershipMatchesHoldingsFilter,
  type HoldingsOwnerFilter,
} from "@/features/admin/accounts/symbolOwnershipLabels";
import * as adminApi from "@/features/admin/api/adminApi";
import { SummaryLinkCard } from "@/features/admin/ops-ux";
import {
  assetDisplayName,
  dataQualityLabelKo,
  formatOptionalKrw,
  formatOptionalPnl,
  formatOptionalPct,
  resolveHoldingMetrics,
  type DataQuality,
  type MarketFilter,
} from "@/features/admin/portfolio/holdingsMetrics";
import {
  resolveHoldingOwner,
  shouldIncludeHoldingPositionRow,
  shouldShowHoldingByQuantity,
} from "@/features/admin/portfolio/holdingsRowPolicy";
import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";
import {
  formatQuantityKo,
  isEffectivelyZero,
  parseDecimalSafe,
} from "@/shared/utils/numericFormatKo";

const DEFAULT_UPBIT_UBA = Number(
  process.env.NEXT_PUBLIC_DEFAULT_UPBIT_UBA_ID ?? "1380",
);
const DEFAULT_KIWOOM_UBA = Number(
  process.env.NEXT_PUBLIC_DEFAULT_KIWOOM_UBA_ID ?? "1381",
);

type HoldingRow = {
  key: string;
  broker: string;
  symbol: string;
  name: string | null;
  userBrokerAccountId: number | null;
  owner: string;
  quantity: unknown;
  avgPriceDisplay: string;
  currentPriceDisplay: string;
  purchaseDisplay: string;
  evalDisplay: string;
  unrealizedDisplay: string;
  returnDisplay: string;
  evalSort: number;
  unrealizedSort: number;
  quantitySort: number;
  strategy: string;
  manageLabel: string;
  dataQuality: DataQuality;
  snapshotAt: string | null;
};

function holdingRowKey(
  broker: string,
  symbol: string,
  userBrokerAccountId?: number | null,
): string {
  const uba =
    userBrokerAccountId != null && userBrokerAccountId > 0
      ? String(userBrokerAccountId)
      : "na";
  return `${broker}-${symbol}-${uba}`;
}

function targetUbaForBroker(
  broker: string,
  ubaIds: { upbit: number; kiwoom: number },
): number {
  if (broker === "UPBIT") return ubaIds.upbit;
  if (broker === "KIWOOM") return ubaIds.kiwoom;
  return 0;
}

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

function PnLText({
  text,
  value,
}: {
  text: string;
  value: number | null;
}) {
  const { token } = theme.useToken();
  if (value == null || !Number.isFinite(value)) {
    return <Typography.Text type="secondary">{text}</Typography.Text>;
  }
  const color =
    value > 0 ? token.colorSuccess : value < 0 ? token.colorError : undefined;
  return <Typography.Text style={{ color }}>{text}</Typography.Text>;
}

export function HoldingsOwnershipWorkspace() {
  const [market, setMarket] = useState<MarketFilter>("ALL");
  const [filter, setFilter] = useState<HoldingsOwnerFilter>("ALL");
  const [includeZeroQty, setIncludeZeroQty] = useState(false);

  const accountsQ = useQuery({
    queryKey: ["admin", "broker-accounts", "holdings"],
    queryFn: () =>
      adminApi.listAdminBrokerAccounts({ include_inactive: false, limit: 100 }),
  });

  const ubaIds = useMemo(() => {
    const root = rec(accountsQ.data);
    const items = Array.isArray(root.items)
      ? root.items
      : Array.isArray(accountsQ.data)
        ? (accountsQ.data as unknown[])
        : [];
    let upbit = DEFAULT_UPBIT_UBA;
    let kiwoom = DEFAULT_KIWOOM_UBA;
    for (const row of items) {
      const r = rec(row);
      const id = Number(r.user_broker_account_id ?? r.id ?? 0);
      const broker = String(r.broker_code ?? "").toUpperCase();
      if (broker === "UPBIT" && id) upbit = id;
      if (broker === "KIWOOM" && id) kiwoom = id;
    }
    return { upbit, kiwoom };
  }, [accountsQ.data]);

  const ownershipQs = useQueries({
    queries: [
      {
        queryKey: ["admin", "symbol-ownership", ubaIds.upbit, "UPBIT"],
        queryFn: () =>
          adminApi.listAdminSymbolOwnership(ubaIds.upbit, "UPBIT"),
        enabled: ubaIds.upbit > 0,
      },
      {
        queryKey: ["admin", "symbol-ownership", ubaIds.kiwoom, "KIWOOM"],
        queryFn: () =>
          adminApi.listAdminSymbolOwnership(ubaIds.kiwoom, "KIWOOM"),
        enabled: ubaIds.kiwoom > 0,
      },
    ],
  });

  const positionsQ = useQuery({
    queryKey: ["admin", "ops-positions", "holdings"],
    queryFn: () => adminApi.getOpsDashboardPositions(),
    refetchInterval: 20_000,
  });

  const ownerMap = useMemo(() => {
    const map = new Map<string, Record<string, unknown>>();
    const pairs: [string, number][] = [
      ["UPBIT", 0],
      ["KIWOOM", 1],
    ];
    for (const [broker, idx] of pairs) {
      const items = extractRows(
        rec(ownershipQs[idx]?.data).items ?? ownershipQs[idx]?.data,
      );
      for (const raw of items) {
        const o = rec(raw);
        const sym = String(o.symbol ?? "").toUpperCase();
        if (!sym) continue;
        map.set(`${broker}:${sym}`, o);
      }
    }
    return map;
  }, [ownershipQs]);

  const rows: HoldingRow[] = useMemo(() => {
    const posRows = extractRows(
      rec(positionsQ.data).positions ?? positionsQ.data,
    );
    const out: HoldingRow[] = [];
    const bestBySymbol = new Map<string, Record<string, unknown>>();

    for (const raw of posRows) {
      const p = rec(raw);
      const broker = String(p.broker_code ?? "").toUpperCase();
      const symbol = String(p.symbol ?? "").toUpperCase();
      if (!broker || !symbol) continue;
      if (market !== "ALL" && broker !== market) continue;

      const targetUba = targetUbaForBroker(broker, ubaIds);
      const rowUba = Number(p.user_broker_account_id ?? 0) || null;
      if (targetUba > 0 && rowUba != null && rowUba !== targetUba) continue;

      const dedupeKey = `${broker}:${symbol}`;
      const prev = bestBySymbol.get(dedupeKey);
      if (prev) {
        const prevAt = String(prev.snapshot_time ?? "");
        const nextAt = String(p.snapshot_time ?? "");
        if (prevAt && nextAt && nextAt <= prevAt) continue;
      }
      bestBySymbol.set(dedupeKey, p);
    }

    const pushRow = (
      broker: string,
      symbol: string,
      rowUba: number | null,
      owner: string,
      qtyRaw: unknown,
      p: Record<string, unknown>,
      own: Record<string, unknown>,
    ) => {
      if (!ownershipMatchesHoldingsFilter(owner, filter)) return;
      if (!shouldShowHoldingByQuantity(qtyRaw, includeZeroQty)) return;

      const metrics = resolveHoldingMetrics({
        quantity: qtyRaw,
        brokerAvgPrice: p.average_price,
        autoEntryPrice: own.auto_entry_price,
        currentPrice: p.current_price,
        brokerEvalAmount: p.evaluation_amount,
        brokerUnrealized: p.unrealized_pnl,
        brokerPurchaseAmount: p.purchase_amount,
        owner,
      });

      const nameRaw = p.name != null ? String(p.name) : null;
      out.push({
        key: holdingRowKey(broker, symbol, rowUba),
        broker,
        symbol,
        name: nameRaw,
        userBrokerAccountId: rowUba,
        owner,
        quantity: qtyRaw,
        avgPriceDisplay: metrics.avgPriceMissing
          ? "확인 불가"
          : formatOptionalKrw(metrics.avgPrice),
        currentPriceDisplay: formatOptionalKrw(metrics.currentPrice),
        purchaseDisplay: formatOptionalKrw(metrics.purchaseAmount),
        evalDisplay: formatOptionalKrw(metrics.valuationAmount),
        unrealizedDisplay: formatOptionalPnl(metrics.unrealizedPnl),
        returnDisplay: formatOptionalPct(metrics.returnPct),
        evalSort: metrics.valuationAmount ?? -1,
        unrealizedSort: metrics.unrealizedPnl ?? Number.NEGATIVE_INFINITY,
        quantitySort: metrics.quantity ?? 0,
        strategy:
          own.strategy_id != null ? `strategy:${own.strategy_id}` : "—",
        // CLOSED binding + broker 잔량 → 일반/기타로 명시
        manageLabel:
          owner === "MANUAL"
            ? "일반/기타 보유"
            : ownershipLabelKo(owner),
        dataQuality: metrics.dataQuality,
        snapshotAt:
          p.snapshot_time != null ? String(p.snapshot_time) : null,
      });
    };

    for (const p of bestBySymbol.values()) {
      const broker = String(p.broker_code ?? "").toUpperCase();
      const symbol = String(p.symbol ?? "").toUpperCase();
      const rowUba = Number(p.user_broker_account_id ?? 0) || null;
      const ownEntry = ownerMap.get(`${broker}:${symbol}`);
      const hasOwnershipEntry = ownEntry != null;
      const own = ownEntry ?? {};
      if (!shouldIncludeHoldingPositionRow(p.quantity, hasOwnershipEntry)) {
        continue;
      }
      const owner = resolveHoldingOwner(
        own.owner as string | undefined,
        hasOwnershipEntry,
        p.quantity,
      );
      const qtyRaw =
        owner === "AUTO"
          ? (own.auto_position_qty ?? p.quantity)
          : (own.manual_position_qty ?? p.quantity);
      pushRow(broker, symbol, rowUba, owner, qtyRaw, p, own);
    }

    for (const [mapKey, own] of ownerMap) {
      const owner = String(own.owner ?? "").toUpperCase();
      if (!ownershipMatchesHoldingsFilter(owner, filter)) continue;
      if (owner === "FREE") continue;
      const [broker, symbol] = mapKey.split(":");
      if (market !== "ALL" && broker !== market) continue;
      if (out.some((r) => r.broker === broker && r.symbol === symbol)) continue;
      const qtyRaw =
        owner === "AUTO" ? own.auto_position_qty : own.manual_position_qty;
      if (isEffectivelyZero(qtyRaw) && owner !== "AUTO_EXCLUDED") {
        if (!includeZeroQty) continue;
      }
      const rowUba = targetUbaForBroker(broker, ubaIds) || null;
      pushRow(broker, symbol, rowUba, owner, qtyRaw, {}, own);
    }

    out.sort((a, b) => {
      if (a.quantitySort <= 0 && b.quantitySort > 0) return 1;
      if (a.quantitySort > 0 && b.quantitySort <= 0) return -1;
      return b.evalSort - a.evalSort;
    });
    return out;
  }, [
    filter,
    includeZeroQty,
    market,
    ownerMap,
    positionsQ.data,
    ubaIds,
  ]);

  const summaries = useMemo(() => {
    const empty = {
      eval: 0,
      unreal: 0,
      cost: 0,
      count: 0,
      lastAt: null as string | null,
    };
    const by: Record<"UPBIT" | "KIWOOM", typeof empty> = {
      UPBIT: { ...empty },
      KIWOOM: { ...empty },
    };
    for (const r of rows) {
      const bucket = r.broker === "KIWOOM" ? by.KIWOOM : by.UPBIT;
      const ev = r.evalSort > 0 ? r.evalSort : 0;
      const u =
        r.unrealizedSort === Number.NEGATIVE_INFINITY ? 0 : r.unrealizedSort;
      bucket.eval += Number.isFinite(ev) ? ev : 0;
      bucket.unreal += Number.isFinite(u) ? u : 0;
      bucket.count += 1;
      if (r.snapshotAt && (!bucket.lastAt || r.snapshotAt > bucket.lastAt)) {
        bucket.lastAt = r.snapshotAt;
      }
    }
    return by;
  }, [rows]);

  const loading =
    accountsQ.isLoading ||
    positionsQ.isLoading ||
    ownershipQs.some((q) => q.isLoading);
  const errored =
    accountsQ.isError ||
    positionsQ.isError ||
    ownershipQs.some((q) => q.isError);

  const columns: ColumnsType<HoldingRow> = useMemo(() => {
    const base: ColumnsType<HoldingRow> = [];
    if (market === "ALL") {
      base.push({ title: "시장", dataIndex: "broker", width: 90 });
    }
    base.push({
      title: market === "KIWOOM" ? "종목" : "코인/종목",
      key: "asset",
      width: 150,
      render: (_, r) => (
        <span style={{ whiteSpace: "pre-line" }}>
          {assetDisplayName(r.symbol, r.name, r.broker)}
        </span>
      ),
    });
    base.push(
      {
        title: "보유구분",
        dataIndex: "owner",
        width: 110,
        render: (v: string) => (
          <Tag color={ownershipBadgeColor(v)}>{ownershipLabelKo(v)}</Tag>
        ),
      },
      {
        title: "수량",
        dataIndex: "quantity",
        width: 110,
        sorter: (a, b) => a.quantitySort - b.quantitySort,
        render: (v) => formatQuantityKo(v),
      },
      {
        title: market === "KIWOOM" ? "평균매입가" : "평균매수가",
        dataIndex: "avgPriceDisplay",
        width: 120,
      },
      { title: "현재가", dataIndex: "currentPriceDisplay", width: 110 },
      { title: "매입금액", dataIndex: "purchaseDisplay", width: 120 },
      {
        title: "평가금액",
        dataIndex: "evalDisplay",
        width: 120,
        sorter: (a, b) => a.evalSort - b.evalSort,
        defaultSortOrder: "descend",
      },
      {
        title: "평가손익",
        dataIndex: "unrealizedDisplay",
        width: 120,
        sorter: (a, b) => a.unrealizedSort - b.unrealizedSort,
        render: (text: string, r) => (
          <PnLText
            text={text}
            value={
              r.unrealizedSort === Number.NEGATIVE_INFINITY
                ? null
                : r.unrealizedSort
            }
          />
        ),
      },
      {
        title: "수익률",
        dataIndex: "returnDisplay",
        width: 100,
        render: (text: string, r) => {
          const pct =
            r.unrealizedSort === Number.NEGATIVE_INFINITY || r.evalSort <= 0
              ? null
              : parseDecimalSafe(
                  String(text).replace("%", "").replace("+", ""),
                );
          return <PnLText text={text} value={pct} />;
        },
      },
      { title: "Strategy", dataIndex: "strategy", width: 120 },
      { title: "관리상태", dataIndex: "manageLabel", width: 110 },
      {
        title: "데이터",
        dataIndex: "dataQuality",
        width: 120,
        render: (v: DataQuality) => (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {dataQualityLabelKo(v)}
          </Typography.Text>
        ),
      },
    );
    return base;
  }, [market]);

  const emptyText =
    market === "UPBIT"
      ? "현재 업비트 보유자산이 없습니다."
      : market === "KIWOOM"
        ? "현재 키움증권 보유종목이 없습니다."
        : "표시할 보유 자산이 없습니다.";

  const formatLast = (iso: string | null) => {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("ko-KR", {
        hour12: false,
      });
    } catch {
      return iso;
    }
  };

  const renderMarketCard = (
    title: string,
    key: "UPBIT" | "KIWOOM",
    feeNote: string,
  ) => {
    const s = summaries[key];
    const ret =
      s.eval > 0 && Number.isFinite(s.unreal)
        ? (s.unreal / Math.max(s.eval - s.unreal, 1)) * 100
        : null;
    return (
      <Card size="small" title={title} style={{ height: "100%" }}>
        <Row gutter={[12, 12]}>
          <Col span={12}>
            <Statistic
              title="평가금액"
              value={s.eval}
              precision={0}
              suffix="원"
            />
          </Col>
          <Col span={12}>
            <Statistic
              title="평가손익"
              value={s.unreal}
              precision={0}
              suffix="원"
            />
          </Col>
          <Col span={12}>
            <Statistic
              title="평가수익률"
              value={ret ?? 0}
              precision={2}
              suffix="%"
              formatter={ret == null ? () => "—" : undefined}
            />
          </Col>
          <Col span={12}>
            <Statistic
              title="오늘 실현손익"
              value="—"
              suffix={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  실현손익 데이터 준비 중
                </Typography.Text>
              }
            />
          </Col>
        </Row>
        <Typography.Paragraph
          type="secondary"
          style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}
        >
          최근 갱신 {formatLast(s.lastAt)} · 종목 {s.count} · {feeNote}
        </Typography.Paragraph>
      </Card>
    );
  };

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="실제 보유자산과 자동매매 포지션을 구분합니다"
        description="Broker snapshot(일반 보유)과 Strategy binding(자동매매)을 분리 표시합니다. 평균단가가 없으면 평가손익을 0원으로 위장하지 않습니다."
      />

      <Row gutter={[12, 12]}>
        <Col xs={24} sm={12} md={8}>
          <SummaryLinkCard
            title="계좌 · LIVE/ARM"
            value="연결·거래 가능"
            href={adminRoutes.accounts}
            hint="보유와 분리된 기준 화면"
          />
        </Col>
        <Col xs={24} sm={12} md={8}>
          <SummaryLinkCard
            title="업비트 자동매매"
            value="슬롯·자금"
            href={adminRoutes.autotradingUpbit}
            hint="런타임 상세"
          />
        </Col>
        <Col xs={24} sm={12} md={8}>
          <SummaryLinkCard
            title="주문·체결"
            value="오늘 거래"
            href={adminRoutes.orders}
            hint="체결·거절 SoT"
          />
        </Col>
      </Row>

      <div>
        <Typography.Text type="secondary">시장</Typography.Text>
        <div style={{ marginTop: 6 }}>
          <Radio.Group
            value={market}
            onChange={(e) => setMarket(e.target.value)}
            optionType="button"
            options={[
              { label: "전체", value: "ALL" },
              { label: "업비트", value: "UPBIT" },
              { label: "키움증권", value: "KIWOOM" },
            ]}
          />
        </div>
      </div>

      <div>
        <Typography.Text type="secondary">보유구분</Typography.Text>
        <div style={{ marginTop: 6 }}>
          <Radio.Group
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            optionType="button"
            options={[
              { label: "전체", value: "ALL" },
              { label: "일반매매", value: "MANUAL" },
              { label: "자동매매", value: "AUTO" },
            ]}
          />
        </div>
      </div>

      <Checkbox
        checked={includeZeroQty}
        onChange={(e) => setIncludeZeroQty(e.target.checked)}
      >
        0수량 포함
      </Checkbox>

      {market === "ALL" ? (
        <Row gutter={[12, 12]}>
          <Col xs={24} md={12}>
            {renderMarketCard(
              "업비트",
              "UPBIT",
              "수수료 별도(평가손익 미반영)",
            )}
          </Col>
          <Col xs={24} md={12}>
            {renderMarketCard(
              "키움증권",
              "KIWOOM",
              "수수료/세금 반영 여부 미확정",
            )}
          </Col>
        </Row>
      ) : market === "UPBIT" ? (
        renderMarketCard("업비트 손익 Summary", "UPBIT", "수수료 별도(평가손익 미반영)")
      ) : (
        renderMarketCard(
          "키움증권 손익 Summary",
          "KIWOOM",
          "수수료/세금 반영 여부 미확정",
        )
      )}

      {errored ? (
        <Alert
          type="error"
          showIcon
          title="데이터를 불러오지 못했습니다."
          action={
            <Typography.Link
              onClick={() => {
                void accountsQ.refetch();
                void positionsQ.refetch();
                ownershipQs.forEach((q) => void q.refetch());
              }}
            >
              다시 시도
            </Typography.Link>
          }
        />
      ) : null}

      <div style={{ width: "100%", overflowX: "auto" }}>
        <Table
          size="small"
          rowKey="key"
          loading={loading}
          pagination={{ pageSize: 50 }}
          dataSource={rows}
          columns={columns}
          locale={{
            emptyText: (
              <Empty description={emptyText} image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ),
          }}
        />
      </div>

    </Space>
  );
}
