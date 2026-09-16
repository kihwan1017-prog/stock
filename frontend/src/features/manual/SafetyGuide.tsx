"use client";

import { Alert, Card, Col, List, Row, Space, Steps, Typography } from "antd";

import {
  SAFETY_IMMEDIATE_STOP_CONDITIONS,
  SAFETY_SHUTDOWN_STEPS,
} from "./manualDataSafety";
import { ManualStatusBadge } from "./ManualStatusBadge";

export function SafetyGuide() {
  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="error"
        showIcon
        title="즉시 중단 조건"
        description="아래 징후가 보이면 신규 주문을 막고 안전 종료 절차를 시작합니다."
      />

      <Row gutter={[16, 16]}>
        <Col xs={24} md={10}>
          <Card size="small" title="즉시 중단 조건">
            <List
              size="small"
              dataSource={SAFETY_IMMEDIATE_STOP_CONDITIONS}
              renderItem={(item) => (
                <List.Item>
                  <Typography.Text type="danger">• {item}</Typography.Text>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} md={14}>
          <Card size="small" title="안전 종료 순서">
            <Steps
              direction="vertical"
              size="small"
              items={SAFETY_SHUTDOWN_STEPS.map((step) => ({
                title: (
                  <Space>
                    {step.title}
                    <ManualStatusBadge status={step.status} />
                  </Space>
                ),
                description: step.detail,
              }))}
            />
          </Card>
        </Col>
      </Row>
    </Space>
  );
}
