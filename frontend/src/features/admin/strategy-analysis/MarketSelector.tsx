"use client";

import { Segmented, Space, Typography } from "antd";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

import {
  STRATEGY_MARKET_LABEL_KO,
  STRATEGY_MARKETS,
  parseStrategyMarket,
  type StrategyMarket,
} from "@/features/admin/strategy-analysis/marketScope";

type Props = {
  /** 제어 모드 — 없으면 URL ?market= 동기화 */
  value?: StrategyMarket;
  onChange?: (market: StrategyMarket) => void;
  size?: "small" | "middle" | "large";
  showLabel?: boolean;
};

/**
 * 전략·분석 공통 시장 선택기 — [전체 | 키움 | 업비트]
 */
export function MarketSelector({
  value,
  onChange,
  size = "middle",
  showLabel = true,
}: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const urlMarket = useMemo(
    () => parseStrategyMarket(searchParams.get("market")),
    [searchParams],
  );
  const market = value ?? urlMarket;

  const setMarket = useCallback(
    (next: StrategyMarket) => {
      onChange?.(next);
      if (value !== undefined && onChange) {
        // 완전 제어 모드 — URL은 호출측에서 갱신 가능
        return;
      }
      const params = new URLSearchParams(searchParams.toString());
      if (next === "ALL") {
        params.delete("market");
      } else {
        params.set("market", next);
      }
      const q = params.toString();
      router.replace(q ? `${pathname}?${q}` : pathname, { scroll: false });
    },
    [onChange, pathname, router, searchParams, value],
  );

  return (
    <Space wrap align="center" size={8}>
      {showLabel ? (
        <Typography.Text type="secondary">시장</Typography.Text>
      ) : null}
      <Segmented
        size={size}
        value={market}
        options={STRATEGY_MARKETS.map((m) => ({
          value: m,
          label: STRATEGY_MARKET_LABEL_KO[m],
        }))}
        onChange={(v) => setMarket(parseStrategyMarket(String(v)))}
      />
    </Space>
  );
}

export function useStrategyMarketFromUrl(): StrategyMarket {
  const searchParams = useSearchParams();
  return useMemo(
    () => parseStrategyMarket(searchParams.get("market")),
    [searchParams],
  );
}
