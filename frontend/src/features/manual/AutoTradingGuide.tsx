"use client";

import { Card, Col, Row, Space, Steps, Typography } from "antd";

import {
  AUTO_TRADING_COMMON_STEPS,
  AUTO_TRADING_MARKET_FLOWS,
} from "./manualDataTrading";
import { ManualStatusBadge } from "./ManualStatusBadge";

export function AutoTradingGuide() {
  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card size="small" title="공통 흐름">
        <Steps
          direction="vertical"
          size="small"
          items={AUTO_TRADING_COMMON_STEPS.map((step) => ({
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

      <Typography.Title level={5} style={{ margin: 0 }}>
        시장별 절차
      </Typography.Title>
      <Row gutter={[16, 16]}>
        {AUTO_TRADING_MARKET_FLOWS.map((flow) => (
          <Col xs={24} lg={12} key={flow.id}>
            <Card
              size="small"
              title={
                <Space>
                  {flow.title}
                  <ManualStatusBadge status={flow.status} />
                </Space>
              }
            >
              <ol style={{ margin: 0, paddingLeft: 20 }}>
                {flow.steps.map((step) => (
                  <li key={step}>
                    <Typography.Text>{step}</Typography.Text>
                  </li>
                ))}
              </ol>
              {flow.warnings.length ? (
                <Typography.Paragraph type="warning" style={{ marginTop: 12, marginBottom: 0 }}>
                  {flow.warnings.join(" · ")}
                </Typography.Paragraph>
              ) : null}
            </Card>
          </Col>
        ))}
      </Row>

      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        모든 LIVE Flag는 기본 OFF입니다. 이 매뉴얼은 LIVE Flag를 직접 켜도록 안내하지
        않습니다. 관리자 승인·Unlock·Risk Gate가 필요합니다.
      </Typography.Paragraph>
    </Space>
  );
}
