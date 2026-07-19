"use client";

import { Alert, Typography } from "antd";

interface UnimplementedNoticeProps {
  /** 화면에 필요한 기능 이름 */
  feature: string;
  /** 없는 API 또는 이유 */
  reason: string;
  /** 참고용 기존 API (있으면) */
  relatedApis?: string[];
}

/**
 * Backend에 해당 API가 없을 때 표시.
 * 추측 구현 금지 — 이 배너만 보여준다.
 */
export function UnimplementedNotice({
  feature,
  reason,
  relatedApis = [],
}: UnimplementedNoticeProps) {
  return (
    <Alert
      type="warning"
      showIcon
      title={`${feature} — 미구현`}
      description={
        <div>
          <Typography.Paragraph style={{ marginBottom: relatedApis.length ? 8 : 0 }}>
            {reason}
          </Typography.Paragraph>
          {relatedApis.length > 0 ? (
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              관련·참고 API: {relatedApis.join(", ")}
            </Typography.Paragraph>
          ) : null}
        </div>
      }
    />
  );
}
