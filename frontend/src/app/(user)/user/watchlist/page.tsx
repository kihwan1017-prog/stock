"use client";

import {
  DndContext,
  PointerSensor,
  closestCenter,
  type DragEndEvent,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  AutoComplete,
  Button,
  Card,
  ColorPicker,
  Empty,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { Color } from "antd/es/color-picker";
import { HolderOutlined, DeleteOutlined } from "@ant-design/icons";
import { useMemo, useState } from "react";

import { PageContainer } from "@/components/common/PageContainer";
import type { WatchlistItem, WatchlistSearchHit } from "@/features/user/api/userApi";
import * as userApi from "@/features/user/api/userApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const COLOR_PRESETS = ["#1677ff", "#52c41a", "#faad14", "#eb2f96", "#722ed1", "#13c2c2"];

function SortableRow({
  item,
  onDelete,
  onPatch,
}: {
  item: WatchlistItem;
  onDelete: (item: WatchlistItem) => void;
  onPatch: (
    id: number,
    body: Parameters<typeof userApi.updateWatchlistItem>[1],
  ) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: item.watchlist_id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.7 : 1,
    background: item.color ? `${item.color}14` : undefined,
  };

  return (
    <tr ref={setNodeRef} style={style}>
      <td style={{ width: 40, cursor: "grab" }} {...attributes} {...listeners}>
        <HolderOutlined />
      </td>
      <td>
        <Tag>{item.market}</Tag>
      </td>
      <td>
        <Typography.Text strong>{item.symbol}</Typography.Text>
      </td>
      <td>{item.symbol_name}</td>
      <td>
        <Input
          size="small"
          defaultValue={item.memo ?? ""}
          placeholder="메모"
          maxLength={500}
          onBlur={(event) => {
            const value = event.target.value.trim();
            if (value === (item.memo ?? "")) return;
            onPatch(item.watchlist_id, {
              memo: value || null,
              clear_memo: !value,
            });
          }}
        />
      </td>
      <td>
        <ColorPicker
          size="small"
          value={item.color ?? undefined}
          presets={[{ label: "추천", colors: COLOR_PRESETS }]}
          onChangeComplete={(color: Color) => {
            onPatch(item.watchlist_id, { color: color.toHexString() });
          }}
          allowClear
          onClear={() =>
            onPatch(item.watchlist_id, { clear_color: true })
          }
        />
      </td>
      <td>
        <Space size={4} wrap>
          <Switch
            size="small"
            checked={item.news_enabled}
            onChange={(checked) =>
              onPatch(item.watchlist_id, { news_enabled: checked })
            }
          />
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            뉴스
          </Typography.Text>
        </Space>
      </td>
      <td>
        <Space size={4} wrap>
          <Switch
            size="small"
            checked={item.disclosure_enabled}
            onChange={(checked) =>
              onPatch(item.watchlist_id, { disclosure_enabled: checked })
            }
          />
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            공시
          </Typography.Text>
        </Space>
      </td>
      <td>
        <Space size={4} wrap>
          <Switch
            size="small"
            checked={item.ai_enabled}
            onChange={(checked) =>
              onPatch(item.watchlist_id, { ai_enabled: checked })
            }
          />
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            AI
          </Typography.Text>
        </Space>
      </td>
      <td>
        <Button
          size="small"
          danger
          icon={<DeleteOutlined />}
          onClick={() => onDelete(item)}
        />
      </td>
    </tr>
  );
}

export default function UserWatchlistPage() {
  const queryClient = useQueryClient();
  const [market, setMarket] = useState("KRX");
  const [searchText, setSearchText] = useState("");
  const [options, setOptions] = useState<
    { value: string; label: string; hit: WatchlistSearchHit }[]
  >([]);

  const listQuery = useQuery({
    queryKey: queryKeys.user.watchlist(),
    queryFn: userApi.listWatchlist,
  });

  const items = listQuery.data?.items ?? [];
  const maxItems = listQuery.data?.max_items ?? 50;

  const invalidate = async () => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.user.watchlist(),
    });
  };

  const addMutation = useMutation({
    mutationFn: userApi.addWatchlistItem,
    onSuccess: async () => {
      message.success("관심종목에 추가했습니다.");
      setSearchText("");
      setOptions([]);
      await invalidate();
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const patchMutation = useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: number;
      body: Parameters<typeof userApi.updateWatchlistItem>[1];
    }) => userApi.updateWatchlistItem(id, body),
    onSuccess: async () => {
      await invalidate();
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const deleteMutation = useMutation({
    mutationFn: userApi.deleteWatchlistItem,
    onSuccess: async (result) => {
      await invalidate();
      const deleted = result.item;
      message.success({
        content: (
          <span>
            {deleted.symbol} 삭제됨.{" "}
            <Button
              type="link"
              size="small"
              onClick={() => {
                addMutation.mutate({
                  market: deleted.market,
                  symbol: deleted.symbol,
                  symbol_name: deleted.symbol_name,
                  memo: deleted.memo ?? undefined,
                  color: deleted.color ?? undefined,
                  alarm_enabled: deleted.alarm_enabled,
                  news_enabled: deleted.news_enabled,
                  disclosure_enabled: deleted.disclosure_enabled,
                  ai_enabled: deleted.ai_enabled,
                });
              }}
            >
              실행 취소
            </Button>
          </span>
        ),
        duration: 5,
      });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const reorderMutation = useMutation({
    mutationFn: userApi.reorderWatchlist,
    onSuccess: async () => {
      await invalidate();
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

  const ids = useMemo(
    () => items.map((row) => row.watchlist_id),
    [items],
  );

  const onDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = ids.indexOf(Number(active.id));
    const newIndex = ids.indexOf(Number(over.id));
    if (oldIndex < 0 || newIndex < 0) return;
    const next = arrayMove(ids, oldIndex, newIndex);
    // 낙관적 UI — 서버 저장
    queryClient.setQueryData(
      queryKeys.user.watchlist(),
      (prev: userApi.WatchlistListResponse | undefined) => {
        if (!prev) return prev;
        const map = new Map(
          prev.items.map((row) => [row.watchlist_id, row]),
        );
        const reordered = next
          .map((id, index) => {
            const row = map.get(id);
            return row ? { ...row, display_order: index + 1 } : null;
          })
          .filter((row): row is WatchlistItem => row !== null);
        return { ...prev, items: reordered };
      },
    );
    reorderMutation.mutate(next);
  };

  const runSearch = async (text: string) => {
    setSearchText(text);
    if (!text.trim()) {
      setOptions([]);
      return;
    }
    try {
      const result = await userApi.searchWatchlistSymbols({
        q: text.trim(),
        market,
        limit: 20,
      });
      setOptions(
        result.items.map((hit) => ({
          value: `${hit.market}:${hit.symbol}`,
          label: `${hit.symbol} · ${hit.symbol_name ?? hit.name ?? ""} (${hit.market})`,
          hit,
        })),
      );
    } catch (error) {
      message.error(toApiError(error).message);
    }
  };

  const confirmDelete = (item: WatchlistItem) => {
    Modal.confirm({
      title: "관심종목 삭제",
      content: `${item.symbol} (${item.symbol_name}) 을(를) 삭제할까요?`,
      okText: "삭제",
      okButtonProps: { danger: true },
      onOk: () => deleteMutation.mutateAsync(item.watchlist_id),
    });
  };

  return (
    <PageContainer
      title="관심종목"
      description="회원별 관심종목을 관리합니다. STEP68~70 뉴스·공시·AI 개인화의 기반입니다."
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        {listQuery.error ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(listQuery.error).message}
          />
        ) : null}

        <Card size="small" title="종목 추가">
          <Space wrap>
            <Select
              style={{ width: 120 }}
              value={market}
              onChange={setMarket}
              options={[
                { value: "KRX", label: "KRX" },
                { value: "UPBIT", label: "UPBIT" },
              ]}
            />
            <AutoComplete
              style={{ width: 360 }}
              options={options}
              value={searchText}
              onSearch={(value) => void runSearch(value)}
              onSelect={(_value, option) => {
                const hit = (
                  option as { hit?: WatchlistSearchHit }
                ).hit;
                if (!hit) return;
                addMutation.mutate({
                  market: hit.market,
                  symbol: hit.symbol,
                  symbol_name: hit.symbol_name ?? hit.name,
                });
              }}
              placeholder="종목코드 또는 이름 검색"
            />
            <Typography.Text type="secondary">
              {items.length} / {maxItems}
            </Typography.Text>
          </Space>
        </Card>

        <Card
          size="small"
          title="내 관심종목"
          loading={listQuery.isLoading}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              드래그하여 순서 변경 · GET/POST /user/watchlist
            </Typography.Text>
          }
        >
          {items.length === 0 ? (
            <Empty description="관심종목이 없습니다. 위에서 검색해 추가하세요." />
          ) : (
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={onDragEnd}
            >
              <SortableContext
                items={ids}
                strategy={verticalListSortingStrategy}
              >
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left", padding: 8 }} />
                      <th style={{ textAlign: "left", padding: 8 }}>시장</th>
                      <th style={{ textAlign: "left", padding: 8 }}>코드</th>
                      <th style={{ textAlign: "left", padding: 8 }}>종목명</th>
                      <th style={{ textAlign: "left", padding: 8 }}>메모</th>
                      <th style={{ textAlign: "left", padding: 8 }}>색상</th>
                      <th style={{ textAlign: "left", padding: 8 }}>뉴스</th>
                      <th style={{ textAlign: "left", padding: 8 }}>공시</th>
                      <th style={{ textAlign: "left", padding: 8 }}>AI</th>
                      <th style={{ textAlign: "left", padding: 8 }} />
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <SortableRow
                        key={item.watchlist_id}
                        item={item}
                        onDelete={confirmDelete}
                        onPatch={(id, body) =>
                          patchMutation.mutate({ id, body })
                        }
                      />
                    ))}
                  </tbody>
                </table>
              </SortableContext>
            </DndContext>
          )}
        </Card>

        {/* 접근성·모바일용 테이블 요약 */}
        <Card size="small" title="목록 (표)" type="inner">
          <Table<WatchlistItem>
            size="small"
            pagination={false}
            rowKey="watchlist_id"
            dataSource={items}
            columns={[
              { title: "순서", dataIndex: "display_order", width: 70 },
              { title: "시장", dataIndex: "market", width: 80 },
              { title: "코드", dataIndex: "symbol", width: 100 },
              { title: "종목명", dataIndex: "symbol_name" },
              {
                title: "메모",
                dataIndex: "memo",
                render: (v: string | null) => v ?? "-",
              },
            ]}
          />
        </Card>
      </Space>
    </PageContainer>
  );
}
