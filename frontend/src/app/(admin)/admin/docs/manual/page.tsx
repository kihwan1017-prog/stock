"use client";

import { Spin } from "antd";
import { Suspense } from "react";

import ManualPageClient from "./ManualPageClient";

export default function Page() {
  return (
    <Suspense fallback={<Spin description="매뉴얼 로딩..." />}>
      <ManualPageClient />
    </Suspense>
  );
}
