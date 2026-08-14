"use client";

import { Button, Space, Tabs, Typography } from "antd";
import { useState, type ReactNode } from "react";

import {
  UPBIT_HUB_TAB_KEYS,
  UPBIT_HUB_TAB_LABELS,
  type UpbitHubTabKey,
} from "@/features/admin/upbit/upbitHubTabConfig";

type UpbitHubTabsProps = {
  /** Overview 전용 — LIVE READ summary (추가 API 없음) */
  liveSummary: ReactNode;
  technical: ReactNode;
  news: ReactNode;
  ab: ReactNode;
  ops: ReactNode;
};

/**
 * M5-A Upbit Hub Tab shell.
 * - 비활성 탭은 첫 방문 전 unmount (Overview에서 Scanner/News/A-B fetch 방지)
 * - 방문 후에는 display:none 유지 (remount로 인한 refetchInterval 재시작 방지)
 * - Tab 전환만으로 mutation 호출 없음
 */
export function UpbitHubTabs({
  liveSummary,
  technical,
  news,
  ab,
  ops,
}: UpbitHubTabsProps) {
  const [activeKey, setActiveKey] = useState<UpbitHubTabKey>(
    UPBIT_HUB_TAB_KEYS.overview,
  );
  const [visited, setVisited] = useState<Partial<Record<UpbitHubTabKey, true>>>(
    {
      [UPBIT_HUB_TAB_KEYS.overview]: true,
    },
  );

  const selectTab = (key: string) => {
    const tabKey = key as UpbitHubTabKey;
    setActiveKey(tabKey);
    setVisited((prev) =>
      prev[tabKey] ? prev : { ...prev, [tabKey]: true as const },
    );
  };

  const keepAlivePane = (key: UpbitHubTabKey, node: ReactNode) => {
    if (!visited[key]) return null;
    return (
      <div
        role="tabpanel"
        id={`upbit-hub-panel-${key}`}
        aria-labelledby={`upbit-hub-tab-${key}`}
        hidden={activeKey !== key}
        style={{ display: activeKey === key ? "block" : "none" }}
      >
        {node}
      </div>
    );
  };

  const overviewBody = (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        UPBIT Hub입니다. LIVE/ARM/Scheduler{" "}
        <Typography.Text strong>제어</Typography.Text>는 계좌 관리에서만
        수행합니다. 이 화면은 조회·연구(Scanner/News/A-B)·운영 정합을
        탭으로 나눕니다.
      </Typography.Paragraph>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Private 키는 env(`UPBIT_ACCESS_KEY` / `UPBIT_SECRET_KEY`)만 사용합니다.
        `UPBIT_USE_MOCK=true`이면 실호출 없이 mock 잔고로 검증합니다. 실주문은
        비활성(`UPBIT_LIVE_ORDER_ENABLED=false`)이 기본입니다. 연결·잔고·체결
        동기화는「운영·정합」탭을 사용하세요.
      </Typography.Paragraph>

      {liveSummary}

      <Typography.Title level={5} style={{ marginBottom: 0 }}>
        섹션 안내
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
        아래 버튼은 탭만 전환합니다. Scanner/News/A-B 데이터를 Overview에서
        다시 조회하지 않습니다.
      </Typography.Paragraph>
      <Space wrap>
        <Button onClick={() => selectTab(UPBIT_HUB_TAB_KEYS.technical)}>
          {UPBIT_HUB_TAB_LABELS.technical} — Opportunity Scanner / Shadow /
          Cohort
        </Button>
        <Button onClick={() => selectTab(UPBIT_HUB_TAB_KEYS.news)}>
          {UPBIT_HUB_TAB_LABELS.news} — Collector → Mapping → AI → Signal
        </Button>
        <Button onClick={() => selectTab(UPBIT_HUB_TAB_KEYS.ab)}>
          {UPBIT_HUB_TAB_LABELS.ab} — Combined Shadow (N6)
        </Button>
        <Button onClick={() => selectTab(UPBIT_HUB_TAB_KEYS.ops)}>
          {UPBIT_HUB_TAB_LABELS.ops} — 연결/잔고/체결 · Ambiguous
        </Button>
      </Space>
    </Space>
  );

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Tabs
        activeKey={activeKey}
        onChange={selectTab}
        items={[
          {
            key: UPBIT_HUB_TAB_KEYS.overview,
            label: UPBIT_HUB_TAB_LABELS.overview,
            id: `upbit-hub-tab-${UPBIT_HUB_TAB_KEYS.overview}`,
          },
          {
            key: UPBIT_HUB_TAB_KEYS.technical,
            label: UPBIT_HUB_TAB_LABELS.technical,
            id: `upbit-hub-tab-${UPBIT_HUB_TAB_KEYS.technical}`,
          },
          {
            key: UPBIT_HUB_TAB_KEYS.news,
            label: UPBIT_HUB_TAB_LABELS.news,
            id: `upbit-hub-tab-${UPBIT_HUB_TAB_KEYS.news}`,
          },
          {
            key: UPBIT_HUB_TAB_KEYS.ab,
            label: UPBIT_HUB_TAB_LABELS.ab,
            id: `upbit-hub-tab-${UPBIT_HUB_TAB_KEYS.ab}`,
          },
          {
            key: UPBIT_HUB_TAB_KEYS.ops,
            label: UPBIT_HUB_TAB_LABELS.ops,
            id: `upbit-hub-tab-${UPBIT_HUB_TAB_KEYS.ops}`,
          },
        ]}
      />

      {keepAlivePane(UPBIT_HUB_TAB_KEYS.overview, overviewBody)}
      {keepAlivePane(UPBIT_HUB_TAB_KEYS.technical, technical)}
      {keepAlivePane(UPBIT_HUB_TAB_KEYS.news, news)}
      {keepAlivePane(UPBIT_HUB_TAB_KEYS.ab, ab)}
      {keepAlivePane(UPBIT_HUB_TAB_KEYS.ops, ops)}
    </Space>
  );
}
