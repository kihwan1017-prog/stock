"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  InputNumber,
  Space,
  message as antdMessage,
} from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { toApiError } from "@/lib/api/apiError";

/**
 * STEP 8-5-2 — ADMIN Credential 상태/재검증/폐기.
 * Secret 원문 조회 UI는 제공하지 않는다.
 */
export function AdminBrokerCredentialCard() {
  const [messageApi, contextHolder] = antdMessage.useMessage();
  const [ubaId, setUbaId] = useState<number | null>(null);
  const [activeId, setActiveId] = useState<number | null>(null);
  const queryClient = useQueryClient();

  const statusQuery = useQuery({
    queryKey: ["admin", "credentials", activeId],
    queryFn: () =>
      adminApi.getAdminBrokerCredentialStatus(activeId as number),
    enabled: activeId !== null && activeId > 0,
  });

  const verifyMutation = useMutation({
    mutationFn: (id: number) => adminApi.verifyAdminBrokerCredential(id),
    onSuccess: async () => {
      messageApi.success("재검증을 요청했습니다.");
      await queryClient.invalidateQueries({
        queryKey: ["admin", "credentials", activeId],
      });
    },
    onError: (error) => messageApi.error(toApiError(error).message),
  });

  const revokeMutation = useMutation({
    mutationFn: (id: number) => adminApi.revokeAdminBrokerCredential(id),
    onSuccess: async () => {
      messageApi.success("Credential 폐기 및 거래 일시중지를 적용했습니다.");
      await queryClient.invalidateQueries({
        queryKey: ["admin", "credentials", activeId],
      });
    },
    onError: (error) => messageApi.error(toApiError(error).message),
  });

  const status = statusQuery.data;

  return (
    <Card
      title="Broker Credential 상태 (UBA)"
      size="small"
      style={{ marginTop: 16 }}
    >
      {contextHolder}
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 12 }}
        title="ADMIN도 APP/SECRET KEY 원문을 조회·내보내기할 수 없습니다."
        description="Credential 신규 등록/교체는 위 'UPBIT LIVE UBA' 패널에서 수행하세요. 이 카드는 상태 조회·재검증·폐기 전용입니다."
      />
      <Form
        layout="inline"
        onFinish={() => {
          if (ubaId && ubaId > 0) setActiveId(ubaId);
        }}
      >
        <Form.Item label="user_broker_account_id">
          <InputNumber
            min={1}
            value={ubaId ?? undefined}
            onChange={(value) =>
              setUbaId(typeof value === "number" ? value : null)
            }
            style={{ width: 160 }}
          />
        </Form.Item>
        <Button type="primary" htmlType="submit">
          상태 조회
        </Button>
      </Form>

      {statusQuery.isError ? (
        <Alert
          type="error"
          style={{ marginTop: 12 }}
          title={toApiError(statusQuery.error).message}
        />
      ) : null}

      {status ? (
        <>
          <Descriptions
            size="small"
            column={2}
            bordered
            style={{ marginTop: 16 }}
          >
            <Descriptions.Item label="Broker">
              {status.broker_code}
            </Descriptions.Item>
            <Descriptions.Item label="Owner">
              {status.owner_user_id ?? "-"}
            </Descriptions.Item>
            <Descriptions.Item label="등록">
              {status.connected ? "Y" : "N"}
            </Descriptions.Item>
            <Descriptions.Item label="활성">
              {status.is_active ? "Y" : "N"}
            </Descriptions.Item>
            <Descriptions.Item label="검증">
              {status.verification_status ?? "-"}
            </Descriptions.Item>
            <Descriptions.Item label="Key Version">
              {status.key_version ?? "-"}
            </Descriptions.Item>
            <Descriptions.Item label="마스킹">
              {status.masked_identifier ?? "-"}
            </Descriptions.Item>
            <Descriptions.Item label="거래 일시중지">
              {status.account_paused ? "Y" : "N"}
            </Descriptions.Item>
            <Descriptions.Item label="마지막 검증">
              {status.last_verified_at
                ? new Date(status.last_verified_at).toLocaleString("ko-KR")
                : "-"}
            </Descriptions.Item>
            <Descriptions.Item label="마지막 사용">
              {status.last_used_at
                ? new Date(status.last_used_at).toLocaleString("ko-KR")
                : "-"}
            </Descriptions.Item>
          </Descriptions>
          <Space style={{ marginTop: 12 }}>
            <Button
              loading={verifyMutation.isPending}
              disabled={!status.connected}
              onClick={() =>
                activeId && verifyMutation.mutate(activeId)
              }
            >
              재검증
            </Button>
            <Button
              danger
              loading={revokeMutation.isPending}
              disabled={!status.connected}
              onClick={() =>
                activeId && revokeMutation.mutate(activeId)
              }
            >
              Credential 폐기
            </Button>
          </Space>
        </>
      ) : null}
    </Card>
  );
}
