"use client";

import { Segmented } from "antd";

import type { BrokerFilter } from "./autoTradingPerformanceHelpers";
import { BROKER_SEGMENTS } from "./dashboardTabState";

type Props = {
  value: BrokerFilter;
  onChange: (v: BrokerFilter) => void;
};

export function DashboardBrokerFilter({ value, onChange }: Props) {
  return (
    <Segmented
      value={value}
      onChange={(v) => onChange(v as BrokerFilter)}
      options={BROKER_SEGMENTS.map((b) => ({
        label: b.label,
        value: b.value,
      }))}
    />
  );
}
