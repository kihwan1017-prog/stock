/**
 * 24H Operator Authorization / Unattended execution 운영 카드.
 * - 자동운영 중지 = Unattended OFF (Authorization 유지)
 * - 운영 승인 철회 = Authorization REVOKE (별도 확인)
 * - 내부 Lease 자동갱신 ≠ 승인 Horizon 자동연장
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
  /** 내부 Lease(Activation/ARM) 자동갱신 — Auth Horizon 연장 아님 */
  autoRenewEnabled?: boolean;
  authorizedUntil?: string | null;
  authorizationExpiringSoon?: boolean;
  /** Authorization ACTIVE but Unattended OFF */
  authorizationActive?: boolean;
  onStart: () => void;
  onStop: () => void;
  onRevokeAuthorization?: () => void;
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
  authorizedUntil,
  authorizationExpiringSoon,
  authorizationActive,
  onStart,
  onStop,
  onRevokeAuthorization,
}: UnattendedCardProps) {
  const authActive =
    authorizationActive ??
    (String(statusCode || "").toUpperCase() === "ACTIVE" &&
      remainingSeconds > 0);
  const statusLabel = enabled
    ? `자동운영 ON · 남은 ${formatRemaining(remainingSeconds)}`
    : authActive
      ? `자동운영 OFF · 승인 ACTIVE (${formatRemaining(remainingSeconds)})`
      : "OFF";

  return (
    <Alert
      type={enabled ? "success" : authActive ? "warning" : "info"}
      showIcon
      title="24H 운영 승인 / 자동운영 (분리)"
      description={
        <Space orientation="vertical" size={8} style={{ width: "100%" }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Operator Authorization = 유한 승인 Horizon(자동연장 없음). 자동운영 =
            Horizon 안 내부 Lease 갱신·Class A/B. 「자동운영 중지」는 승인을
            철회하지 않습니다.
          </Typography.Text>
          <Space wrap>
            <Typography.Text>상태:</Typography.Text>
            <Tag color={enabled ? "success" : authActive ? "gold" : "default"}>
              {statusLabel}
            </Tag>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {statusCode}
            </Typography.Text>
          </Space>
          <Space wrap>
            <Tag color="default">승인 자동연장: OFF</Tag>
            {autoRenewEnabled ? (
              <Tag color="processing">내부 Lease 자동갱신: ON</Tag>
            ) : (
              <Tag>내부 Lease 자동갱신: OFF</Tag>
            )}
            {authorizationExpiringSoon ? (
              <Tag color="warning">재승인 필요(만료 임박)</Tag>
            ) : null}
          </Space>
          {authorizedUntil ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              운영 승인 만료: {authorizedUntil}
            </Typography.Text>
          ) : null}
          <Space wrap>
            <Typography.Text>승인기간:</Typography.Text>
            <Select
              size="small"
              style={{ width: 120 }}
              value={durationHours}
              disabled={enabled || authActive || loading}
              options={[
                { value: 24, label: "24시간" },
                { value: 48, label: "48시간" },
                { value: 72, label: "72시간" },
              ]}
              onChange={(v) => onDurationHoursChange?.(v as 24 | 48 | 72)}
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
                    : authActive
                      ? "동일 Operator Authorization 안에서 자동운영 재개"
                      : `${durationHours}H Operator Authorization + 자동운영 시작`
                }
              >
                <Button
                  type="primary"
                  loading={loading}
                  disabled={startDisabled}
                  onClick={onStart}
                >
                  {authActive
                    ? "자동운영 재개"
                    : `${durationHours}H 운영 승인 시작`}
                </Button>
              </Tooltip>
            ) : (
              <Button loading={loading} onClick={onStop}>
                자동운영 중지
              </Button>
            )}
            {authActive && onRevokeAuthorization ? (
              <Tooltip title="Operator Authorization을 REVOKED로 철회합니다. 자동운영 중지와 다릅니다.">
                <Button
                  danger
                  loading={loading}
                  onClick={onRevokeAuthorization}
                >
                  운영 승인 철회
                </Button>
              </Tooltip>
            ) : null}
          </Space>
        </Space>
      }
    />
  );
}
