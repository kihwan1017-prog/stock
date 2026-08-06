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
import {
  normalizeUpbitAccounts,
  pickDefaultUba,
} from "@/features/user/trading/guidedUpbitAccountHelpers";
import { toApiError } from "@/lib/api/apiError";
import { formatLiveSmokeConfirmError } from "@/features/user/trading/liveSmokeConfirmError";

const BUY_CONFIRM = "UPBIT LIVE BUY CONFIRM";
const SELL_CONFIRM = "UPBIT LIVE SELL CONFIRM";

export function GuidedUpbitLiveSmokePanel() {
  const [step, setStep] = useState(0);
  const [ubaId, setUbaId] = useState<number | null>(null);
  const [market, setMarket] = useState("KRW-BTC");
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [orderType, setOrderType] = useState<"MARKET" | "LIMIT">("MARKET");
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

  const liveParsedEmpty =
    accountsQuery.isSuccess &&
    normalizeUpbitAccounts(accountsQuery.data, null).length === 0;

  const userAccountsQuery = useQuery({
    queryKey: ["user", "accounts", "upbit-fallback"],
    queryFn: () => userApi.listUserAccounts({ include_inactive: false }),
    enabled: liveParsedEmpty,
  });

  const upbitAccounts = useMemo(
    () => normalizeUpbitAccounts(accountsQuery.data, userAccountsQuery.data),
    [accountsQuery.data, userAccountsQuery.data],
  );

  // 기본/단일 계좌 자동 선택 → Pre-flight 단계
  useEffect(() => {
    if (ubaId != null) return;
    if (upbitAccounts.length === 0) return;
    const selected = pickDefaultUba(upbitAccounts);
    if (selected == null) return;
    setUbaId(selected);
    setStep(1);
    setPreview(null);
    setOrderTest(null);
    setResult(null);
  }, [upbitAccounts, ubaId]);

  const preflightQuery = useQuery({
    queryKey: ["user", "live-order-preflight", ubaId],
    queryFn: () => userApi.getLiveOrderPreflight(Number(ubaId)),
    enabled: ubaId != null,
    refetchOnMount: "always",
  });

  useEffect(() => {
    if (ubaId != null && preflightQuery.isSuccess && step < 1) {
      setStep(1);
    }
  }, [ubaId, preflightQuery.isSuccess, step]);

  useEffect(() => {
    setOrderTest(null);
  }, [ubaId, market, side, orderType, amount, limitPrice]);

  const previewMutation = useMutation({
    mutationFn: () =>
      userApi.postLiveOrderPreview(Number(ubaId), {
        market,
        side,
        order_type: orderType,
        amount: amount ?? undefined,
        // 시장가는 지정가 미전송 — 현재가로 수량 추정
        limit_price:
          orderType === "LIMIT" ? (limitPrice ?? undefined) : undefined,
      }),
    onSuccess: (data) => {
      const rec = asRecord(data);
      setPreview(rec);
      const min = Number(
        (rec?.min_notional_krw as string | undefined) ?? 5000,
      );
      if (amount == null) setAmount(min);
      // LIMIT만 지정가 자동 채움 (MARKET은 금액≠가격 혼동 방지)
      if (orderType === "LIMIT" && limitPrice == null) {
        const lp = Number(rec?.limit_price ?? rec?.reference_price);
        if (Number.isFinite(lp) && lp > 0) setLimitPrice(lp);
      }
      setStep(3);
    },
  });

  const orderTestMutation = useMutation({
    mutationFn: () => {
      const testPrice = Number(
        limitPrice ??
          preview?.limit_price ??
          preview?.reference_price ??
          undefined,
      );
      return userApi.postLiveOrderTest(Number(ubaId), {
        market,
        side,
        order_type: orderType,
        amount: amount ?? undefined,
        // MARKET는 지정가 미전송 — Preview와 동일
        limit_price:
          orderType === "LIMIT" &&
          Number.isFinite(testPrice) &&
          testPrice > 0
            ? testPrice
            : undefined,
        smoke_buy_run_id:
          side === "SELL" ? smokeBuyRunId ?? undefined : undefined,
      });
    },
    onSuccess: (data) => {
      setOrderTest(asRecord(data));
      setStep(4);
    },
  });

  const confirmMutation = useMutation({
    mutationFn: (executeLive: boolean) => {
      // Confirm API는 아직 LIMIT 경로 — MARKET Preview 시 현재가를 지정가 슬롯에 전달
      const confirmPrice = Number(
        limitPrice ??
          preview?.limit_price ??
          preview?.reference_price ??
          0,
      );
      return userApi.postLiveOrderConfirm(Number(ubaId), {
        market,
        side,
        amount: Number(amount),
        limit_price: confirmPrice,
        confirmation_text: confirmText,
        arm_token: armToken || undefined,
        execute_live: executeLive,
        preview_id: String(preview?.preview_id ?? ""),
        order_test_fingerprint: String(
          orderTest?.order_test_fingerprint ?? "",
        ),
        order_test_tested_at: String(orderTest?.tested_at ?? ""),
        smoke_buy_run_id:
          side === "SELL" ? smokeBuyRunId ?? undefined : undefined,
      });
    },
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

  const accountsLoading =
    accountsQuery.isLoading ||
    (userAccountsQuery.isFetching && upbitAccounts.length === 0);

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
      loading={accountsLoading}
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="warning"
          showIcon
          title="안전 모드"
          description="공식 POST /v1/orders/test 통과(ORDER_TEST_PASSED)+FRESH 후에만 실주문 버튼이 활성화됩니다. Runtime STOP·자동 반복 OFF."
        />

        {accountsQuery.isError ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(accountsQuery.error).message}
          />
        ) : null}

        {!accountsLoading && upbitAccounts.length === 0 ? (
          <Alert
            type="info"
            showIcon
            title="업비트 계좌 없음"
            description="내 계좌에서 UPBIT UBA를 연결·활성화한 뒤 다시 열어주세요."
          />
        ) : null}

        <Steps size="small" current={step} items={steps} />

        <Form layout="vertical">
          <Form.Item label="1. UPBIT 계좌 (1건이면 자동 선택)">
            <Select
              placeholder={accountsLoading ? "계좌 로딩 중…" : "UBA 선택"}
              loading={accountsLoading}
              value={ubaId ?? undefined}
              options={upbitAccounts.map((a) => ({
                value: a.user_broker_account_id,
                label: `UBA ${a.user_broker_account_id}${
                  a.account_alias ? ` · ${a.account_alias}` : ""
                } · LIVE=${a.live_order_enabled ? "ON" : "OFF"} · ARM=${
                  a.live_armed ? "ON" : "OFF"
                }`,
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
                {preflightQuery.isLoading ? "LOADING" : overall}
              </Tag>
              {preflightQuery.isFetching ? (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  Pre-flight 자동 실행 중…
                </Typography.Text>
              ) : null}
            </Space>
          ) : null}

          {preflightQuery.isError ? (
            <Alert
              type="error"
              showIcon
              title={toApiError(preflightQuery.error).message}
            />
          ) : null}

          {step >= 1 ? (
            <Form.Item
              label="4. 종목 / 주문유형 / 금액"
              style={{ marginTop: 12 }}
            >
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
                <Select
                  value={orderType}
                  options={[
                    { value: "MARKET", label: "시장가" },
                    { value: "LIMIT", label: "지정가" },
                  ]}
                  onChange={(v) => {
                    setOrderType(v);
                    setPreview(null);
                    setOrderTest(null);
                  }}
                  style={{ width: 110 }}
                />
                {orderType === "LIMIT" ? (
                  <InputNumber
                    placeholder="지정가 (원)"
                    value={limitPrice ?? undefined}
                    onChange={(v) =>
                      setLimitPrice(v == null ? null : Number(v))
                    }
                    style={{ width: 160 }}
                  />
                ) : null}
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
              <Typography.Paragraph
                type="secondary"
                style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}
              >
                시장가 매수 5000원 → 수량은 BTC 현재가 기준(금액÷현재가).
                지정가에서만 &quot;가격&quot; 입력. 금액 칸에 가격을 넣지 마세요.
              </Typography.Paragraph>
            </Form.Item>
          ) : null}

          {previewMutation.error ? (
            <Alert
              type="error"
              showIcon
              title={toApiError(previewMutation.error).message}
            />
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
              <Descriptions.Item label="order_type">
                {String(preview.order_type)} / {String(preview.upbit_ord_type)}
              </Descriptions.Item>
              <Descriptions.Item label="stage">
                {String(preview.stage)}
              </Descriptions.Item>
              <Descriptions.Item label="현재가(reference)">
                {String(preview.reference_price ?? "-")}
              </Descriptions.Item>
              <Descriptions.Item label="지정가">
                {String(preview.limit_price ?? "-")}
              </Descriptions.Item>
              <Descriptions.Item label="수량(qty)">
                {String(preview.quantity)}
              </Descriptions.Item>
              <Descriptions.Item label="qty 산출">
                {String(preview.quantity_note ?? "-")}
              </Descriptions.Item>
              <Descriptions.Item label="요청 금액">
                {String(preview.requested_amount ?? preview.estimated_amount)}
              </Descriptions.Item>
              <Descriptions.Item label="추정 체결금액">
                {String(preview.estimated_amount)}
              </Descriptions.Item>
              <Descriptions.Item label="수수료(예상)">
                {String(preview.estimated_fee)}
              </Descriptions.Item>
              <Descriptions.Item label="volume 전송">
                {String(preview.volume_sent)}
              </Descriptions.Item>
              <Descriptions.Item label="adapter_create">
                {String(preview.adapter_create_order_calls ?? 0)}
              </Descriptions.Item>
              <Descriptions.Item label="최소금액">
                {String(preview.min_notional_krw ?? "-")}
              </Descriptions.Item>
              <Descriptions.Item label="업비트 body" span={2}>
                <Typography.Text code style={{ fontSize: 11 }}>
                  {JSON.stringify(preview.broker_body ?? {})}
                </Typography.Text>
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
              <Descriptions.Item label="fault_layer">
                {String(
                  (asRecord(orderTest.diagnostics) as Record<string, unknown> | null)
                    ?.fault_layer ?? "-",
                )}
              </Descriptions.Item>
              <Descriptions.Item label="ord_type">
                {String(
                  orderTest.upbit_ord_type ??
                    asRecord(orderTest.request)?.ord_type ??
                    "-",
                )}
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
              <Descriptions.Item label="request body" span={2}>
                <Typography.Text code style={{ fontSize: 11 }}>
                  {JSON.stringify(
                    asRecord(orderTest.request)?.broker_body ??
                      orderTest.request ??
                      {},
                  )}
                </Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="diagnostics" span={2}>
                <Typography.Text code style={{ fontSize: 11 }}>
                  {JSON.stringify(orderTest.diagnostics ?? {})}
                </Typography.Text>
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
                    confirmMutation.mutate(true);
                  }}
                >
                  실주문 Confirm (ORDER_TEST 필수)
                </Button>
              </Space>
            </Card>
          ) : null}

          {confirmMutation.error ? (
            (() => {
              const view = formatLiveSmokeConfirmError(confirmMutation.error);
              if (view.kind === "db_error") {
                return (
                  <Alert
                    type="error"
                    showIcon
                    title={view.title}
                    description={
                      <Space orientation="vertical" size={4}>
                        <ul style={{ margin: 0, paddingLeft: 18 }}>
                          {view.detailLines.map((line) => (
                            <li key={line}>{line}</li>
                          ))}
                        </ul>
                      </Space>
                    }
                  />
                );
              }
              if (view.isRiskRejection) {
                return (
                  <Alert
                    type="warning"
                    showIcon
                    title={view.title}
                    description={
                      <Space orientation="vertical" size={4}>
                        <ul style={{ margin: 0, paddingLeft: 18 }}>
                          {view.detailLines.map((line) => (
                            <li key={line}>{line}</li>
                          ))}
                        </ul>
                        <Typography.Text type="secondary">
                          실제 주문 전송: 없음 · Upbit 주문 UUID: 없음 ·
                          create_order_calls: {view.createOrderCalls}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          다음 조치: 관리자/사용자 Risk 설정 확인
                          {view.errorCode ? ` (${view.errorCode})` : ""}
                        </Typography.Text>
                      </Space>
                    }
                  />
                );
              }
              return (
                <Alert
                  type="error"
                  showIcon
                  title={toApiError(confirmMutation.error).message}
                />
              );
            })()
          ) : null}

          {result ? (
            (() => {
              const statusRaw = String(
                result.status ?? result.stage ?? "",
              ).toUpperCase();
              const isFailed =
                statusRaw === "FAILED" ||
                statusRaw === "REJECTED" ||
                statusRaw.includes("FAIL") ||
                Boolean(result.error_code);
              const isQueued =
                statusRaw === "QUEUED" ||
                statusRaw === "OUTBOX_PENDING" ||
                Boolean(result.queued);
              return (
                <Alert
                  type={isFailed ? "error" : isQueued ? "success" : "info"}
                  showIcon
                  title={
                    isFailed
                      ? "실주문 실패"
                      : isQueued
                        ? "큐 저장 완료 (브로커 전송 전)"
                        : "결과"
                  }
                  description={`status=${String(result.stage ?? result.status)} · create_calls=${String(result.adapter_create_order_calls ?? result.create_order_calls ?? 0)} · run_id=${String(result.run_id ?? "-")} · order_id=${String(result.order_id ?? "없음")}`}
                />
              );
            })()
          ) : null}
        </Form>
      </Space>
    </Card>
  );
}
