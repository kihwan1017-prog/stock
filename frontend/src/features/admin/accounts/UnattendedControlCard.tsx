/**
 * 24H Operator Authorization (Unattended lease SoT) 운영 카드.
 * 기간은 24/48/72h만 선택 — 무기한 금지.
 */

import { Alert, Button, Select, Space, Tag, Tooltip, Typography } from "antd";

export type UnattendedCardProps = {
  enabled: boolean;
  remainingSeconds: number;
  statusCode: string;
  startDisabled: boolean;
  startDisabledReason: string | null;
  loading?: boolean;
  /** Operator Authorization 승인기간 (시간) */
  durationHours?: 24 | 48 | 72;
  onDurationHoursChange?: (hours: 24 | 48 | 72) => void;
  activationExpiresAt?: string | null;
  armExpiresAt?: string | null;
  autoRenewEnabled?: boolean;
  onStart: () => void;
  onStop: () => void;
};

function formatRemaining(seconds: number): string {
  if (seconds <= 0) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m.toString().padStart(2, "0")}m`;
  return `${m}m`;
}

export function UnattendedControlCard({
  enabled,
  remainingSeconds,
  statusCode,
  startDisabled,
  startDisabledReason,
  loading,
  durationHours = 24,
  onDurationHoursChange,
  activationExpiresAt,
  armExpiresAt,
  autoRenewEnabled,
  onStart,
  onStop,
}: UnattendedCardProps) {
  const statusLabel = enabled
    ? `ON · 남은 ${formatRemaining(remainingSeconds)}`
    : "OFF";

  return (
    <Alert
      type={enabled ? "success" : "info"}
      showIcon
      title="24H 운영 승인 (Operator Authorization)"
      description={
        <Space orientation="vertical" size={8} style={{ width: "100%" }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            SoT: Unattended lease. Activation/ARM 자동 갱신·Class A/B 복구 권한.
            승인기간 종료 시 ENTRY fail-closed · 보유 포지션은 protective EXIT 유지.
          </Typography.Text>
          <Space wrap>
            <Typography.Text>상태:</Typography.Text>
            <Tag color={enabled ? "success" : "default"}>{statusLabel}</Tag>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {statusCode}
            </Typography.Text>
            {autoRenewEnabled ? (
              <Tag color="processing">Auto Renewal ON</Tag>
            ) : null}
          </Space>
          <Space wrap>
            <Typography.Text>승인기간:</Typography.Text>
            <Select
              size="small"
              style={{ width: 120 }}
              value={durationHours}
              disabled={enabled || loading}
              options={[
                { value: 24, label: "24시간" },
                { value: 48, label: "48시간" },
                { value: 72, label: "72시간" },
              ]}
              onChange={(v) =>
                onDurationHoursChange?.(v as 24 | 48 | 72)
              }
            />
          </Space>
          {(activationExpiresAt || armExpiresAt) && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Activation 만료: {activationExpiresAt || "—"} · ARM 만료:{" "}
              {armExpiresAt || "—"}
            </Typography.Text>
          )}
          <Space wrap>
            {!enabled ? (
              <Tooltip
                title={
                  startDisabled
                    ? startDisabledReason || "시작 불가"
                    : `${durationHours}H Operator Authorization 활성화. LIVE/ARM/Activation은 별도 승인.`
                }
              >
                <Button
                  type="primary"
                  loading={loading}
                  disabled={startDisabled}
                  onClick={onStart}
                >
                  {durationHours}H 운영 승인 시작
                </Button>
              </Tooltip>
            ) : (
              <Button danger loading={loading} onClick={onStop}>
                운영 승인 중지
              </Button>
            )}
          </Space>
        </Space>
      }
    />
  );
}
