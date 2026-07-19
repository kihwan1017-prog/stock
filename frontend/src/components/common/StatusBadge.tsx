"use client";

import { Badge, Tag } from "antd";

export type StatusType = "healthy" | "warning" | "error" | "disabled" | "unknown";

interface StatusBadgeProps {
  status: StatusType;
  label?: string;
}

const STATUS_META: Record<
  StatusType,
  { color: string; text: string; badgeStatus: "success" | "warning" | "error" | "default" }
> = {
  healthy: { color: "success", text: "정상", badgeStatus: "success" },
  warning: { color: "warning", text: "주의", badgeStatus: "warning" },
  error: { color: "error", text: "오류", badgeStatus: "error" },
  disabled: { color: "default", text: "비활성", badgeStatus: "default" },
  unknown: { color: "processing", text: "확인 중", badgeStatus: "default" },
};

export function StatusBadge({ status, label }: StatusBadgeProps) {
  const meta = STATUS_META[status];
  return (
    <Badge status={meta.badgeStatus} text={<Tag color={meta.color}>{label ?? meta.text}</Tag>} />
  );
}
