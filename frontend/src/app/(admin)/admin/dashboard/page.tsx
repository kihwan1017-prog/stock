"use client";

import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { OperationsCenterDashboard } from "@/features/admin/operations-center/OperationsCenterDashboard";

export default function AdminDashboardPage() {
  return (
    <AdminPageShell
      title="운영 대시보드"
      description="단일 운영자 Cockpit — KPI · Broker 상태 · AUTO 손익 (Read-only)"
    >
      <OperationsCenterDashboard refreshMs={5000} />
    </AdminPageShell>
  );
}
