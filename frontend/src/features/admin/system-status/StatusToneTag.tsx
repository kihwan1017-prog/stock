"use client";

import { Tag, Tooltip } from "antd";

import {
  mapStatus,
  type StatusTone,
} from "@/features/admin/system-status/statusLabelMap";

function toneColor(tone: StatusTone): string {
  switch (tone) {
    case "success":
      return "success";
    case "processing":
      return "processing";
    case "warning":
      return "warning";
    case "error":
      return "error";
    default:
      return "default";
  }
}

export function StatusToneTag({
  value,
  label,
  tip,
}: {
  value: unknown;
  /** 값 앞에 붙는 항목명 (예: Runtime) */
  label?: string;
  tip?: string;
}) {
  const mapped = mapStatus(value);
  const text = label ? `${label}: ${mapped.labelKo}` : mapped.labelKo;
  const tag = <Tag color={toneColor(mapped.tone)}>{text}</Tag>;
  if (tip) {
    return <Tooltip title={tip}>{tag}</Tooltip>;
  }
  return tag;
}

export function BoolOnOffTag({
  on,
  onLabel = "켜짐",
  offLabel = "꺼짐",
}: {
  on: boolean;
  onLabel?: string;
  offLabel?: string;
}) {
  return (
    <Tag color={on ? "success" : "default"}>{on ? onLabel : offLabel}</Tag>
  );
}
