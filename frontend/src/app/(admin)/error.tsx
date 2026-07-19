"use client";

import { Button, Result } from "antd";
import { useEffect } from "react";

export default function AdminError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <Result
      status="error"
      title="Admin 화면 오류"
      subTitle={error.message || "예상치 못한 오류가 발생했습니다."}
      extra={
        <Button type="primary" onClick={reset}>
          다시 시도
        </Button>
      }
    />
  );
}
