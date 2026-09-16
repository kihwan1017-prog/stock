"use client";

/**
 * Kiwoom Research RAG/Feedback tab — market-isolated from UPBIT.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Collapse,
  Descriptions,
  Drawer,
  Empty,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState, type ReactNode } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { formatKstClock } from "@/features/admin/upbit/researchDetailFormat";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

function dash(v: unknown): string {
  if (v == null || v === "") return "—";
  return String(v);
}

function safeArray<T extends Record<string, unknown>>(v: unknown): T[] {
  return Array.isArray(v)
    ? v.filter((x): x is T => typeof x === "object" && x !== null)
    : [];
}

function QueryState({
  isLoading,
  isError,
  error,
  empty,
  emptyHint,
  children,
}: {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  empty: boolean;
  emptyHint?: string;
  children: ReactNode;
}) {
  if (isLoading) {
    return <Typography.Text type="secondary">불러오는 중…</Typography.Text>;
  }
  if (isError) {
    return (
      <Alert
        type="error"
        showIcon
        title="조회 실패"
        description={toApiError(error).message}
      />
    );
  }
  if (empty) {
    return (
      <Empty
        description={emptyHint || "표시할 데이터가 없습니다"}
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    );
  }
  return <>{children}</>;
}

function JsonCollapse({ title, data }: { title: string; data: unknown }) {
  if (data == null) return null;
  return (
    <Collapse
      size="small"
      items={[
        {
          key: "raw",
          label: title,
          children: (
            <pre
              style={{
                margin: 0,
                maxHeight: 320,
                overflow: "auto",
                fontSize: 12,
              }}
            >
              {JSON.stringify(data, null, 2)}
            </pre>
          ),
        },
      ]}
    />
  );
}

export function KiwoomRagFeedbackTab() {
  const [drawerId, setDrawerId] = useState<number | null>(null);
  const listQ = useQuery({
    queryKey: queryKeys.admin.kiwoomDualLlmRagFeedback({ limit: 50 }),
    queryFn: () => adminApi.getAdminKiwoomDualLlmRagFeedback({ limit: 50 }),
  });
  const detailQ = useQuery({
    queryKey: queryKeys.admin.kiwoomDualLlmRagFeedbackDetail(drawerId ?? 0),
    queryFn: () =>
      adminApi.getAdminKiwoomDualLlmRagFeedbackDetail(drawerId as number),
    enabled: drawerId != null,
  });
  const items = safeArray(asRecord(listQ.data)?.items);
  const flow = asRecord(asRecord(detailQ.data)?.flow);

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="KIWOOM RAG / Feedback"
        description="KIWOOM CLEAN 사례만 사용합니다. UPBIT RAG와 혼합되지 않습니다. SHADOW ONLY."
      />
      <QueryState
        isLoading={listQ.isLoading}
        isError={listQ.isError}
        error={listQ.error}
        empty={!listQ.isLoading && items.length === 0}
        emptyHint="자연 MA ENTRY SHADOW row가 아직 없습니다."
      >
        <Table
          size="small"
          rowKey={(r) => String(r.analysis_id)}
          dataSource={items}
          pagination={false}
          onRow={(r) => ({
            onClick: () => setDrawerId(Number(r.analysis_id)),
            style: { cursor: "pointer" },
          })}
          columns={[
            { title: "ID", dataIndex: "analysis_id", width: 70, render: dash },
            { title: "Symbol", dataIndex: "symbol", render: dash },
            {
              title: "Detected",
              dataIndex: "detected_at",
              render: (v) => formatKstClock(v),
            },
            {
              title: "Trading",
              dataIndex: "trading_prediction",
              render: dash,
            },
            {
              title: "Verdict",
              dataIndex: "prediction_verdict",
              render: dash,
            },
            {
              title: "RAG",
              dataIndex: "rag_examples",
              render: (v) => (Array.isArray(v) ? String(v.length) : "0"),
            },
            {
              title: "Teacher",
              dataIndex: "teacher_reviewed",
              render: (v) => (v ? <Tag color="blue">Y</Tag> : "—"),
            },
            {
              title: "Tier",
              dataIndex: "dataset_tier",
              render: (v) => (v ? <Tag>{String(v)}</Tag> : "—"),
            },
          ]}
        />
      </QueryState>
      <Drawer
        title={`KIWOOM RAG / Feedback #${drawerId ?? ""}`}
        open={drawerId != null}
        onClose={() => setDrawerId(null)}
        size={720}
      >
        {detailQ.isLoading ? (
          <Typography.Text type="secondary">불러오는 중…</Typography.Text>
        ) : detailQ.isError ? (
          <Alert
            type="error"
            showIcon
            title="상세 조회 실패"
            description={toApiError(detailQ.error).message}
          />
        ) : (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <JsonCollapse title="후보 / provenance" data={flow?.provenance} />
            <JsonCollapse title="Technical" data={flow?.technical} />
            <JsonCollapse title="News" data={flow?.news} />
            <JsonCollapse title="Disclosure" data={flow?.disclosures} />
            <JsonCollapse title="RAG 유사사례" data={flow?.rag_examples} />
            <JsonCollapse title="1.7B Analysis" data={flow?.analysis_1_7b} />
            <JsonCollapse title="2B Trading SHADOW" data={flow?.trading_2b} />
            <JsonCollapse title="4B Teacher" data={flow?.teacher_4b} />
            <JsonCollapse title="Actual" data={flow?.actual_outcome} />
            <JsonCollapse title="Feedback" data={flow?.feedback} />
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="Dataset tier">
                {dash(flow?.dataset_tier)}
              </Descriptions.Item>
            </Descriptions>
          </Space>
        )}
      </Drawer>
    </Space>
  );
}
