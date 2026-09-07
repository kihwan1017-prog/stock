"use client";

/**
 * 내부 Lease 자동 갱신 패널 (P0.7).
 * Operator Authorization Horizon 자동연장은 지원하지 않는다.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import type { StackStartSnapshot } from "@/features/admin/accounts/upbit24x7StackOrchestrator";
import { parseAutoRenewPreview } from "@/features/admin/upbit/upbitAutoRenewPreview";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

function formatIsoLocal(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function renewStatusTag(status: string | null | undefined) {
  const s = String(status ?? "").toUpperCase();
  if (s === "SUCCESS") return <Tag color="green">성공(레거시)</Tag>;
  if (s === "DENIED") return <Tag color="default">승인연장 거부</Tag>;
  if (s === "BLOCKED") return <Tag color="red">차단</Tag>;
  if (s === "NONE" || !s) return <Tag>—</Tag>;
  return <Tag>{s}</Tag>;
}

type Props = {
  ubaId: number;
  opsSnap: StackStartSnapshot | null;
  unattendedPayload?: Record<string, unknown> | null;
  onChanged?: () => void;
};

export function UpbitUnattendedAutoRenewPanel({
  ubaId,
  opsSnap,
  unattendedPayload,
  onChanged,
}: Props) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const unattended = asRecord(unattendedPayload) ?? {};
  const lastHorizonRenew = asRecord(unattended.last_horizon_auto_renew) ?? {};
  const active =
    Boolean(opsSnap?.unattendedEnabled) &&
    String(opsSnap?.unattendedStatusCode ?? "").toUpperCase() === "ACTIVE";
  const authExpiringSoon = Boolean(unattended.authorization_expiring_soon);

  const previewQ = useQuery({
    queryKey: ["admin", "uba-horizon-auto-renew-preview", ubaId],
    queryFn: () => adminApi.getAdminUbaHorizonAutoRenewPreview(ubaId),
    enabled: ubaId > 0 && active,
    staleTime: 30_000,
    refetchInterval: active ? 60_000 : false,
  });

  const toggleMut = useMutation({
    mutationFn: (enabled: boolean) =>
      adminApi.setAdminUbaUnattendedAutoRenew(ubaId, { enabled }),
    onSuccess: async (_data, enabled) => {
      message.success(
        enabled
          ? "내부 Lease 자동갱신이 켜졌습니다 (승인 Horizon 연장 아님)"
          : "내부 Lease 자동갱신이 꺼졌습니다",
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["admin", "uba-ops-status", ubaId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["admin", "uba-unattended", ubaId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["admin", "uba-horizon-auto-renew-preview", ubaId],
        }),
      ]);
      onChanged?.();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const autoRenewOn =
    opsSnap?.unattendedAutoRenewEnabled ??
    Boolean(unattended.auto_renew_enabled);
  const { preview, precheckBlockers, hasPreviewData } =
    parseAutoRenewPreview(previewQ.data);
  const previewLoading = active && previewQ.isLoading && !previewQ.data;
  const previewEmpty =
    active && !previewQ.isLoading && !previewQ.isError && !hasPreviewData;

  return (
    <Card size="small" title="운영 승인 / 내부 Lease 자동갱신">
      <Space orientation="vertical" size={12} style={{ width: "100%" }}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          운영 승인(Operator Authorization)은 유한 Horizon이며 시스템이 자동으로
          연장하지 않습니다. 아래 스위치는 Activation/ARM 등 내부 Lease만
          갱신하며, 승인 만료시각을 넘지 않습니다.
        </Typography.Paragraph>

        {!active ? (
          <Alert
            type="info"
            showIcon
            title="ACTIVE 운영 승인 lease 필요"
            description="내부 Lease 자동갱신은 활성 무인운영에서만 설정할 수 있습니다."
          />
        ) : null}

        {authExpiringSoon ? (
          <Alert
            type="warning"
            showIcon
            title="재승인 필요 (만료 임박)"
            description="승인 Horizon 자동연장은 없습니다. 만료 전 명시적 재승인이 필요합니다."
          />
        ) : null}

        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="운영 승인">
            <Tag color={active ? "green" : "default"}>
              {active ? "ACTIVE" : "비활성"}
            </Tag>
            {opsSnap?.unattendedRemainingLabel
              ? ` · ${opsSnap.unattendedRemainingLabel}`
              : null}
          </Descriptions.Item>
          <Descriptions.Item label="승인 자동연장">
            <Tag>OFF / 지원 안 함</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="내부 Lease 자동갱신">
            <Space>
              <Switch
                checked={autoRenewOn}
                disabled={!active || toggleMut.isPending}
                loading={toggleMut.isPending}
                onChange={(checked) => toggleMut.mutate(checked)}
              />
              <Typography.Text>
                {autoRenewOn ? "ON" : "OFF"}
              </Typography.Text>
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="운영 승인 만료">
            {formatIsoLocal(
              opsSnap?.unattendedAuthorizedUntil ??
                (unattended.authorized_until != null
                  ? String(unattended.authorized_until)
                  : null),
            )}
          </Descriptions.Item>
          <Descriptions.Item label="만료 임박 경고 시각">
            {formatIsoLocal(
              opsSnap?.nextHorizonRenewCheckAt ??
                (unattended.next_authorization_expiry_warning_at != null
                  ? String(unattended.next_authorization_expiry_warning_at)
                  : unattended.next_horizon_renew_check_at != null
                    ? String(unattended.next_horizon_renew_check_at)
                    : null),
            )}
          </Descriptions.Item>
          <Descriptions.Item label="최근 horizon 시도">
            {renewStatusTag(
              opsSnap?.lastHorizonAutoRenewStatus ??
                (lastHorizonRenew.status as string | undefined),
            )}
          </Descriptions.Item>
          <Descriptions.Item label="최근 사유">
            {opsSnap?.lastHorizonAutoRenewReason ??
              (lastHorizonRenew.reason as string | undefined) ??
              "—"}
          </Descriptions.Item>
        </Descriptions>

        {previewLoading ? (
          <Alert
            type="info"
            showIcon
            title="상태 불러오는 중"
            description="만료/연장 정책을 조회하고 있습니다."
          />
        ) : null}

        {previewEmpty ? (
          <Alert
            type="info"
            showIcon
            title="사전 점검 정보 없음"
            description="Dry 평가 데이터가 아직 없습니다. 새로고침을 눌러 조회하세요."
          />
        ) : null}

        {active && hasPreviewData ? (
          <Alert
            type="info"
            showIcon
            title="Dry 평가 (READ-ONLY) — 승인 자동연장 미지원"
            description={
              <Space orientation="vertical" size={4}>
                <Typography.Text>
                  would_extend_operator_authorization:{" "}
                  <Typography.Text strong>
                    {String(
                      preview.would_extend_operator_authorization ??
                        preview.would_renew ??
                        false,
                    )}
                  </Typography.Text>
                  {preview.authorized_until
                    ? ` · 승인 만료 유지 ${formatIsoLocal(String(preview.authorized_until))}`
                    : null}
                </Typography.Text>
                {precheckBlockers.length ? (
                  <Typography.Text type="warning">
                    lease precheck blockers: {precheckBlockers.join(", ")}
                  </Typography.Text>
                ) : (
                  <Typography.Text type="secondary">
                    lease precheck: PASS (Auth Horizon은 연장되지 않음)
                  </Typography.Text>
                )}
              </Space>
            }
          />
        ) : null}

        <Button
          size="small"
          loading={previewQ.isFetching}
          disabled={!active}
          onClick={() => void previewQ.refetch()}
        >
          Dry 평가 새로고침
        </Button>
      </Space>
    </Card>
  );
}
