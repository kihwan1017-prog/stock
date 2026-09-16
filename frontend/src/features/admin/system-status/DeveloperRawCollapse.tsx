"use client";

import { Button, Collapse, Space, Typography } from "antd";
import { useMemo, useState } from "react";

/**
 * 개발자용 Raw JSON — 기본 접힘. 운영 화면에 JSON을 직접 노출하지 않는다.
 */
export function DeveloperRawCollapse({
  title = "개발자 상세 보기",
  endpoint,
  updatedAt,
  data,
}: {
  title?: string;
  endpoint?: string;
  updatedAt?: string | null;
  data: unknown;
}) {
  const [copied, setCopied] = useState(false);
  const text = useMemo(() => {
    try {
      return JSON.stringify(data ?? null, null, 2);
    } catch {
      return String(data);
    }
  }, [data]);

  return (
    <Collapse
      size="small"
      items={[
        {
          key: "dev",
          label: title,
          children: (
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              {endpoint ? (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  API: {endpoint}
                </Typography.Text>
              ) : null}
              {updatedAt ? (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  updated_at: {updatedAt}
                </Typography.Text>
              ) : null}
              <Space>
                <Button
                  size="small"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(text);
                      setCopied(true);
                      window.setTimeout(() => setCopied(false), 2000);
                    } catch {
                      setCopied(false);
                    }
                  }}
                >
                  JSON 복사
                </Button>
                {copied ? (
                  <Typography.Text type="success" style={{ fontSize: 12 }}>
                    복사됨
                  </Typography.Text>
                ) : null}
              </Space>
              <pre
                style={{
                  margin: 0,
                  maxHeight: 360,
                  overflow: "auto",
                  fontSize: 11,
                  padding: 12,
                  borderRadius: 8,
                  background: "var(--app-bg, #fafafa)",
                }}
              >
                {text}
              </pre>
            </Space>
          ),
        },
      ]}
    />
  );
}
