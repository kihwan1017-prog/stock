"use client";

/**
 * UPBIT 자동매매 운영 — 스택 시작/중지 중심 UI.
 * 개별 Runtime/Worker/Exit는 「고급 제어」로 접는다.
 * LIVE/ARM/Unattended 강한 승인은 건드리지 않는다.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Collapse,
  Descriptions,
  Space,
  Tag,
  Tooltip,
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
  runUpbit24x7StackStop,
  snapshotFromOpsStatus,
  type StackStartOutcome,
  type StackStartSnapshot,
  type StackStartStepStatus,
} from "./upbit24x7StackOrchestrator";
import { UpbitFullMarketControls } from "./UpbitFullMarketControls";
import { UpbitPortfolioControls } from "./UpbitPortfolioControls";

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

function onOffTag(on: boolean, onLabel = "ON", offLabel = "OFF") {
  return <Tag color={on ? "green" : "default"}>{on ? onLabel : offLabel}</Tag>;
}

function autoTradingTag(state: string) {
  const u = state.toUpperCase();
  const color =
    u === "RUNNING"
      ? "green"
      : u === "WAITING_SIGNAL"
        ? "processing"
        : u === "BLOCKED"
          ? "red"
          : "default";
  return <Tag color={color}>{u || "—"}</Tag>;
}

function StackOutcomeAlert({
  kind,
  outcome,
}: {
  kind: "START" | "STOP";
  outcome: StackStartOutcome;
}) {
  return (
    <Alert
      type={outcome.ok ? "success" : "error"}
      showIcon
      title={
        outcome.ok
          ? `스택 ${kind} PASS`
          : `스택 ${kind} FAIL @ ${outcome.failedStep}`
      }
      description={
        <Space orientation="vertical" size={8} style={{ width: "100%" }}>
          {!outcome.ok ? (
            <Typography.Text type="danger">
              {outcome.failedReason}
            </Typography.Text>
          ) : null}
          {outcome.snapshot ? (
            <Typography.Text style={{ fontSize: 12 }}>
              AUTO {outcome.snapshot.autoTradingState} · LIVE{" "}
              {outcome.snapshot.live} · ARM {outcome.snapshot.arm} · STACK{" "}
              {outcome.snapshot.stackLabel}
            </Typography.Text>
          ) : null}
          <Space orientation="vertical" size={4} style={{ width: "100%" }}>
            {outcome.steps.map((item) => (
              <Space key={item.id} size={8} wrap>
                <Tag color={stepTagColor(item.status)}>{item.status}</Tag>
                <Typography.Text>{item.id}</Typography.Text>
                {item.reason ? (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {item.reason}
                  </Typography.Text>
                ) : null}
              </Space>
            ))}
          </Space>
        </Space>
      }
    />
  );
}

export function Upbit24x7OperatorControls({
  ubaId,
  strategyId,
  showUnattendedActions = false,
  onUnattendedEnable,
}: {
  ubaId: number;
  strategyId: number | null;
  /** Drawer canonical 패널에서 24H 시작/중지 노출 */
  showUnattendedActions?: boolean;
  /** 24H Enable Modal은 부모가 소유 (강한 승인 UX) */
  onUnattendedEnable?: () => void;
}) {
  const { message: messageApi, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [stackOutcome, setStackOutcome] = useState<StackStartOutcome | null>(
    null,
  );
  const [stackKind, setStackKind] = useState<"START" | "STOP">("START");
  const [stackPending, setStackPending] = useState(false);

  const opsQuery = useQuery({
    queryKey: ["admin", "uba-ops-status", ubaId, strategyId],
    queryFn: () =>
      adminApi.getAdminUbaOpsStatus(
        ubaId,
        strategyId != null && strategyId > 0 ? strategyId : undefined,
      ),
    refetchInterval: 15_000,
  });

  const snap: StackStartSnapshot | null = opsQuery.data
    ? snapshotFromOpsStatus(opsQuery.data)
    : null;

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["admin", "autotrading-readiness", ubaId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["admin", "uba-ops-status", ubaId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["admin", "uba-unattended", ubaId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["admin", "uba-ops"],
      }),
    ]);
  };

  const runtimeReady = strategyId != null && strategyId > 0;

  // 재승인은 LIVE/ARM OFF 상태에서도 가능 (restore-grade safety만)
  const unattendedStartBlocked = Boolean(
    snap?.blockers.some((b) =>
      ["KILL_SWITCH_ACTIVE"].includes(b),
    ),
  );
  const unattendedStartReason = unattendedStartBlocked
    ? "KILL_SWITCH_ACTIVE — 해소 후 시작 가능"
    : snap?.needsReauthorize
      ? "만료/PROTECTIVE lease — 재승인 시 LIVE/ARM/스택을 canonical 복구합니다"
      : null;

  const unattendedDisable = useMutation({
    mutationFn: () =>
      adminApi.disableAdminUbaUnattended(ubaId, {
        confirmation_text: "DISABLE 24H UNATTENDED",
        reason: "admin_ui_disable",
      }),
    onSuccess: async () => {
      messageApi.success("자동운영(Unattended) 중지 — Operator Authorization 유지");
      await invalidate();
    },
    onError: (err) => messageApi.error(toApiError(err).message),
  });

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
    setStackKind("START");
    setStackOutcome(null);
    try {
      const outcome = await runUpbit24x7StackStart({
        fetchOpsStatus: () =>
          adminApi.getAdminUbaOpsStatus(ubaId, Number(strategyId)),
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
        messageApi.success("운영 스택 START 완료");
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

  const runStackStop = async () => {
    if (!runtimeReady) {
      messageApi.error("strategy_id가 없어 Runtime STOP를 진행할 수 없습니다.");
      return;
    }
    setStackPending(true);
    setStackKind("STOP");
    setStackOutcome(null);
    try {
      const outcome = await runUpbit24x7StackStop({
        fetchOpsStatus: () =>
          adminApi.getAdminUbaOpsStatus(ubaId, Number(strategyId)),
        stopWorker: (phrase) => adminApi.stopAdminLiveOutboxWorker(phrase),
        stopExitMonitor: (phrase) => adminApi.stopAdminExitMonitor(phrase),
        stopRuntime: (phrase) =>
          adminApi.stopAdminUbaStrategyRuntime(
            ubaId,
            Number(strategyId),
            phrase,
          ),
      });
      setStackOutcome(outcome);
      await invalidate();
      if (outcome.ok) {
        messageApi.success("운영 스택 STOP 완료 (LIVE/ARM/24H 유지)");
      } else {
        messageApi.error(
          `스택 STOP 실패 @ ${outcome.failedStep}: ${outcome.failedReason ?? ""}`,
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
      <Typography.Title level={5} style={{ margin: 0 }}>
        자동매매 운영
      </Typography.Title>

      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="AUTO TRADING">
          {snap ? autoTradingTag(snap.autoTradingState) : "—"}
        </Descriptions.Item>
        <Descriptions.Item label="24H">
          {snap ? (
            <Space size={4}>
              {onOffTag(snap.unattendedEnabled)}
              {snap.unattendedEnabled ? (
                <Typography.Text type="secondary">
                  · {snap.unattendedRemainingLabel}
                </Typography.Text>
              ) : (
                <Typography.Text type="secondary">
                  · {snap.unattendedStatusCode}
                  {snap.needsReauthorize ? " · 재승인 필요" : ""}
                </Typography.Text>
              )}
            </Space>
          ) : (
            "—"
          )}
        </Descriptions.Item>
        <Descriptions.Item label="LIVE">
          {snap ? onOffTag(snap.live === "ON") : "—"}
        </Descriptions.Item>
        <Descriptions.Item label="ARM">
          {snap ? (
            <Space size={4}>
              {onOffTag(snap.arm === "ON")}
              {snap.arm === "ON" ? (
                <Typography.Text type="secondary">
                  · {snap.armRemainingLabel}
                </Typography.Text>
              ) : null}
            </Space>
          ) : (
            "—"
          )}
        </Descriptions.Item>
        <Descriptions.Item label="Activation">
          {snap ? (
            <Space size={4}>
              <Tag color={snap.activation === "ACTIVE" ? "green" : "default"}>
                {snap.activation}
              </Tag>
              {snap.activation === "ACTIVE" ? (
                <Typography.Text type="secondary">
                  · {snap.activationRemainingLabel}
                </Typography.Text>
              ) : null}
            </Space>
          ) : (
            "—"
          )}
        </Descriptions.Item>
        <Descriptions.Item label="STACK">
          {snap ? (
            <Tag
              color={
                snap.stackLabel.startsWith("4/")
                  ? "green"
                  : snap.stackLabel.startsWith("0/")
                    ? "default"
                    : "processing"
              }
            >
              {snap.stackLabel}
            </Tag>
          ) : (
            "—"
          )}
        </Descriptions.Item>
        <Descriptions.Item label="AI">
          {snap ? <Tag>{snap.aiState}</Tag> : "—"}
        </Descriptions.Item>
        <Descriptions.Item label="Blocker">
          {snap?.primaryBlocker ? (
            <Tag color="red">{snap.primaryBlocker}</Tag>
          ) : (
            <Tag>NONE</Tag>
          )}
        </Descriptions.Item>
      </Descriptions>

      <UpbitFullMarketControls
        ubaId={ubaId}
        strategyId={strategyId ?? undefined}
        templateSymbol="KRW-XRP"
        opsPayload={opsQuery.data}
      />

      <UpbitPortfolioControls
        ubaId={ubaId}
        strategyId={strategyId ?? undefined}
        templateSymbol="KRW-XRP"
      />

      <Space wrap>
        <Button
          type="primary"
          loading={stackPending && stackKind === "START"}
          disabled={!runtimeReady || stackPending}
          onClick={() =>
            confirmThen(
              "운영 스택 시작",
              "Activation/LIVE/ARM 게이트 확인 후 Worker → Exit Monitor → Runtime 순으로 기동합니다. 실패 시 FAIL CLOSED. LIVE/ARM/24H는 변경하지 않습니다.",
              "시작",
              false,
              () => {
                void runStackStart();
              },
            )
          }
        >
          운영 스택 시작
        </Button>
        <Button
          danger
          loading={stackPending && stackKind === "STOP"}
          disabled={!runtimeReady || stackPending}
          onClick={() =>
            confirmThen(
              "운영 스택 중지",
              "Runtime → Exit Monitor → Worker 순으로 중지합니다. LIVE/ARM/24H Unattended는 끄지 않습니다.",
              "중지",
              true,
              () => {
                void runStackStop();
              },
            )
          }
        >
          운영 스택 중지
        </Button>
        {showUnattendedActions ? (
          snap?.unattendedEnabled && !snap.needsReauthorize ? (
            <Button
              danger
              loading={unattendedDisable.isPending}
              onClick={() =>
                confirmThen(
                  "자동운영 중지",
                  "Unattended 실행만 중지합니다. Operator Authorization(승인 Horizon)은 유지됩니다. 승인 철회는 별도 작업입니다.",
                  "중지",
                  true,
                  () => unattendedDisable.mutate(),
                )
              }
            >
              자동운영 중지
            </Button>
          ) : (
            <Tooltip title={unattendedStartReason ?? undefined}>
              <Button
                type="primary"
                disabled={unattendedStartBlocked || !onUnattendedEnable}
                onClick={() => onUnattendedEnable?.()}
              >
                {snap?.needsReauthorize
                  ? "24H 운영 승인 재발급"
                  : "24시간 자동운영 시작"}
              </Button>
            </Tooltip>
          )
        ) : null}
      </Space>

      {stackOutcome ? (
        <StackOutcomeAlert kind={stackKind} outcome={stackOutcome} />
      ) : null}

      <Collapse
        size="small"
        defaultActiveKey={[]}
        items={[
          {
            key: "advanced",
            label: "▶ 고급 제어",
            children: (
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  Modal 확인만으로 canonical confirmation phrase를 전송합니다.
                  Backend safety gate는 완화되지 않습니다.
                </Typography.Text>
                <Space wrap>
                  <Button
                    size="small"
                    type="primary"
                    disabled={!runtimeReady}
                    loading={runtimeStart.isPending}
                    onClick={() =>
                      confirmThen(
                        "Runtime START",
                        `UBA ${ubaId} / strategy ${strategyId}`,
                        "START",
                        false,
                        () => runtimeStart.mutate(),
                      )
                    }
                  >
                    Runtime START
                  </Button>
                  <Button
                    size="small"
                    danger
                    disabled={!runtimeReady}
                    loading={runtimeStop.isPending}
                    onClick={() =>
                      confirmThen(
                        "Runtime STOP",
                        `UBA ${ubaId} Runtime 중지`,
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
                    size="small"
                    type="primary"
                    loading={workerStart.isPending}
                    onClick={() =>
                      confirmThen(
                        "Worker START",
                        "Live Outbox Worker 시작 (프로세스 전역)",
                        "START",
                        false,
                        () => workerStart.mutate(),
                      )
                    }
                  >
                    Worker START
                  </Button>
                  <Button
                    size="small"
                    danger
                    loading={workerStop.isPending}
                    onClick={() =>
                      confirmThen(
                        "Worker STOP",
                        "Live Outbox Worker 중지",
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
                    size="small"
                    type="primary"
                    loading={exitStart.isPending}
                    onClick={() =>
                      confirmThen(
                        "Exit Monitor START",
                        "Exit Monitor 시작",
                        "START",
                        false,
                        () => exitStart.mutate(),
                      )
                    }
                  >
                    Exit Monitor START
                  </Button>
                  <Button
                    size="small"
                    danger
                    loading={exitStop.isPending}
                    onClick={() =>
                      confirmThen(
                        "Exit Monitor STOP",
                        "Exit Monitor 중지",
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
            ),
          },
        ]}
      />
    </Space>
  );
}
