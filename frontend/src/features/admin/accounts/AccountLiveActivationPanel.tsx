"use client";

/**
 * ACCOUNT-scope Activation 단계 UI.
 * validate → request → approve 를 한 버튼으로 묶지 않는다.
 * Production 자동 호출은 하지 않으며, 사용자가 각 단계를 명시 실행한다.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Form, Input, InputNumber, Space, Typography } from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

import {
  approvalPhraseForBroker,
  buildAccountActivationApprovePayload,
  buildAccountActivationPayload,
  buildAccountActivationRequestPayload,
  extractTransitionId,
  isValidateReady,
} from "./accountLiveActivation";

type Props = {
  ubaId: number;
  brokerCode: string;
  maxOrderAmount?: unknown;
  maxDailyLoss?: unknown;
  notifySuccess: (text: string) => void;
  notifyError: (err: unknown) => void;
};

export function AccountLiveActivationPanel({
  ubaId,
  brokerCode,
  maxOrderAmount,
  maxDailyLoss,
  notifySuccess,
  notifyError,
}: Props) {
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [validateResult, setValidateResult] = useState<unknown>(null);
  const [requestResult, setRequestResult] = useState<unknown>(null);
  const phrase = approvalPhraseForBroker(brokerCode);

  const invalidate = async () => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.admin.liveTransitionHistory(),
    });
    await queryClient.invalidateQueries({
      queryKey: queryKeys.admin.liveTransitionActive(),
    });
  };

  const validateMutation = useMutation({
    mutationFn: async () => {
      const values = form.getFieldsValue();
      const body = buildAccountActivationPayload({
        brokerCode,
        userBrokerAccountId: ubaId,
        maxOrderAmount: values.max_order_amount ?? maxOrderAmount,
        maxDailyLoss: values.max_daily_loss ?? maxDailyLoss,
        paperValidationApproved: Boolean(values.paper_validation_approved),
      });
      if (!body) {
        throw new Error("ACCOUNT Activation payload를 만들 수 없습니다");
      }
      return adminApi.validateLiveTransition(body);
    },
    onSuccess: (data) => {
      setValidateResult(data);
      notifySuccess(
        isValidateReady(data)
          ? "Activation 검증 READY"
          : "Activation 검증 — READY 아님",
      );
    },
    onError: (err) => notifyError(err),
  });

  const requestMutation = useMutation({
    mutationFn: async () => {
      if (!isValidateReady(validateResult)) {
        throw new Error("검증 READY 확인 후 Activation 요청이 가능합니다");
      }
      const values = form.getFieldsValue();
      const body = buildAccountActivationRequestPayload({
        brokerCode,
        userBrokerAccountId: ubaId,
        requestedBy: String(values.requested_by ?? "").trim(),
        maxOrderAmount: values.max_order_amount ?? maxOrderAmount,
        maxDailyLoss: values.max_daily_loss ?? maxDailyLoss,
        paperValidationApproved: Boolean(values.paper_validation_approved),
      });
      if (!body) {
        throw new Error("Activation 요청 payload가 올바르지 않습니다");
      }
      return adminApi.requestLiveTransition(body);
    },
    onSuccess: async (data) => {
      setRequestResult(data);
      const id = extractTransitionId(data);
      notifySuccess(
        id != null
          ? `Activation 요청 완료 (ID ${id})`
          : "Activation 요청 완료",
      );
      await invalidate();
    },
    onError: (err) => notifyError(err),
  });

  const approveMutation = useMutation({
    mutationFn: async () => {
      const values = form.getFieldsValue();
      const transitionId = extractTransitionId(requestResult);
      if (transitionId == null) {
        throw new Error("요청 ID 확인 후 승인할 수 있습니다");
      }
      const body = buildAccountActivationApprovePayload({
        brokerCode,
        userBrokerAccountId: ubaId,
        approvedBy: String(values.approved_by ?? "").trim(),
        approvalPhrase: String(values.approval_phrase ?? ""),
        reason: "ADMIN_UI_ACCOUNT_ACTIVATION_APPROVE",
      });
      if (!body) {
        throw new Error("승인 문구 또는 승인자가 올바르지 않습니다");
      }
      return adminApi.approveLiveTransition(transitionId, body);
    },
    onSuccess: async () => {
      notifySuccess("Activation 승인 완료 — ACTIVE 상태를 확인하세요");
      await invalidate();
    },
    onError: (err) => notifyError(err),
  });

  const requestId = extractTransitionId(requestResult);
  const validateReady = isValidateReady(validateResult);

  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="ACCOUNT Activation (단계 분리)"
        description="검증 → 요청 → 승인을 한 번에 실행하지 않습니다. BROKER scope는 제공하지 않습니다."
      />
      <Typography.Text type="secondary">
        UBA {ubaId} · {brokerCode} · scope=ACCOUNT · ttl_hours=1
      </Typography.Text>
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          max_order_amount: Number(maxOrderAmount ?? 5000),
          max_daily_loss: Number(maxDailyLoss ?? 5000),
          requested_by: "admin",
          approved_by: "admin",
          approval_phrase: "",
        }}
      >
        <Form.Item name="max_order_amount" label="max_order_amount">
          <InputNumber min={1} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="max_daily_loss" label="max_daily_loss">
          <InputNumber min={1} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="requested_by" label="requested_by" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="approved_by" label="approved_by" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item
          name="approval_phrase"
          label="approval_phrase"
          extra={phrase ? `정확히 입력: ${phrase}` : "지원하지 않는 broker"}
        >
          <Input placeholder={phrase ?? ""} autoComplete="off" />
        </Form.Item>
      </Form>
      <Space wrap>
        <Button
          loading={validateMutation.isPending}
          onClick={() => validateMutation.mutate()}
        >
          1. Activation 검증
        </Button>
        <Button
          disabled={!validateReady}
          loading={requestMutation.isPending}
          onClick={() => requestMutation.mutate()}
        >
          3. Activation 요청
        </Button>
        <Button
          type="primary"
          danger
          disabled={requestId == null}
          loading={approveMutation.isPending}
          onClick={() => approveMutation.mutate()}
        >
          5. Activation 승인
        </Button>
      </Space>
      {validateResult != null ? (
        <Alert
          type={validateReady ? "success" : "warning"}
          title={validateReady ? "2. READY 확인" : "2. READY 아님"}
          description={
            <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>
              {JSON.stringify(validateResult, null, 2)}
            </Typography.Paragraph>
          }
        />
      ) : null}
      {requestId != null ? (
        <Alert
          type="success"
          title={`4. 요청 ID 확인: ${requestId}`}
        />
      ) : null}
      {validateMutation.error ? (
        <Alert type="error" title={toApiError(validateMutation.error).message} />
      ) : null}
    </Space>
  );
}
