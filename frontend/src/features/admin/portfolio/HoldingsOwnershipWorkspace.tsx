"use client";

/**
 * 보유자산·손익 — AUTO/MANUAL ownership 필터.
 * WRITE 없음. symbol-ownership + ops positions 조합.
 */

import { useQueries, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  Radio,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import {
  ownershipBadgeColor,
  ownershipLabelKo,
  ownershipMatchesHoldingsFilter,
  type HoldingsOwnerFilter,
} from "@/features/admin/accounts/symbolOwnershipLabels";
import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";

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
  owner: string;
  quantity: string;
  avgPrice: string;
  currentPrice: string;
  evalAmount: string;
  unrealized: number;
  returnRate: string;
  strategy: string;
  manageLabel: string;
};

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

export function HoldingsOwnershipWorkspace() {
  const [filter, setFilter] = useState<HoldingsOwnerFilter>("ALL");

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

  const snapshotsQ = useQuery({
    queryKey: ["admin", "broker-snapshots", "holdings"],
    queryFn: () => adminApi.listAdminBrokerSnapshots({ limit: 50 }),
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
    for (const raw of posRows) {
      const p = rec(raw);
      const broker = String(p.broker_code ?? "").toUpperCase();
      const symbol = String(p.symbol ?? "").toUpperCase();
      if (!broker || !symbol) continue;
      const own = ownerMap.get(`${broker}:${symbol}`) ?? {};
      const owner = String(own.owner ?? "UNKNOWN").toUpperCase();
      if (!ownershipMatchesHoldingsFilter(owner, filter)) continue;
      const qty =
        owner === "AUTO"
          ? String(own.auto_position_qty ?? p.quantity ?? "—")
          : String(own.manual_position_qty ?? p.quantity ?? "—");
      const unrealized = Number(p.unrealized_pnl ?? 0);
      out.push({
        key: `${broker}-${symbol}`,
        broker,
        symbol,
        owner,
        quantity: qty,
        avgPrice: cell(p.average_price),
        currentPrice: cell(p.current_price),
        evalAmount: cell(p.evaluation_amount),
        unrealized: Number.isFinite(unrealized) ? unrealized : 0,
        returnRate: cell(p.return_rate),
        strategy:
          own.strategy_id != null ? `strategy:${own.strategy_id}` : "—",
        manageLabel: ownershipLabelKo(owner),
      });
    }

    // 포지션 스냅샷에 없고 ownership만 있는 AUTO/MANUAL (수량>0)
    for (const [key, own] of ownerMap) {
      const owner = String(own.owner ?? "").toUpperCase();
      if (!ownershipMatchesHoldingsFilter(owner, filter)) continue;
      if (owner === "FREE") continue;
      const [broker, symbol] = key.split(":");
      if (out.some((r) => r.broker === broker && r.symbol === symbol)) continue;
      const qtyNum = Number(
        owner === "AUTO" ? own.auto_position_qty : own.manual_position_qty,
      );
      if (!Number.isFinite(qtyNum) || qtyNum <= 0) {
        if (owner !== "AUTO_EXCLUDED") continue;
      }
      out.push({
        key,
        broker,
        symbol,
        owner,
        quantity: String(
          owner === "AUTO" ? own.auto_position_qty : own.manual_position_qty,
        ),
        avgPrice: "—",
        currentPrice: "—",
        evalAmount: "—",
        unrealized: 0,
        returnRate: "—",
        strategy:
          own.strategy_id != null ? `strategy:${own.strategy_id}` : "—",
        manageLabel: ownershipLabelKo(owner),
      });
    }
    return out;
  }, [filter, ownerMap, positionsQ.data]);

  const summary = useMemo(() => {
    let totalEval = 0;
    let totalUnreal = 0;
    let manualEval = 0;
    let manualUnreal = 0;
    let autoEval = 0;
    let autoUnreal = 0;
    for (const r of rows) {
      const ev = Number(r.evalAmount);
      const u = r.unrealized;
      if (Number.isFinite(ev)) totalEval += ev;
      totalUnreal += u;
      if (r.owner === "MANUAL" || r.owner === "AUTO_EXCLUDED") {
        if (Number.isFinite(ev)) manualEval += ev;
        manualUnreal += u;
      }
      if (r.owner === "AUTO") {
        if (Number.isFinite(ev)) autoEval += ev;
        autoUnreal += u;
      }
    }
    const snapTotal = (snapshotsQ.data?.items ?? []).reduce((sum, s) => {
      const n = Number(s.total_evaluation_amount);
      return sum + (Number.isFinite(n) ? n : 0);
    }, 0);
    return {
      totalEval: totalEval || snapTotal,
      totalUnreal,
      manualEval,
      manualUnreal,
      autoEval,
      autoUnreal,
    };
  }, [rows, snapshotsQ.data]);

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="계좌 전체 ≠ 자동매매 Strategy PnL"
        description="일반매매(MANUAL)와 자동매매(AUTO binding)를 분리해 표시합니다. FREE(후보만)는 보유 목록에서 숨깁니다."
      />
      <Card size="small" title="손익 Summary">
        <Row gutter={[12, 12]}>
          <Col xs={12} md={8} lg={6}>
            <Statistic
              title="전체 자산(평가)"
              value={summary.totalEval}
              precision={0}
            />
          </Col>
          <Col xs={12} md={8} lg={6}>
            <Statistic
              title="전체 평가손익"
              value={summary.totalUnreal}
              precision={0}
            />
          </Col>
          <Col xs={12} md={8} lg={6}>
            <Statistic
              title="일반매매 평가금액"
              value={summary.manualEval}
              precision={0}
            />
          </Col>
          <Col xs={12} md={8} lg={6}>
            <Statistic
              title="일반매매 평가손익"
              value={summary.manualUnreal}
              precision={0}
            />
          </Col>
          <Col xs={12} md={8} lg={6}>
            <Statistic
              title="자동매매 투자금(평가)"
              value={summary.autoEval}
              precision={0}
            />
          </Col>
          <Col xs={12} md={8} lg={6}>
            <Statistic
              title="자동매매 평가손익"
              value={summary.autoUnreal}
              precision={0}
            />
          </Col>
          <Col xs={12} md={8} lg={6}>
            <Statistic
              title="자동매매 실현손익"
              value="—"
              suffix={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  시계열 API gap
                </Typography.Text>
              }
            />
          </Col>
        </Row>
      </Card>

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

      <div style={{ width: "100%", overflowX: "auto" }}>
        <Table
          size="small"
          rowKey="key"
          pagination={{ pageSize: 50 }}
          dataSource={rows}
          columns={[
            { title: "Broker", dataIndex: "broker", width: 90 },
            { title: "종목", dataIndex: "symbol", width: 110 },
            {
              title: "구분",
              dataIndex: "owner",
              width: 110,
              render: (v: string) => (
                <Tag color={ownershipBadgeColor(v)}>{ownershipLabelKo(v)}</Tag>
              ),
            },
            { title: "수량", dataIndex: "quantity", width: 100 },
            { title: "평균단가", dataIndex: "avgPrice", width: 100 },
            { title: "현재가", dataIndex: "currentPrice", width: 100 },
            { title: "평가금액", dataIndex: "evalAmount", width: 110 },
            {
              title: "평가손익",
              dataIndex: "unrealized",
              width: 110,
              render: (v: number) => v.toLocaleString("ko-KR"),
            },
            { title: "수익률", dataIndex: "returnRate", width: 90 },
            { title: "Strategy", dataIndex: "strategy", width: 120 },
            { title: "관리상태", dataIndex: "manageLabel", width: 110 },
          ]}
          locale={{ emptyText: "표시할 보유 자산이 없습니다." }}
        />
      </div>
    </Space>
  );
}
