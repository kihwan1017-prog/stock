"use client";

import Link from "next/link";
import { Space } from "antd";

import { adminRoutes } from "@/config/routes";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { SystemStatusDashboard } from "@/features/admin/system-status/SystemStatusDashboard";

/**
 * 관리자 «시스템 상태» — 한글 Dashboard.
 * Raw JSON은 개발자 상세 Collapse에만 노출.
 */
export default function AdminMonitoringPage() {
  return (
    <AdminPageShell
      title="시스템 상태"
      description="공통·업비트·키움 운영 상태를 한눈에 확인합니다. 이 화면은 조회 전용이며 LIVE/ARM/Runtime을 변경하지 않습니다."
      extra={
        <Space wrap>
          <Link href={adminRoutes.operations}>시스템 운영</Link>
          <Link href={adminRoutes.operationsDashboard}>거래 운영 현황</Link>
        </Space>
      }
    >
      <SystemStatusDashboard />
    </AdminPageShell>
  );
}
