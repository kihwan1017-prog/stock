"use client";

import { Alert, Card, Empty, Spin, Typography } from "antd";
import type { ReactNode } from "react";

interface JsonPanelProps {
  title: string;
  loading?: boolean;
  error?: Error | null;
  data?: unknown;
  emptyText?: string;
  extra?: ReactNode;
}

function formatJson(data: unknown): string {
  try {
    return JSON.stringify(data, null, 2);
  } catch {
    return String(data);
  }
}

/** API 원본 JSON을 그대로 보여 추측 매핑을 피한다 */
export function JsonPanel({
  title,
  loading,
  error,
  data,
  emptyText = "데이터 없음",
  extra,
}: JsonPanelProps) {
  return (
    <Card title={title} extra={extra} size="small">
      {loading ? <Spin description="불러오는 중..." /> : null}
      {error ? (
        <Alert type="error" showIcon title="API 오류" description={error.message} />
      ) : null}
      {!loading && !error && (data === undefined || data === null) ? (
        <Empty description={emptyText} />
      ) : null}
      {!loading && !error && data !== undefined && data !== null ? (
        <Typography.Paragraph>
          <pre
            style={{
              margin: 0,
              maxHeight: 420,
              overflow: "auto",
              fontSize: 12,
              background: "var(--app-bg, #fafafa)",
              padding: 12,
              borderRadius: 8,
            }}
          >
            {formatJson(data)}
          </pre>
        </Typography.Paragraph>
      ) : null}
    </Card>
  );
}
