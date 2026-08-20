/**
 * 24H Unattended 운영 카드 — ops-status 실패와 무관하게 항상 노출.
 */

import { Alert, Button, Space, Tag, Tooltip, Typography } from "antd";

export type UnattendedCardProps = {
  enabled: boolean;
  remainingSeconds: number;
  statusCode: string;
  startDisabled: boolean;
  startDisabledReason: string | null;
  loading?: boolean;
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
      title="24시간 무인운영"
      description={
        <Space orientation="vertical" size={8} style={{ width: "100%" }}>
          <Space wrap>
            <Typography.Text>상태:</Typography.Text>
            <Tag color={enabled ? "success" : "default"}>{statusLabel}</Tag>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {statusCode}
            </Typography.Text>
          </Space>
          <Space wrap>
            {!enabled ? (
              <Tooltip
                title={
                  startDisabled
                    ? startDisabledReason || "시작 불가"
                    : "관리자 승인 후 24H Unattended lease 활성화. 성공 시 운영 스택(Worker/Exit/Runtime) 기동을 제안합니다."
                }
              >
                <Button
                  type="primary"
                  loading={loading}
                  disabled={startDisabled}
                  onClick={onStart}
                >
                  24시간 무인운영 시작
                </Button>
              </Tooltip>
            ) : (
              <Button danger loading={loading} onClick={onStop}>
                24시간 무인운영 중지
              </Button>
            )}
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            LIVE ON / ARM / Activation은 LIVE 패널 강한 승인. Runtime·Worker는
            「운영 스택 시작」또는 개별 Modal 확인(문구 타이핑 없음).
          </Typography.Text>
        </Space>
      }
    />
  );
}
