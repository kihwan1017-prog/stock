"use client";

import { Tag } from "antd";

import {
  STRATEGY_MARKET_LABEL_KO,
  parseStrategyMarket,
  type StrategyMarket,
} from "@/features/admin/strategy-analysis/marketScope";

const COLOR: Record<StrategyMarket, string> = {
  ALL: "default",
  KIWOOM: "blue",
  UPBIT: "purple",
};

export function MarketBadge({
  market,
}: {
  market: StrategyMarket | string;
}) {
  const raw = String(market ?? "").toUpperCase();
  const m = parseStrategyMarket(raw === "KRX" ? "KIWOOM" : raw);
  const label = STRATEGY_MARKET_LABEL_KO[m] ?? String(market);
  return <Tag color={COLOR[m]}>{label}</Tag>;
}

export function BrokerBadge({
  broker,
}: {
  broker: string | null | undefined;
}) {
  const b = String(broker ?? "").toUpperCase();
  if (b.includes("KIWOOM") || b === "KRX") {
    return <MarketBadge market="KIWOOM" />;
  }
  if (b.includes("UPBIT")) {
    return <MarketBadge market="UPBIT" />;
  }
  return <Tag>{broker || "—"}</Tag>;
}
