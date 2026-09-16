"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Descriptions,
  Form,
  Input,
  Modal,
  Space,
  Typography,
  message as antdMessage,
} from "antd";
import { useState } from "react";

import type { UserAccount } from "@/features/user/api/userApi";
import * as userApi from "@/features/user/api/userApi";
import { toApiError } from "@/lib/api/apiError";

interface BrokerCredentialPanelProps {
  account: UserAccount;
  open: boolean;
  onClose: () => void;
}

/**
 * STEP 8-5-2 — Credential 등록/교체/검증/폐기.
 * 저장된 Secret은 Form에 재표시하지 않는다.
 */
export function BrokerCredentialPanel({
  account,
  open,
  onClose,
}: BrokerCredentialPanelProps) {
  const [messageApi, contextHolder] = antdMessage.useMessage();
  const [form] = Form.useForm();
  const queryClient = useQueryClient();
  // 사용자가 명시적으로 모드를 바꿀 때만 override (effect setState 금지)
  const [modeOverride, setModeOverride] = useState<
    "register" | "replace" | null
  >(null);
  const isKiwoom = account.account_type === "KIWOOM";
  const isUpbit = account.account_type === "UPBIT";

  const statusQuery = useQuery({
    queryKey: ["user", "credentials", account.account_id],
    queryFn: () =>
      userApi.getUserBrokerCredentialStatus(account.account_id),
    enabled: open && (isKiwoom || isUpbit),
  });

  const derivedMode: "register" | "replace" = statusQuery.data?.connected
    ? "replace"
    : "register";
  const mode = modeOverride ?? derivedMode;

  const closePanel = () => {
    // destroyOnHidden으로 Form이 내려가므로 미연결 reset 호출하지 않음
    setModeOverride(null);
    onClose();
  };
  const invalidate = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["user", "credentials", account.account_id],
    });
    await queryClient.invalidateQueries({
      queryKey: ["user", "accounts"],
    });
  };

  const saveMutation = useMutation({
    mutationFn: async (values: Record<string, string | boolean>) => {
      if (isKiwoom) {
        const body: userApi.KiwoomCredentialPayload = {
          app_key: String(values.app_key),
          secret_key: String(values.secret_key),
          account_number: String(values.account_number),
        };
        if (mode === "replace") {
          return userApi.replaceUserBrokerCredential(
            account.account_id,
            body,
          );
        }
        return userApi.registerUserBrokerCredential(
          account.account_id,
          body,
        );
      }
      const body: userApi.UpbitCredentialPayload = {
        access_key: String(values.access_key),
        secret_key: String(values.secret_key),
      };
      if (mode === "replace") {
        return userApi.replaceUserBrokerCredential(
          account.account_id,
          body,
        );
      }
      return userApi.registerUserBrokerCredential(
        account.account_id,
        body,
      );
    },
    onSuccess: async () => {
      messageApi.success(
        mode === "replace"
          ? "Credential을 교체했습니다."
          : "Credential을 등록했습니다.",
      );
      // destroyOnHidden Modal이 열려 있을 때만 reset
      if (open) {
        form.resetFields();
      }
      await invalidate();
    },
    onError: (error) => messageApi.error(toApiError(error).message),
  });

  const verifyMutation = useMutation({
    mutationFn: () =>
      userApi.verifyUserBrokerCredential(account.account_id),
    onSuccess: async () => {
      messageApi.success("연결 검증을 요청했습니다.");
      await invalidate();
    },
    onError: (error) => messageApi.error(toApiError(error).message),
  });

  const revokeMutation = useMutation({
    mutationFn: () =>
      userApi.revokeUserBrokerCredential(account.account_id),
    onSuccess: async () => {
      messageApi.success("Credential을 폐기했습니다.");
      if (open) {
        form.resetFields();
      }
      await invalidate();
    },
    onError: (error) => messageApi.error(toApiError(error).message),
  });

  const status = statusQuery.data;

  return (
    <Modal
      title={`API Credential — ${account.account_name}`}
      open={open}
      onCancel={closePanel}
      footer={null}
      destroyOnHidden
      width={560}
    >
      {contextHolder}
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title="Secret은 서버에만 암호화 저장되며, 이 화면·로그·API 응답에 원문이 표시되지 않습니다."
      />

      {statusQuery.isError ? (
        <Alert
          type="error"
          title={toApiError(statusQuery.error).message}
          style={{ marginBottom: 12 }}
        />
      ) : null}

      <Descriptions size="small" column={1} bordered style={{ marginBottom: 16 }}>
        <Descriptions.Item label="연결">
          {status?.connected ? "등록됨" : "없음"}
        </Descriptions.Item>
        <Descriptions.Item label="검증 상태">
          {status?.verification_status ?? "-"}
        </Descriptions.Item>
        <Descriptions.Item label="식별자(마스킹)">
          {status?.masked_identifier ?? "-"}
        </Descriptions.Item>
        <Descriptions.Item label="마지막 검증">
          {status?.last_verified_at
            ? new Date(status.last_verified_at).toLocaleString("ko-KR")
            : "-"}
        </Descriptions.Item>
        <Descriptions.Item label="Vault">
          {status?.vault_available ? "사용 가능" : "Master Key 없음"}
        </Descriptions.Item>
        {status?.verification_message ? (
          <Descriptions.Item label="메시지">
            <Typography.Text type="danger">
              {status.verification_message}
            </Typography.Text>
          </Descriptions.Item>
        ) : null}
      </Descriptions>

      <Space style={{ marginBottom: 16 }} wrap>
        <Button
          onClick={() => verifyMutation.mutate()}
          loading={verifyMutation.isPending}
          disabled={!status?.connected}
        >
          연결 검증
        </Button>
        <Button
          danger
          onClick={() => revokeMutation.mutate()}
          loading={revokeMutation.isPending}
          disabled={!status?.connected}
        >
          Credential 폐기
        </Button>
        {status?.connected ? (
          <Button type="link" onClick={() => setModeOverride("replace")}>
            교체 모드
          </Button>
        ) : (
          <Button type="link" onClick={() => setModeOverride("register")}>
            등록 모드
          </Button>
        )}
      </Space>

      <Typography.Paragraph strong style={{ marginBottom: 8 }}>
        {mode === "replace" ? "Credential 교체" : "Credential 등록"}
      </Typography.Paragraph>
      <Form
        form={form}
        layout="vertical"
        onFinish={(values) => saveMutation.mutate(values)}
        autoComplete="off"
      >
        {isKiwoom ? (
          <>
            <Form.Item
              name="app_key"
              label="APP KEY"
              rules={[{ required: true, message: "APP KEY 필요" }]}
            >
              <Input.Password visibilityToggle autoComplete="off" />
            </Form.Item>
            <Form.Item
              name="secret_key"
              label="SECRET KEY"
              rules={[{ required: true, message: "SECRET KEY 필요" }]}
            >
              <Input.Password visibilityToggle autoComplete="new-password" />
            </Form.Item>
            <Form.Item
              name="account_number"
              label="계좌번호"
              rules={[{ required: true, message: "계좌번호 필요" }]}
            >
              <Input.Password visibilityToggle autoComplete="off" />
            </Form.Item>
          </>
        ) : null}
        {isUpbit ? (
          <>
            <Form.Item
              name="access_key"
              label="ACCESS KEY"
              rules={[{ required: true, message: "ACCESS KEY 필요" }]}
            >
              <Input.Password visibilityToggle autoComplete="off" />
            </Form.Item>
            <Form.Item
              name="secret_key"
              label="SECRET KEY"
              rules={[{ required: true, message: "SECRET KEY 필요" }]}
            >
              <Input.Password visibilityToggle autoComplete="new-password" />
            </Form.Item>
          </>
        ) : null}
        <Button
          type="primary"
          htmlType="submit"
          loading={saveMutation.isPending}
          block
        >
          {mode === "replace" ? "교체 저장" : "등록"}
        </Button>
      </Form>
    </Modal>
  );
}
