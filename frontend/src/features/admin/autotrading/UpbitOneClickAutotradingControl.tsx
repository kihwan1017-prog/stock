"use client";

import { Alert, App, Button, Modal, Space, Typography } from "antd";
import { useState } from "react";

import {
  runUpbitOneClickStart,
  runUpbitOneClickStop,
  type OneClickOutcome,
} from "@/features/admin/autotrading/upbitOneClick";

type Props = {
  ubaId: number;
  strategyId: number | null;
  needsReauthorize: boolean;
  autoTradingRunning: boolean;
  onDone?: () => void;
};

/**
 * Primary one-click START/STOP — safety gate는 backend/FE orchestrator에 위임.
 */
export function UpbitOneClickAutotradingControl({
  ubaId,
  strategyId,
  needsReauthorize,
  autoTradingRunning,
  onDone,
}: Props) {
  const { message } = App.useApp();
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<OneClickOutcome | null>(null);

  const ready = strategyId != null && strategyId > 0;

  const runStart = () => {
    if (!ready || strategyId == null) return;
    Modal.confirm({
      title: needsReauthorize
        ? "24H 재승인 후 자동매매 시작"
        : "자동매매 시작",
      content: needsReauthorize
        ? "UPBIT REAL 자동매매를 24시간 동안 허용하고 스택을 기동합니다. 안전 조건 위반 시 자동 중지됩니다."
        : "기존 안전 Gate(Credential/Recovery/Kill/Activation/LIVE/ARM)를 통과한 뒤 Worker·Exit·Runtime을 기동합니다.",
      okText: needsReauthorize ? "재승인 후 시작" : "시작",
      cancelText: "취소",
      onOk: async () => {
        setBusy(true);
        try {
          const out = await runUpbitOneClickStart(ubaId, strategyId);
          setLast(out);
          if (out.ok) message.success(out.message);
          else message.error(out.message);
          onDone?.();
        } catch (err) {
          message.error(err instanceof Error ? err.message : String(err));
        } finally {
          setBusy(false);
        }
      },
    });
  };

  const runStop = () => {
    if (!ready || strategyId == null) return;
    Modal.confirm({
      title: "자동매매 중지",
      content:
        "Runtime → Exit → Worker 순으로 중지합니다. LIVE/ARM/24H lease는 유지됩니다.",
      okText: "중지",
      okButtonProps: { danger: true },
      cancelText: "취소",
      onOk: async () => {
        setBusy(true);
        try {
          const out = await runUpbitOneClickStop(ubaId, strategyId);
          setLast(out);
          if (out.ok) message.success(out.message);
          else message.error(out.message);
          onDone?.();
        } catch (err) {
          message.error(err instanceof Error ? err.message : String(err));
        } finally {
          setBusy(false);
        }
      },
    });
  };

  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      <Space wrap>
        <Button
          type="primary"
          size="large"
          loading={busy}
          disabled={!ready}
          onClick={runStart}
        >
          {needsReauthorize
            ? "24H 재승인 후 자동매매 시작"
            : "자동매매 시작"}
        </Button>
        <Button
          danger
          size="large"
          loading={busy}
          disabled={!ready || !autoTradingRunning}
          onClick={runStop}
        >
          자동매매 중지
        </Button>
      </Space>
      {!ready ? (
        <Typography.Text type="secondary">
          strategyId가 없어 시작할 수 없습니다. 계좌·전략 바인딩을 확인하세요.
        </Typography.Text>
      ) : null}
      {needsReauthorize ? (
        <Alert
          type="warning"
          showIcon
          title="24H 운영 승인 만료 또는 PROTECTIVE"
          description="자동매매 진입이 차단된 상태입니다. 위 버튼으로 재승인·복구하세요."
        />
      ) : null}
      {last && !last.ok ? (
        <Alert type="error" showIcon title={last.message} />
      ) : null}
    </Space>
  );
}
