"use client";

import { Button, Result } from "antd";

interface GlobalErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function GlobalError({ error, reset }: GlobalErrorProps) {
  return (
    <html lang="ko">
      <body>
        <Result
          status="500"
          title="치명적 오류"
          subTitle={
            process.env.NODE_ENV === "development"
              ? error.message
              : "애플리케이션을 다시 로드해 주세요."
          }
          extra={
            <Button type="primary" onClick={reset}>
              다시 시도
            </Button>
          }
        />
      </body>
    </html>
  );
}
