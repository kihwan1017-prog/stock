"use client";

/**
 * UPBIT 24/7 Runtime / Outbox Worker / Exit Monitor 개별 제어 + 운영 스택 START.
 * 텍스트 confirmation 입력 없음 — Modal 확인 후 canonical phrase를 API에 전송.
 * LIVE/ARM/Activation/Unattended 강한 승인은 건드리지 않는다.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  List,
  Space,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { toApiError } from "@/lib/api/apiError";

import {
  CONFIRM_START_EXIT_MONITOR,
  CONFIRM_START_RUNTIME,
  CONFIRM_START_WORKER,
  CONFIRM_STOP_EXIT_MONITOR,
  CONFIRM_STOP_RUNTIME,
  CONFIRM_STOP_WORKER,
} from "./upbit24x7Confirmations";
import {
  runUpbit24x7StackStart,
  type StackStartOutcome,
  type StackStartStepStatus,
} from "./upbit24x7StackOrchestrator";

function stepTagColor(status: StackStartStepStatus): string {
  switch (status) {
    case "PASS":
      return "green";
    case "FAIL":
      return "red";
    case "RUNNING":
      return "processing";
    case "SKIPPED":
      return "default";
    default:
      return "default";
  }
}

export function Upbit24x7OperatorControls({
  ubaId,
  strategyId,
}: {
  ubaId: number;
  strategyId: number | null;
}) {
  const { message: messageApi, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [stackOutcome, setStackOutcome] = useState<StackStartOutcome | null>(
    null,
  );
  const [stackPending, setStackPending] = useState(false);

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["admin", "autotrading-readiness", ubaId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["admin", "uba-ops-status", ubaId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["admin", "uba-ops"],
      }),
    ]);
  };

  const runtimeReady = strategyId != null && strategyId > 0;

  const runtimeStart = useMutation({
    mutationFn: () =>
      adminApi.startAdminUbaStrategyRuntime(
        ubaId,
        Number(strategyId),
        CONFIRM_START_RUNTIME,
      ),
    onSuccess: async () => {
      messageApi.success("Strategy Runtime START 완료");
      await invalidate();
    },
    onError: (err) => messageApi.error(toApiError(err).message),
  });

  const runtimeStop = useMutation({
    mutationFn: () =>
      adminApi.stopAdminUbaStrategyRuntime(
        ubaId,
        Number(strategyId),
        CONFIRM_STOP_RUNTIME,
      ),
    onSuccess: async () => {
      messageApi.success("Strategy Runtime STOP 완료");
      await invalidate();
    },
    onError: (err) => messageApi.error(toApiError(err).message),
  });

  const workerStart = useMutation({
    mutationFn: () =>
      adminApi.startAdminLiveOutboxWorker(CONFIRM_START_WORKER),
    onSuccess: async () => {
      messageApi.success("Outbox Worker START 완료");
      await invalidate();
    },
    onError: (err) => messageApi.error(toApiError(err).message),
  });

  const workerStop = useMutation({
    mutationFn: () =>
      adminApi.stopAdminLiveOutboxWorker(CONFIRM_STOP_WORKER),
    onSuccess: async () => {
      messageApi.success("Outbox Worker STOP 완료");
      await invalidate();
    },
    onError: (err) => messageApi.error(toApiError(err).message),
  });

  const exitStart = useMutation({
    mutationFn: () => adminApi.startAdminExitMonitor(CONFIRM_START_EXIT_MONITOR),
    onSuccess: async () => {
      messageApi.success("Exit Monitor START 완료");
      await invalidate();
    },
    onError: (err) => messageApi.error(toApiError(err).message),
  });

  const exitStop = useMutation({
    mutationFn: () => adminApi.stopAdminExitMonitor(CONFIRM_STOP_EXIT_MONITOR),
    onSuccess: async () => {
      messageApi.success("Exit Monitor STOP 완료");
      await invalidate();
    },
    onError: (err) => messageApi.error(toApiError(err).message),
  });

  const confirmThen = (
    title: string,
    content: string,
    okText: string,
    danger: boolean,
    run: () => void,
  ) => {
    modal.confirm({
      title,
      content,
      okText,
      cancelText: "취소",
      okButtonProps: danger ? { danger: true } : undefined,
      onOk: () => {
        run();
      },
    });
  };

  const runStackStart = async () => {
    if (!runtimeReady) {
      messageApi.error("strategy_id가 없어 Runtime START를 진행할 수 없습니다.");
      return;
    }
    setStackPending(true);
    setStackOutcome(null);
    try {
      const outcome = await runUpbit24x7StackStart({
        fetchOpsStatus: () => adminApi.getAdminUbaOpsStatus(ubaId, Number(strategyId)),
        startWorker: (phrase) => adminApi.startAdminLiveOutboxWorker(phrase),
        startExitMonitor: (phrase) => adminApi.startAdminExitMonitor(phrase),
        startRuntime: (phrase) =>
          adminApi.startAdminUbaStrategyRuntime(
            ubaId,
            Number(strategyId),
            phrase,
          ),
      });
      setStackOutcome(outcome);
      await invalidate();
      if (outcome.ok) {
        messageApi.success("운영 스택 START 완료 (Worker · Exit · Runtime)");
      } else {
        messageApi.error(
          `스택 START 실패 @ ${outcome.failedStep}: ${outcome.failedReason ?? ""}`,
        );
      }
    } catch (err) {
      messageApi.error(toApiError(err).message);
    } finally {
      setStackPending(false);
    }
  };

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="운영 제어 (문구 타이핑 없음)"
        description={
          <>
            Runtime / Worker / Exit는 Modal 확인만으로 기동합니다. Backend
            confirmation phrase는 자동 전송되며 safety gate는 완화되지 않습니다.
            LIVE ON · ARM · 24H Unattended · Kill Switch 해제는 강한 승인
            입력을 유지합니다.
          </>
        }
      />

      <Space wrap>
        <Button
          type="primary"
          loading={stackPending}
          disabled={!runtimeReady}
          onClick={() =>
            confirmThen(
              "24H 운영 스택 시작",
              "Preflight → Activation/LIVE/ARM 게이트 확인 후 Worker → Exit Monitor → Runtime 순으로 기동합니다. 어느 단계든 실패하면 즉시 중단(FAIL CLOSED)합니다. LIVE/ARM은 이 버튼으로 켜지지 않습니다.",
              "스택 시작",
              false,
              () => {
                void runStackStart();
              },
            )
          }
        >
          운영 스택 시작
        </Button>
      </Space>

      {stackOutcome ? (
        <Alert
          type={stackOutcome.ok ? "success" : "error"}
          showIcon
          title={
            stackOutcome.ok
              ? "스택 START PASS"
              : `스택 START FAIL @ ${stackOutcome.failedStep}`
          }
          description={
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              {!stackOutcome.ok ? (
                <Typography.Text type="danger">
                  {stackOutcome.failedReason}
                </Typography.Text>
              ) : null}
              {stackOutcome.snapshot ? (
                <Typography.Text style={{ fontSize: 12 }}>
                  LIVE {stackOutcome.snapshot.live} · ARM{" "}
                  {stackOutcome.snapshot.arm} · Runtime{" "}
                  {stackOutcome.snapshot.runtime} · Worker{" "}
                  {stackOutcome.snapshot.outboxWorker} · Exit{" "}
                  {stackOutcome.snapshot.exitMonitor} · AUTO{" "}
                  {stackOutcome.snapshot.autoTradingState}
                  {stackOutcome.snapshot.primaryBlocker
                    ? ` · blocker ${stackOutcome.snapshot.primaryBlocker}`
                    : ""}
                </Typography.Text>
              ) : null}
              <List
                size="small"
                dataSource={stackOutcome.steps}
                renderItem={(item) => (
                  <List.Item style={{ padding: "4px 0" }}>
                    <Space>
                      <Tag color={stepTagColor(item.status)}>{item.status}</Tag>
                      <Typography.Text>{item.id}</Typography.Text>
                      {item.reason ? (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {item.reason}
                        </Typography.Text>
                      ) : null}
                    </Space>
                  </List.Item>
                )}
              />
            </Space>
          }
        />
      ) : null}

      <Typography.Text type="secondary">개별 제어</Typography.Text>
      <Space wrap>
        <Button
          type="primary"
          disabled={!runtimeReady}
          loading={runtimeStart.isPending}
          onClick={() =>
            confirmThen(
              "Runtime START",
              `UBA ${ubaId} / strategy ${strategyId} Runtime을 시작합니다.`,
              "START",
              false,
              () => runtimeStart.mutate(),
            )
          }
        >
          Runtime START
        </Button>
        <Button
          danger
          disabled={!runtimeReady}
          loading={runtimeStop.isPending}
          onClick={() =>
            confirmThen(
              "Runtime STOP",
              `UBA ${ubaId} Runtime을 중지합니다.`,
              "STOP",
              true,
              () => runtimeStop.mutate(),
            )
          }
        >
          Runtime STOP
        </Button>
      </Space>
      <Space wrap>
        <Button
          type="primary"
          loading={workerStart.isPending}
          onClick={() =>
            confirmThen(
              "Outbox Worker START",
              "Live Outbox Worker를 시작합니다. (프로세스 전역)",
              "START",
              false,
              () => workerStart.mutate(),
            )
          }
        >
          Worker START
        </Button>
        <Button
          danger
          loading={workerStop.isPending}
          onClick={() =>
            confirmThen(
              "Outbox Worker STOP",
              "Live Outbox Worker를 중지합니다.",
              "STOP",
              true,
              () => workerStop.mutate(),
            )
          }
        >
          Worker STOP
        </Button>
      </Space>
      <Space wrap>
        <Button
          type="primary"
          loading={exitStart.isPending}
          onClick={() =>
            confirmThen(
              "Exit Monitor START",
              "Exit Monitor를 시작합니다.",
              "START",
              false,
              () => exitStart.mutate(),
            )
          }
        >
          Exit Monitor START
        </Button>
        <Button
          danger
          loading={exitStop.isPending}
          onClick={() =>
            confirmThen(
              "Exit Monitor STOP",
              "Exit Monitor를 중지합니다.",
              "STOP",
              true,
              () => exitStop.mutate(),
            )
          }
        >
          Exit Monitor STOP
        </Button>
      </Space>
    </Space>
  );
}
