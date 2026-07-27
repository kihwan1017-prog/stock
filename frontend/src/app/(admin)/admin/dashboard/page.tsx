"use client";

import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { OperationsCenterDashboard } from "@/features/admin/operations-center/OperationsCenterDashboard";

export default function AdminDashboardPage() {
  return (
    <AdminPageShell
      title="Operations Center"
      description="STEP 10-3 — 운영 통합 Dashboard (Read-only, 5초 갱신)"
    >
      <OperationsCenterDashboard refreshMs={5000} />
    </AdminPageShell>
  );
}
