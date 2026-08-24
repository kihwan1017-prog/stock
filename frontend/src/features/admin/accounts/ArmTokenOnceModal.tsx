"use client";

/**
 * ARM ON 직후 원문 토큰 1회 표시 Modal.
 * 닫으면 부모 state에서 토큰을 즉시 제거한다. 재조회·영속 저장 없음.
 */

import { CopyOutlined, EyeInvisibleOutlined, EyeOutlined } from "@ant-design/icons";
import { Alert, App, Button, Modal, Space, Typography } from "antd";
import { useEffect, useState } from "react";

import {
  type ArmTokenOnceReveal,
  armReissueGuidance,
  formatArmCountdown,
  maskArmToken,
} from "./armTokenOnceReveal";

type Props = {
  reveal: ArmTokenOnceReveal | null;
  schedulerPaused: boolean;
  /** 닫기 — 부모가 reveal을 null로 클리어해야 함 */
  onClose: () => void;
};

type BodyProps = {
  reveal: ArmTokenOnceReveal;
  schedulerPaused: boolean;
};

/** reveal.expiresAt 키로 remount — 토큰 보기 상태 자동 초기화 */
function ArmTokenOnceModalBody({
  reveal,
  schedulerPaused,
}: BodyProps) {
  const { message: messageApi } = App.useApp();
  const [tokenVisible, setTokenVisible] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, []);

  const countdown = formatArmCountdown(reveal.expiresAt, nowMs);

  const handleCopy = async () => {
    if (!reveal.armToken) return;
    try {
      await navigator.clipboard.writeText(reveal.armToken);
      // 토큰 원문은 메시지에 넣지 않음
      queueMicrotask(() => {
        messageApi.success("ARM Token 복사됨 — 사용자에게만 전달하고 저장하지 마세요");
      });
    } catch {
      queueMicrotask(() => {
        messageApi.error("클립보드 복사에 실패했습니다");
      });
    }
  };

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Alert
        type="error"
        showIcon
        title="닫으면 다시 확인할 수 없습니다"
        description="원문은 이 화면에 1회만 표시됩니다. DB·재조회 API·Audit에는 저장되지 않습니다. 지금 복사해 사용자에게 전달하세요."
      />
      <Alert
        type="warning"
        showIcon
        title="재발급"
        description={armReissueGuidance(schedulerPaused)}
      />
      <div>
        <Typography.Text type="secondary">만료 시각</Typography.Text>
        <div>
          <Typography.Text code>{reveal.expiresAt}</Typography.Text>
        </div>
        <Typography.Text
          type={countdown.expired ? "danger" : "success"}
          strong
        >
          카운트다운: {countdown.label}
        </Typography.Text>
      </div>
      <div>
        <Typography.Text type="secondary">ARM Token</Typography.Text>
        <Typography.Paragraph
          style={{
            marginBottom: 8,
            wordBreak: "break-all",
            fontFamily: "monospace",
            fontSize: 13,
          }}
        >
          {maskArmToken(reveal.armToken, tokenVisible)}
        </Typography.Paragraph>
        <Space wrap>
          <Button
            icon={tokenVisible ? <EyeInvisibleOutlined /> : <EyeOutlined />}
            onClick={() => setTokenVisible((v) => !v)}
          >
            {tokenVisible ? "가리기" : "보기"}
          </Button>
          <Button type="primary" icon={<CopyOutlined />} onClick={() => void handleCopy()}>
            복사
          </Button>
        </Space>
      </div>
    </Space>
  );
}

export function ArmTokenOnceModal({
  reveal,
  schedulerPaused,
  onClose,
}: Props) {
  const open = reveal != null;

  const handleClose = () => {
    onClose();
  };

  return (
    <Modal
      title={`ARM Token 1회 표시 (UBA ${reveal?.ubaId ?? ""})`}
      open={open}
      onCancel={handleClose}
      onOk={handleClose}
      okText="확인 · 닫기"
      cancelText="닫기"
      destroyOnHidden
      mask={{ closable: false }}
      keyboard={false}
      width={560}
    >
      {reveal ? (
        <ArmTokenOnceModalBody
          key={reveal.expiresAt}
          reveal={reveal}
          schedulerPaused={schedulerPaused}
        />
      ) : null}
    </Modal>
  );
}
