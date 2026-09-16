"use client";

/**
 * AUTO PnL 차트 — 시계열 API 없으면 empty state만 (가짜 데이터 금지).
 * 라이브러리: 기존 recharts 재사용.
 */

import { Alert, Card, Empty, Radio, Space, Typography } from "antd";
import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type AutoPnlPoint = {
  date: string;
  realized: number;
  cumulative: number;
  kiwoom?: number;
  upbit?: number;
};

type Props = {
  /** AUTO 전용 시계열. 없으면 empty */
  series?: AutoPnlPoint[] | null;
  loading?: boolean;
};

export function AutoPnlCharts({ series, loading }: Props) {
  const [range, setRange] = useState<"7" | "30">("7");
  const rows = useMemo(() => {
    const all = Array.isArray(series) ? series : [];
    const n = range === "7" ? 7 : 30;
    return all.slice(-n);
  }, [series, range]);

  const hasData = rows.length > 0;

  return (
    <Card
      size="small"
      title="자동매매 손익 차트"
      extra={
        <Radio.Group
          size="small"
          value={range}
          onChange={(e) => setRange(e.target.value)}
          optionType="button"
          options={[
            { label: "7일", value: "7" },
            { label: "30일", value: "30" },
          ]}
        />
      }
      loading={loading}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        title="AUTO 전용"
        description="일반매매(MANUAL) 손익은 이 차트에 합산하지 않습니다. 계좌 전체 PnL ≠ 자동매매 Strategy PnL."
      />
      {!hasData ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="자동매매 체결 데이터가 아직 없습니다."
        />
      ) : (
        <Space orientation="vertical" size={16} style={{ width: "100%" }}>
          <div style={{ width: "100%", height: 220 }}>
            <Typography.Text type="secondary">최근 AUTO 실현손익</Typography.Text>
            <ResponsiveContainer>
              <BarChart data={rows}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Bar dataKey="realized" name="실현손익" fill="#1677ff" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div style={{ width: "100%", height: 220 }}>
            <Typography.Text type="secondary">누적 AUTO PnL</Typography.Text>
            <ResponsiveContainer>
              <LineChart data={rows}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Line
                  type="monotone"
                  dataKey="cumulative"
                  name="누적"
                  stroke="#52c41a"
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div style={{ width: "100%", height: 220 }}>
            <Typography.Text type="secondary">
              KIWOOM vs UPBIT AUTO PnL
            </Typography.Text>
            <ResponsiveContainer>
              <BarChart data={rows}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey="kiwoom" name="키움 AUTO" fill="#722ed1" />
                <Bar dataKey="upbit" name="업비트 AUTO" fill="#13c2c2" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Space>
      )}
    </Card>
  );
}
