"use client";

import { Button, Empty, Space, Typography } from "antd";

type EmptyVariant = "no-data" | "not-implemented" | "no-results";

interface EmptyStateProps {
  variant?: EmptyVariant;
  title?: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
}

const VARIANT_COPY: Record<EmptyVariant, { title: string; description: string }> = {
  "no-data": {
    title: "데이터가 없습니다",
    description: "표시할 항목이 없습니다.",
  },
  "not-implemented": {
    title: "아직 구현되지 않았습니다",
    description: "후속 STEP에서 연결됩니다.",
  },
  "no-results": {
    title: "검색 결과가 없습니다",
    description: "조건을 바꿔 다시 시도해 주세요.",
  },
};

export function EmptyState({
  variant = "no-data",
  title,
  description,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  const copy = VARIANT_COPY[variant];

  return (
    <Empty
      image={Empty.PRESENTED_IMAGE_SIMPLE}
      description={
        <Space orientation="vertical" size={4}>
          <Typography.Text strong>{title ?? copy.title}</Typography.Text>
          <Typography.Text type="secondary">{description ?? copy.description}</Typography.Text>
        </Space>
      }
    >
      {actionLabel && onAction ? (
        <Button type="primary" onClick={onAction}>
          {actionLabel}
        </Button>
      ) : null}
    </Empty>
  );
}
