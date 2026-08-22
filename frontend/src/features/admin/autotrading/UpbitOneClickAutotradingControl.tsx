"use client";

import { Alert, App, Button, Space, Tag, Timeline, Typography } from "antd";
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

function StepProgress({ outcome }: { outcome: OneClickOutcome | null }) {
  if (!outcome?.steps?.length) return null;
  return (
    <Timeline
      style={{ marginTop: 12 }}
      items={outcome.steps.map((s, index) => {
        const pass =
          s.status === "PASS" ||
          s.status === "ALREADY" ||
          s.status === "SKIP";
        const fail = s.status === "FAIL";
        return {
          key: `${s.name}-${index}`,
          color: fail ? "red" : pass ? "green" : "gray",
          content: (
            <Space>
              <Tag color={fail ? "error" : pass ? "success" : "default"}>
                {fail ? "✕" : pass ? "✓" : "·"} {s.status}
              </Tag>
              <span>{s.message_ko || s.name}</span>
            </Space>
          ),
        };
      })}
    />
  );
}

/**
 * Primary one-click START/STOP — Backend canonical orchestrator API.
 */
export function UpbitOneClickAutotradingControl({
  ubaId,
  strategyId,
  needsReauthorize,
  autoTradingRunning,
  onDone,
}: Props) {
  const { message, modal } = App.useApp();
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<OneClickOutcome | null>(null);

  const ready = strategyId != null && strategyId > 0;

  const runStart = () => {
    if (!ready || strategyId == null) return;
    modal.confirm({
      title: needsReauthorize
        ? "24H 재승인 후 자동매매 시작"
        : "자동매매 시작",
      content: needsReauthorize
        ? "Backend orchestrator가 24H 재승인 후 Worker·Runtime·Runner·Exit를 기동합니다. 안전 Gate 실패 시 fail-closed."
        : "Backend 단일 START API가 Credential/Recovery/Kill/LIVE/ARM Gate를 검사한 뒤 스택을 기동합니다.",
      okText: needsReauthorize ? "24H 재승인 후 시작" : "시작",
      cancelText: "취소",
      onOk: async () => {
        setBusy(true);
        try {
          const out = await runUpbitOneClickStart(ubaId, strategyId, {
            reauthorizeUnattended: needsReauthorize,
          });
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
    modal.confirm({
      title: "자동매매 중지",
      content:
        "신규 매수를 중지합니다. 기존 자동매매 보유 종목의 보호/청산 감시(Exit)·LIVE/ARM은 유지됩니다.",
      okText: "중지",
      okButtonProps: { danger: true },
      cancelText: "취소",
      onOk: async () => {
        setBusy(true);
        try {
          const out = await runUpbitOneClickStop(ubaId, strategyId, {
            mode: "ENTRY_ONLY",
          });
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

  const runFullStop = () => {
    if (!ready || strategyId == null) return;
    modal.confirm({
      title: "완전 종료 (고급)",
      content:
        "Runtime/Exit/Worker를 종료합니다. OPEN 자동매매 포지션이 있으면 차단됩니다. LIVE/ARM OFF는 계좌 화면에서 별도 수행하세요. Kill Switch와 다릅니다.",
      okText: "완전 종료",
      okButtonProps: { danger: true },
      cancelText: "취소",
      onOk: async () => {
        setBusy(true);
        try {
          const out = await runUpbitOneClickStop(ubaId, strategyId, {
            mode: "FULL",
          });
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
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="Canonical Backend Orchestrator"
        description="POST /admin/autotrading/uba/{id}/start|stop — FE 다단계 호출 없음"
      />
      <Space wrap>
        <Button
          type="primary"
          disabled={!ready || busy}
          loading={busy}
          onClick={runStart}
        >
          {needsReauthorize ? "24H 재승인 후 시작" : "자동매매 시작"}
        </Button>
        <Button
          danger
          disabled={!ready || busy}
          loading={busy}
          onClick={runStop}
        >
          자동매매 중지
        </Button>
        <Button disabled={!ready || busy} onClick={runFullStop}>
          완전 종료…
        </Button>
        {autoTradingRunning ? (
          <Tag color="success">가동 중</Tag>
        ) : (
          <Tag>대기</Tag>
        )}
      </Space>
      {last ? (
        <>
          <Typography.Text type={last.ok ? "success" : "danger"}>
            {last.message}
            {last.readiness ? ` · readiness=${last.readiness}` : ""}
          </Typography.Text>
          <StepProgress outcome={last} />
        </>
      ) : null}
    </Space>
  );
}
