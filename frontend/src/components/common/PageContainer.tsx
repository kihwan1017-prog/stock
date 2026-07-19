"use client";

import type { ReactNode } from "react";
import { Flex, Typography } from "antd";

interface PageContainerProps {
  title: string;
  description?: string;
  extra?: ReactNode;
  children: ReactNode;
}

export function PageContainer({ title, description, extra, children }: PageContainerProps) {
  return (
    <div style={{ padding: 24 }}>
      <Flex justify="space-between" align="flex-start" style={{ marginBottom: 24 }} gap={16} wrap>
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            {title}
          </Typography.Title>
          {description ? (
            <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
              {description}
            </Typography.Paragraph>
          ) : null}
        </div>
        {extra}
      </Flex>
      {children}
    </div>
  );
}
