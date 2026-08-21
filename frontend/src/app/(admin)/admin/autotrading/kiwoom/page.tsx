"use client";

import { Alert, Space, Typography } from "antd";
import Link from "next/link";

import { adminRoutes } from "@/config/routes";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";

/**
 * KIWOOM 자동매매 Workspace shell.
 * LIVE WRITE는 계좌 화면 단일 ownership 유지 — 여기서는 현황·런타임 링크.
 */
export default function AdminAutotradingKiwoomPage() {
  return (
    <AdminPageShell
      title="키움 자동매매"
      description="KRX 장전·장중·장마감 상태를 확인하고 Runtime/계좌에서 운영합니다. LIVE/ARM WRITE는 계좌 현황에서만."
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          title="Single-operator Workspace"
          description={
            <>
              장중 자동매매 제어·Credential·Activation은{" "}
              <Link href={`${adminRoutes.accounts}?broker=KIWOOM`}>
                계좌 현황 (KIWOOM)
              </Link>
              에서 수행합니다. Runtime 상세는{" "}
              <Link href={adminRoutes.trading}>Runtime</Link>, Preflight는{" "}
              <Link href={adminRoutes.operationsPreflight}>안전 탭/Preflight</Link>
              를 사용합니다.
            </>
          }
        />
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          UPBIT와 동일한 one-click START/STOP 오케스트레이션은 KRX 장시간·스케줄러
          Gate가 정리된 뒤 확장합니다. 이번 STEP에서는 기존 안전 Gate를 우회하지
          않습니다.
        </Typography.Paragraph>
      </Space>
    </AdminPageShell>
  );
}
