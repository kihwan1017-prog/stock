"use client";

/**
 * STEP 12-2-1 — Strategy Draft 조회(사용자, 읽기 전용).
 * 관리자가 내 승인된 Strategy Request 위에 작성한 Draft를 조회만 한다.
 * 생성/수정/Archive는 관리자 전용이며, 이 화면에서 AI 생성·Backtest·
 * 실거래 승인·Runtime 등록은 이루어지지 않는다(STEP12-2-2 이후).
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";

import * as userApi from "@/features/user/api/userApi";
import type { StrategyDraftItem } from "@/features/user/api/userApi";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const STATUS_COLOR: Record<string, string> = {
  DRAFT: "processing",
  REGENERATED: "default",
  SUPERSEDED: "warning",
  ARCHIVED: "error",
};

export default function UserStrategyDraftsPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const listQuery = useQuery({
    queryKey: queryKeys.user.strategyDrafts.list(),
    queryFn: () => userApi.listStrategyDrafts({ limit: 50 }),
  });

  const detailQuery = useQuery({
    queryKey: queryKeys.user.strategyDrafts.detail(selectedId ?? 0),
    queryFn: () => userApi.getStrategyDraft(selectedId as number),
    enabled: selectedId != null,
  });

  const items = listQuery.data?.items ?? [];
  const detail = detailQuery.data;

  return (
    <UserPageShell
      title="전략 초안"
      description="관리자가 승인된 내 전략 요청 위에 작성한 초안(Draft)을 조회합니다. 이 화면에서 전략이 자동 생성되거나 실거래가 실행되지 않습니다."
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="warning"
          showIcon
          title="Strategy Draft는 관리자가 작성·버전관리하는 초안이며 조회만 가능합니다. Backtest·실거래 승인·자동매매를 의미하지 않습니다."
        />

        <Card size="small" title="내 전략 초안 목록" loading={listQuery.isLoading}>
          {listQuery.isError ? (
            <Alert type="error" title={toApiError(listQuery.error).message} />
          ) : items.length === 0 ? (
            <Empty description="전략 초안이 없습니다." />
          ) : (
            <Table<StrategyDraftItem>
              size="small"
              rowKey={(row) => row.draft_id}
              dataSource={items}
              pagination={{ pageSize: 10 }}
              onRow={(row) => ({
                onClick: () => setSelectedId(row.draft_id),
              })}
              columns={[
                { title: "Version", dataIndex: "label", width: 100 },
                {
                  title: "Request",
                  dataIndex: "strategy_request_id",
                  width: 90,
                },
                {
                  title: "상태",
                  dataIndex: "status",
                  width: 130,
                  render: (value: string) => (
                    <Tag color={STATUS_COLOR[value] ?? "default"}>{value}</Tag>
                  ),
                },
                { title: "제목", dataIndex: "title" },
                { title: "생성일시", dataIndex: "created_at" },
              ]}
            />
          )}
        </Card>
      </Space>

      <Drawer
        title={detail ? `Strategy Draft #${detail.draft_id}` : "상세"}
        open={selectedId != null}
        onClose={() => setSelectedId(null)}
        size={520}
        destroyOnHidden
      >
        {detailQuery.isLoading ? (
          <Typography.Text type="secondary">불러오는 중…</Typography.Text>
        ) : detail ? (
          <Space orientation="vertical" size={10} style={{ width: "100%" }}>
            <Space wrap>
              <Tag color={STATUS_COLOR[detail.status] ?? "default"}>
                {detail.status}
              </Tag>
              <Tag>{detail.label}</Tag>
            </Space>
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="제목">{detail.title}</Descriptions.Item>
              <Descriptions.Item label="요약">
                {detail.summary ?? "-"}
              </Descriptions.Item>
              <Descriptions.Item label="Timeframe / Market">
                {detail.timeframe} / {detail.market_type}
              </Descriptions.Item>
              <Descriptions.Item label="Entry Rule">
                {detail.entry_rule ?? "-"}
              </Descriptions.Item>
              <Descriptions.Item label="Exit Rule">
                {detail.exit_rule ?? "-"}
              </Descriptions.Item>
              <Descriptions.Item label="Stop Loss / Take Profit">
                {detail.stop_loss_rule ?? "-"} / {detail.take_profit_rule ?? "-"}
              </Descriptions.Item>
              <Descriptions.Item label="생성일시">
                {detail.created_at}
              </Descriptions.Item>
            </Descriptions>
          </Space>
        ) : null}
      </Drawer>
    </UserPageShell>
  );
}
