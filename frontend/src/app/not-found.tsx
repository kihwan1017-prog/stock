"use client";

import { Button, Result } from "antd";
import { useRouter } from "next/navigation";

import { routes } from "@/config/routes";

export default function NotFoundPage() {
  const router = useRouter();

  return (
    <Result
      status="404"
      title="페이지를 찾을 수 없습니다"
      subTitle="요청하신 경로가 존재하지 않습니다."
      extra={
        <Button type="primary" onClick={() => router.push(routes.dashboard)}>
          Dashboard로 이동
        </Button>
      }
    />
  );
}
