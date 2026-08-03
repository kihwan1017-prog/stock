"use client";

/**
 * Guided Upbit LIVE Smoke — Pre-flight → Preview → Order Test → Confirm.
 * 기본 execute_live=false. ORDER_TEST_PASSED 전에는 실주문 버튼 비활성.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Steps,
  Tag,
  Typography,
} from "antd";
import { useEffect, useMemo, useState } from "react";

import { asRecord } from "@/features/admin/utils/dataHelpers";
import * as userApi from "@/features/user/api/userApi";
import { toApiError } from "@/lib/api/apiError";

const BUY_CONFIRM = "UPBIT LIVE BUY CONFIRM";
const SELL_CONFIRM = "UPBIT LIVE SELL CONFIRM";

export function GuidedUpbitLiveSmokePanel() {
  const [step, setStep] = useState(0);
  const [ubaId, setUbaId] = useState<number | null>(null);
  const [market, setMarket] = useState("KRW-BTC");
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [limitPrice, setLimitPrice] = useState<number | null>(null);
  const [amount, setAmount] = useState<number | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [armToken, setArmToken] = useState("");
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [orderTest, setOrderTest] = useState<Record<string, unknown> | null>(
    null,
  );
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [smokeBuyRunId, setSmokeBuyRunId] = useState<string | null>(null);

  const accountsQuery = useQuery({
    queryKey: ["user", "live-order-status"],
    queryFn: () => userApi.listMyLiveOrderStatus(),
  });

  const upbitAccounts = useMemo(() => {
    const raw = accountsQuery.data;
    const items =
      (asRecord(raw)?.items as Record<string, unknown>[] | undefined) ??
      (Array.isArray(raw) ? (raw as Record<string, unknown>[]) : []);
    return items.filter(
      (a) => String(a.broker_code || "").toUpperCase() === "UPBIT",
    );
  }, [accountsQuery.data]);

  const preflightQuery = useQuery({
    queryKey: ["user", "live-order-preflight", ubaId],
    queryFn: () => userApi.getLiveOrderPreflight(Number(ubaId)),
    enabled: ubaId != null && step >= 1,
  });

  // 입력 변경 시 Order Test 무효화
  useEffect(() => {
    setOrderTest(null);
  }, [ubaId, market, side, amount, limitPrice]);

  const previewMutation = useMutation({
    mutationFn: () =>
      userApi.postLiveOrderPreview(Number(ubaId), {
        market,
        side,
        amount: amount ?? undefined,
        limit_price: limitPrice ?? undefined,
      }),
    onSuccess: (data) => {
      setPreview(asRecord(data));
      const min = Number(
        (asRecord(data)?.min_notional_krw as string | undefined) ?? 5000,
      );
      if (amount == null) setAmount(min);
      const lp = Number(asRecord(data)?.limit_price);
      if (Number.isFinite(lp) && limitPrice == null) setLimitPrice(lp);
      setStep(3);
    },
  });

  const orderTestMutation = useMutation({
    mutationFn: () =>
      userApi.postLiveOrderTest(Number(ubaId), {
        market,
        side,
        amount: amount ?? undefined,
        limit_price: limitPrice ?? undefined,
        smoke_buy_run_id: side === "SELL" ? smokeBuyRunId ?? undefined : undefined,
      }),
    onSuccess: (data) => {
      setOrderTest(asRecord(data));
      setStep(4);
    },
  });

  const confirmMutation = useMutation({
    mutationFn: (executeLive: boolean) =>
      userApi.postLiveOrderConfirm(Number(ubaId), {
        market,
        side,
        amount: Number(amount),
        limit_price: Number(limitPrice),
        confirmation_text: confirmText,
        arm_token: armToken || undefined,
        execute_live: executeLive,
        preview_id: String(preview?.preview_id ?? ""),
        order_test_fingerprint: String(
          orderTest?.order_test_fingerprint ?? "",
        ),
        order_test_tested_at: String(orderTest?.tested_at ?? ""),
        smoke_buy_run_id: side === "SELL" ? smokeBuyRunId ?? undefined : undefined,
      }),
    onSuccess: (data) => {
      const rec = asRecord(data);
      setResult(rec);
      if (side === "BUY" && rec?.run_id) {
        setSmokeBuyRunId(String(rec.run_id));
      }
      setStep(6);
    },
  });

  const requiredConfirm = side === "BUY" ? BUY_CONFIRM : SELL_CONFIRM;
  const pf = asRecord(preflightQuery.data);
  const overall = String(pf?.overall_status ?? "-");
  const orderTestPassed = Boolean(orderTest?.test_passed);
  const orderTestFresh =
    orderTestPassed &&
    !!orderTest?.expires_at &&
    Date.parse(String(orderTest.expires_at)) > Date.now();
  const liveButtonEnabled =
    orderTestPassed &&
    orderTestFresh &&
    confirmText === requiredConfirm &&
    !(side === "SELL" && !smokeBuyRunId);

  const steps = [
    { title: "계좌" },
    { title: "Pre-flight" },
    { title: "종목" },
    { title: "Preview" },
    { title: "Order Test" },
    { title: "확인" },
    { title: "결과" },
  ];

  return (
    <Card
      title="업비트 LIVE 검증 (Guided Smoke)"
      size="small"
      extra={<Tag>실주문 기본 OFF · Order Test 필수</Tag>}
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="warning"
          showIcon
          title="안전 모드"
          description="공식 POST /v1/orders/test 통과(ORDER_TEST_PASSED)+FRESH 후에만 실주문 버튼이 활성화됩니다. Cursor 기본은 Dry-run Confirm만 사용합니다. Runtime STOP·자동 반복 OFF."
        />

        <Steps size="small" current={step} items={steps} />

        <Form layout="vertical">
          <Form.Item label="1. UPBIT 계좌 (사용자 선택)">
            <Select
              placeholder="UBA 선택"
              value={ubaId ?? undefined}
              options={upbitAccounts.map((a) => ({
                value: Number(a.user_broker_account_id),
                label: `UBA ${a.user_broker_account_id} · LIVE=${a.live_order_enabled ? "ON" : "OFF"} · ARM=${a.live_armed ? "ON" : "OFF"}`,
              }))}
              onChange={(v) => {
                setUbaId(Number(v));
                setStep(1);
                setPreview(null);
                setOrderTest(null);
                setResult(null);
              }}
              style={{ width: "100%" }}
            />
          </Form.Item>

          {ubaId != null ? (
            <Space wrap>
              <Button
                loading={preflightQuery.isFetching}
                onClick={() => {
                  void preflightQuery.refetch();
                  setStep(1);
                }}
              >
                2~3. 계좌 Pre-flight
              </Button>
              <Tag color={overall === "READY_FOR_LIVE" ? "green" : "red"}>
                {overall}
              </Tag>
            </Space>
          ) : null}

          {step >= 1 ? (
            <Form.Item label="4. 종목 / 방향 (자동 선택 없음)" style={{ marginTop: 12 }}>
              <Space wrap>
                <Select
                  value={market}
                  options={[
                    { value: "KRW-BTC", label: "KRW-BTC" },
                    { value: "KRW-ETH", label: "KRW-ETH" },
                    { value: "KRW-XRP", label: "KRW-XRP" },
                  ]}
                  onChange={setMarket}
                  style={{ width: 140 }}
                />
                <Select
                  value={side}
                  options={[
                    { value: "BUY", label: "매수" },
                    { value: "SELL", label: "매도" },
                  ]}
                  onChange={(v) => setSide(v)}
                  style={{ width: 100 }}
                />
                <InputNumber
                  placeholder="LIMIT 가격"
                  value={limitPrice ?? undefined}
                  onChange={(v) => setLimitPrice(v == null ? null : Number(v))}
                  style={{ width: 160 }}
                />
                <InputNumber
                  placeholder="금액(KRW)"
                  value={amount ?? undefined}
                  onChange={(v) => setAmount(v == null ? null : Number(v))}
                  style={{ width: 140 }}
                />
                <Button
                  type="primary"
                  loading={previewMutation.isPending}
                  disabled={ubaId == null}
                  onClick={() => {
                    setStep(2);
                    previewMutation.mutate();
                  }}
                >
                  5~6. Preview
                </Button>
                <Button
                  loading={orderTestMutation.isPending}
                  disabled={ubaId == null || !preview}
                  onClick={() => orderTestMutation.mutate()}
                >
                  7. 업비트 주문 생성 테스트
                </Button>
              </Space>
            </Form.Item>
          ) : null}

          {previewMutation.error ? (
            <Alert type="error" showIcon title={toApiError(previewMutation.error).message} />
          ) : null}
          {orderTestMutation.error ? (
            <Alert
              type="error"
              showIcon
              title={toApiError(orderTestMutation.error).message}
            />
          ) : null}

          {preview ? (
            <Descriptions size="small" bordered column={2} title="Preview">
              <Descriptions.Item label="stage">
                {String(preview.stage)}
              </Descriptions.Item>
              <Descriptions.Item label="adapter_create">
                {String(preview.adapter_create_order_calls ?? 0)}
              </Descriptions.Item>
              <Descriptions.Item label="수량">
                {String(preview.quantity)}
              </Descriptions.Item>
              <Descriptions.Item label="예상금액">
                {String(preview.estimated_amount)}
              </Descriptions.Item>
              <Descriptions.Item label="수수료(예상)">
                {String(preview.estimated_fee)}
              </Descriptions.Item>
              <Descriptions.Item label="최소금액">
                {String(preview.min_notional_krw)}
              </Descriptions.Item>
            </Descriptions>
          ) : null}

          {orderTest ? (
            <Descriptions
              size="small"
              bordered
              column={2}
              title="Order Test (POST /v1/orders/test)"
              style={{ marginTop: 8 }}
            >
              <Descriptions.Item label="status">
                <Tag color={orderTestPassed ? "green" : "red"}>
                  {String(orderTest.status)}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="fresh">
                {orderTestFresh ? "FRESH" : "STALE/FAIL"}
              </Descriptions.Item>
              <Descriptions.Item label="min_amount">
                {String(orderTest.minimum_order_amount)}
              </Descriptions.Item>
              <Descriptions.Item label="available">
                {String(orderTest.available_balance ?? "-")}
              </Descriptions.Item>
              <Descriptions.Item label="fee">
                {String(orderTest.estimated_fee)}
              </Descriptions.Item>
              <Descriptions.Item label="create_order_calls">
                {String(orderTest.adapter_create_order_calls ?? 0)}
              </Descriptions.Item>
              <Descriptions.Item label="errors" span={2}>
                {JSON.stringify(orderTest.validation_errors ?? [])}
              </Descriptions.Item>
            </Descriptions>
          ) : null}

          {preview ? (
            <Card size="small" title="10. 최종 확인" style={{ marginTop: 8 }}>
              <Typography.Paragraph type="secondary">
                정확히 입력: <code>{requiredConfirm}</code>
              </Typography.Paragraph>
              {side === "SELL" && !smokeBuyRunId ? (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 8 }}
                  title="매수 체결(run) 확인 전 매도 비활성"
                />
              ) : null}
              <Input
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder={requiredConfirm}
              />
              <Input.Password
                style={{ marginTop: 8 }}
                value={armToken}
                onChange={(e) => setArmToken(e.target.value)}
                placeholder="ARM token (실주문 시에만)"
              />
              <Space wrap style={{ marginTop: 12 }}>
                <Button
                  disabled={confirmText !== requiredConfirm}
                  loading={confirmMutation.isPending}
                  onClick={() => {
                    setStep(5);
                    confirmMutation.mutate(false);
                  }}
                >
                  Dry-run Confirm (실주문 OFF)
                </Button>
                <Button
                  danger
                  disabled={!liveButtonEnabled}
                  loading={confirmMutation.isPending}
                  onClick={() => {
                    setStep(5);
                    // 사용자 명시 시에만 — Cursor는 이 버튼을 누르지 않음
                    confirmMutation.mutate(true);
                  }}
                >
                  실주문 Confirm (ORDER_TEST 필수)
                </Button>
              </Space>
              <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
                실주문 버튼은 ORDER_TEST_PASSED+FRESH+확인문구 일치 시에만 활성.
                Flag/ARM/Unlock은 Cursor가 변경하지 않습니다.
              </Typography.Paragraph>
            </Card>
          ) : null}

          {confirmMutation.error ? (
            <Alert type="error" showIcon title={toApiError(confirmMutation.error).message} />
          ) : null}

          {result ? (
            <Alert
              type="success"
              showIcon
              title="결과"
              description={`status=${String(result.stage ?? result.status)} · create_calls=${String(result.adapter_create_order_calls ?? 0)} · run_id=${String(result.run_id ?? "-")}`}
            />
          ) : null}
        </Form>
      </Space>
    </Card>
  );
}
