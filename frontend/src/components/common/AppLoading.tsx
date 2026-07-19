"use client";

import { Spin } from "antd";

interface AppLoadingProps {
  /** Ant Design Spin description (구 tip) */
  tip?: string;
  fullScreen?: boolean;
}

export function AppLoading({ tip = "로딩 중...", fullScreen = false }: AppLoadingProps) {
  if (fullScreen) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Spin size="large" description={tip}>
          <div style={{ padding: 48 }} />
        </Spin>
      </div>
    );
  }

  return (
    <div
      style={{
        minHeight: 200,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <Spin description={tip}>
        <div style={{ padding: 32 }} />
      </Spin>
    </div>
  );
}
