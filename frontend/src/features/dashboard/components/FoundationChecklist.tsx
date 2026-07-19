"use client";

import { CheckCircleOutlined, CloseCircleOutlined } from "@ant-design/icons";
import { Card, Flex, Typography } from "antd";

interface ChecklistItem {
  key: string;
  label: string;
  done: boolean;
}

interface FoundationChecklistProps {
  apiConnected: boolean;
}

export function FoundationChecklist({ apiConnected }: FoundationChecklistProps) {
  const items: ChecklistItem[] = [
    { key: "next", label: "Next.js 실행", done: true },
    { key: "antd", label: "Ant Design 적용", done: true },
    { key: "theme", label: "Theme 전환", done: true },
    { key: "sidebar", label: "Sidebar 동작", done: true },
    { key: "api", label: "FastAPI 연결", done: apiConnected },
    { key: "rq", label: "React Query 동작", done: true },
    {
      key: "auth",
      label: "JWT 백엔드 인증",
      done: true,
    },
  ];

  return (
    <Card title="Foundation Checklist">
      <Flex vertical gap={12}>
        {items.map((item) => (
          <Typography.Text key={item.key}>
            {item.done ? (
              <CheckCircleOutlined style={{ color: "#52c41a", marginRight: 8 }} />
            ) : (
              <CloseCircleOutlined style={{ color: "#ff4d4f", marginRight: 8 }} />
            )}
            {item.label}
          </Typography.Text>
        ))}
      </Flex>
    </Card>
  );
}
