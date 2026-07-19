"use client";

import { Card, Tabs } from "antd";

import {
  SettingsEditor,
  SettingsHistoryPanel,
} from "@/features/admin/components/SettingsEditor";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";

export default function AdminSystemSettingsPage() {
  return (
    <AdminPageShell
      title="시스템 설정"
      description="DB 기반 Settings — /api/v1/settings"
    >
      <Tabs
        items={[
          {
            key: "system",
            label: "시스템",
            children: (
              <Card size="small">
                <SettingsEditor category="system" />
              </Card>
            ),
          },
          {
            key: "ai",
            label: "AI",
            children: (
              <Card size="small">
                <SettingsEditor category="ai" />
              </Card>
            ),
          },
          {
            key: "risk",
            label: "Risk",
            children: (
              <Card size="small">
                <SettingsEditor category="risk" />
              </Card>
            ),
          },
          {
            key: "scheduler",
            label: "Scheduler",
            children: (
              <Card size="small">
                <SettingsEditor category="scheduler" />
              </Card>
            ),
          },
          {
            key: "trading",
            label: "거래",
            children: (
              <Card size="small">
                <SettingsEditor category="trading" />
              </Card>
            ),
          },
          {
            key: "environment",
            label: "환경",
            children: (
              <Card size="small">
                <SettingsEditor category="environment" />
              </Card>
            ),
          },
          {
            key: "history",
            label: "변경 이력",
            children: (
              <Card size="small" title="설정 변경 이력">
                <SettingsHistoryPanel />
              </Card>
            ),
          },
        ]}
      />
    </AdminPageShell>
  );
}
