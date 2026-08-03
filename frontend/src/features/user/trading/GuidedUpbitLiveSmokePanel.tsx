"use client";

/**
 * Guided Upbit LIVE Smoke — Preview/Confirm.
 * 기본 execute_live=false. 확인문구 없으면 주문 API 0.
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
import { useMemo, useState } from "react";

import { asRecord } from "@/features/admin/utils/dataHelpers";
import * as userApi from "@/features/user/api/userApi";
import { toApiError } from "@/lib/api/apiError";

const BUY_CONFIRM = "UPBIT LIVE BUY CONFIRM";
const SELL_CONFIRM = "UPBIT LIVE SELL CONFIRM";

type StepKey =
  | "account"
  | "preflight"
  | "market"
  | "preview"
  | "confirm"
  | "result";

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
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

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

  const confirmMutation = useMutation({
    mutationFn: () =>
      userApi.postLiveOrderConfirm(Number(ubaId), {
        market,
        side,
        amount: Number(amount),
        limit_price: Number(limitPrice),
        confirmation_text: confirmText,
        arm_token: armToken || undefined,
        // Cursor/기본: 실주문 OFF — 사용자만 화면에서 명시 ON
        execute_live: false,
        preview_id: String(preview?.preview_id ?? ""),
      }),
    onSuccess: (data) => {
      setResult(asRecord(data));
      setStep(5);
    },
  });

  const requiredConfirm = side === "BUY" ? BUY_CONFIRM : SELL_CONFIRM;
  const pf = asRecord(preflightQuery.data);
  const overall = String(pf?.overall_status ?? "-");

  const steps: { title: string; key: StepKey }[] = [
    { title: "계좌", key: "account" },
    { title: "Pre-flight", key: "preflight" },
    { title: "종목", key: "market" },
    { title: "Preview", key: "preview" },
    { title: "확인", key: "confirm" },
    { title: "결과", key: "result" },
  ];

  return (
    <Card
      title="업비트 LIVE 검증 (Guided Smoke)"
      size="small"
      extra={<Tag>실주문 기본 OFF</Tag>}
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="warning"
          showIcon
          title="안전 모드"
          description="Preview/Confirm(execute_live=false)만 기본 실행합니다. 실주문은 확인문구 + 서버 Gate + 사용자가 execute_live를 켠 경우에만 가능합니다. 자동 반복 없음."
        />

        <Steps
          size="small"
          current={step}
          items={steps.map((s) => ({ title: s.title }))}
        />

        <Form layout="vertical">
          <Form.Item label="1. UPBIT 계좌">
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
                2. 계좌 Pre-flight
              </Button>
              <Tag color={overall === "READY_FOR_LIVE" ? "green" : "red"}>
                {overall}
              </Tag>
              <Tag>
                manual_order_allowed=
                {String(pf?.manual_order_allowed ?? false)}
              </Tag>
            </Space>
          ) : null}

          {step >= 1 ? (
            <>
              <Form.Item label="3. 종목 / 방향" style={{ marginTop: 12 }}>
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
                    4~9. Preview
                  </Button>
                </Space>
              </Form.Item>
            </>
          ) : null}

          {previewMutation.error ? (
            <Alert type="error" showIcon title={toApiError(previewMutation.error).message} />
          ) : null}

          {preview ? (
            <Descriptions size="small" bordered column={2} title="Preview">
              <Descriptions.Item label="stage">
                {String(preview.stage)}
              </Descriptions.Item>
              <Descriptions.Item label="adapter_calls">
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
              <Descriptions.Item label="계좌">
                {String(preview.masked_account ?? `UBA ${ubaId}`)}
              </Descriptions.Item>
              <Descriptions.Item label="확인문구">
                {String(preview.confirmation_text_required)}
              </Descriptions.Item>
            </Descriptions>
          ) : null}

          {preview ? (
            <Card size="small" title="10. 최종 확인" style={{ marginTop: 8 }}>
              <Typography.Paragraph type="secondary">
                정확히 입력: <code>{requiredConfirm}</code>
              </Typography.Paragraph>
              <Input
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder={requiredConfirm}
              />
              <Input.Password
                style={{ marginTop: 8 }}
                value={armToken}
                onChange={(e) => setArmToken(e.target.value)}
                placeholder="ARM token (실주문 시에만 필요)"
              />
              <Button
                style={{ marginTop: 12 }}
                danger
                disabled={confirmText !== requiredConfirm}
                loading={confirmMutation.isPending}
                onClick={() => {
                  setStep(4);
                  confirmMutation.mutate();
                }}
              >
                Dry-run Confirm (실주문 OFF)
              </Button>
              <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
                이 화면 기본값은 execute_live=false 입니다. 실주문 Flag/ARM/Unlock을
                Cursor가 켜지 않습니다.
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
              title="11~12. Confirm 결과"
              description={`stage/status=${String(result.stage ?? result.status)} · adapter_calls=${String(result.adapter_create_order_calls ?? 0)} · run_id=${String(result.run_id ?? "-")}`}
            />
          ) : null}
        </Form>
      </Space>
    </Card>
  );
}
