"use client";

import { Typography } from "antd";

import { env } from "@/config/env";

export function DashboardWelcome() {
  return (
    <div style={{ marginBottom: 24 }}>
      <Typography.Title level={2} style={{ marginBottom: 4 }}>
        {env.APP_NAME}
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        FastAPI 운영 관리자 — STEP41 Foundation
      </Typography.Paragraph>
    </div>
  );
}
