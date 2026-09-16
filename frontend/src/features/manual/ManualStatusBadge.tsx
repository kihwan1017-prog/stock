"use client";

import { Tag } from "antd";

import {
  MANUAL_STATUS_COLOR,
  MANUAL_STATUS_LABEL,
  type ManualStatus,
} from "./manualTypes";

export function ManualStatusBadge({ status }: { status?: ManualStatus }) {
  if (!status) return null;
  return (
    <Tag color={MANUAL_STATUS_COLOR[status]}>{MANUAL_STATUS_LABEL[status]}</Tag>
  );
}
