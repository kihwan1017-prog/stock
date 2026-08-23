"use client";

/**
 * 24H 무인운영 자동 갱신 — compact 운영자 패널.
 * ACTIVE lease에서만 toggle 가능; fail-closed precheck는 서버 SoT.
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
  if (s === "SUCCESS") return <Tag color="green">성공</Tag>;
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
  const unattended = asRecord(unattendedPayload);
  const active =
    Boolean(opsSnap?.unattendedEnabled) &&
    String(opsSnap?.unattendedStatusCode ?? "").toUpperCase() === "ACTIVE";

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
          ? "24H 자동 갱신이 켜졌습니다"
          : "24H 자동 갱신이 꺼졌습니다",
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
  const preview = asRecord(previewQ.data);
  const precheck = asRecord(preview.precheck);
  const precheckBlockers = Array.isArray(precheck.blockers)
    ? precheck.blockers.map((x) => String(x))
    : [];

  return (
    <Card size="small" title="24H 무인운영 · 자동 갱신">
      <Space orientation="vertical" size={12} style={{ width: "100%" }}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          만료 전에 안전조건을 재검증하고 통과한 경우에만 24시간 무인운영
          승인을 자동 연장합니다. 무조건 연장하지 않습니다.
        </Typography.Paragraph>

        {!active ? (
          <Alert
            type="info"
            showIcon
            title="ACTIVE 24H lease 필요"
            description="자동 갱신은 활성 무인운영 lease에서만 설정할 수 있습니다. 먼저 24H 무인운영을 시작하거나 재승인하세요."
          />
        ) : null}

        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="24H 무인운영">
            <Tag color={active ? "green" : "default"}>
              {active ? "활성" : "비활성"}
            </Tag>
            {opsSnap?.unattendedRemainingLabel
              ? ` · ${opsSnap.unattendedRemainingLabel}`
              : null}
          </Descriptions.Item>
          <Descriptions.Item label="자동 갱신">
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
          <Descriptions.Item label="현재 만료">
            {formatIsoLocal(
              opsSnap?.unattendedAuthorizedUntil ??
                (unattended.authorized_until != null
                  ? String(unattended.authorized_until)
                  : null),
            )}
          </Descriptions.Item>
          <Descriptions.Item label="다음 갱신 검사">
            {formatIsoLocal(
              opsSnap?.nextHorizonRenewCheckAt ??
                (unattended.next_horizon_renew_check_at != null
                  ? String(unattended.next_horizon_renew_check_at)
                  : null),
            )}
          </Descriptions.Item>
          <Descriptions.Item label="최근 갱신">
            {renewStatusTag(
              opsSnap?.lastHorizonAutoRenewStatus ??
                asRecord(unattended.last_horizon_auto_renew).status,
            )}
          </Descriptions.Item>
          <Descriptions.Item label="최근 갱신 사유">
            {opsSnap?.lastHorizonAutoRenewReason ??
              asRecord(unattended.last_horizon_auto_renew).reason ??
              "—"}
          </Descriptions.Item>
        </Descriptions>

        {active && previewQ.data ? (
          <Alert
            type={preview.would_renew ? "success" : "info"}
            showIcon
            title="Dry 갱신 평가 (READ-ONLY)"
            description={
              <Space orientation="vertical" size={4}>
                <Typography.Text>
                  would_renew:{" "}
                  <Typography.Text strong>
                    {String(preview.would_renew ?? false)}
                  </Typography.Text>
                  {preview.projected_authorized_until
                    ? ` · 예상 만료 ${formatIsoLocal(String(preview.projected_authorized_until))}`
                    : null}
                </Typography.Text>
                {precheckBlockers.length ? (
                  <Typography.Text type="warning">
                    precheck blockers: {precheckBlockers.join(", ")}
                  </Typography.Text>
                ) : (
                  <Typography.Text type="secondary">
                    precheck: PASS
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
          Dry 갱신 평가 새로고침
        </Button>
      </Space>
    </Card>
  );
}
