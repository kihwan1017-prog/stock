"use client";

import { Button, Result } from "antd";
import { useEffect } from "react";

import { logger } from "@/utils/logger";

interface ErrorPageProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function ErrorPage({ error, reset }: ErrorPageProps) {
  useEffect(() => {
    logger.error("App route error", { message: error.message, digest: error.digest });
  }, [error]);

  return (
    <Result
      status="error"
      title="문제가 발생했습니다"
      subTitle={
        process.env.NODE_ENV === "development"
          ? error.message
          : "잠시 후 다시 시도해 주세요."
      }
      extra={
        <Button type="primary" onClick={reset}>
          다시 시도
        </Button>
      }
    />
  );
}
