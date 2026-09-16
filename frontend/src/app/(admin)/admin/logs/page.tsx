"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Space, Typography } from "antd";
import Link from "next/link";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

/** 감사 로그 조회 전용 — LIVE/ARM/주문 mutate 없음. 앱 로그 tail은 미구현. */
export default function AdminLogsPage() {
  const auditQuery = useQuery({
    queryKey: queryKeys.admin.auditEvents({ limit: 100 }),
    queryFn: () => adminApi.listAuditEvents({ limit: 100 }),
    retry: false,
  });

  const rows = extractRows(auditQuery.data);

  return (
    <AdminPageShell
      title="로그·감사"
      description="감사 이벤트 조회 전용입니다. 앱 로그 파일 테일링과 dump/restore는 제공하지 않습니다."
      extra={
        <Link href={adminRoutes.operations}>시스템 운영</Link>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          title="조회 전용"
          description="이 화면은 GET /audit/events 만 호출합니다. LIVE/ARM/Scheduler/실주문을 변경하지 않습니다."
        />
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          웹 앱 로그 tail(GET /ops/logs/tail)은 운영센터에서 미구현으로 안내합니다.
        </Typography.Paragraph>
        <AdminDataTable
          title="감사 이벤트 (GET /audit/events)"
          loading={auditQuery.isLoading}
          error={auditQuery.error ? toApiError(auditQuery.error) : null}
          rowKey={(row) =>
            cell(row.event_id ?? row.id ?? row.created_at ?? JSON.stringify(row))
          }
          columns={[
            { title: "시각", dataIndex: "created_at", width: 200 },
            { title: "유형", dataIndex: "event_type", width: 180 },
            { title: "행위", dataIndex: "action" },
            { title: "행위자", dataIndex: "actor", width: 140 },
          ]}
          dataSource={rows}
        />
      </Space>
    </AdminPageShell>
  );
}
