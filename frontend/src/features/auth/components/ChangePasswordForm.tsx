"use client";

import { App, Button, Card, Form, Input, Space } from "antd";
import { useState } from "react";

import { changePassword } from "@/features/auth/api/authApi";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { toApiError } from "@/lib/api/apiError";

/** 로그인 사용자 비밀번호 변경 */
export function ChangePasswordForm() {
  const { message } = App.useApp();
  const { logout } = useAuth();
  const [loading, setLoading] = useState(false);

  return (
    <Card title="비밀번호 변경" size="small">
      <Form
        layout="vertical"
        onFinish={async (values: {
          currentPassword: string;
          newPassword: string;
          confirmPassword: string;
        }) => {
          if (values.newPassword !== values.confirmPassword) {
            message.error("새 비밀번호 확인이 일치하지 않습니다.");
            return;
          }
          setLoading(true);
          try {
            await changePassword({
              currentPassword: values.currentPassword,
              newPassword: values.newPassword,
            });
            message.success("비밀번호가 변경되었습니다. 다시 로그인해 주세요.");
            await logout();
          } catch (error) {
            message.error(toApiError(error).message);
          } finally {
            setLoading(false);
          }
        }}
      >
        <Form.Item
          name="currentPassword"
          label="현재 비밀번호"
          rules={[{ required: true }]}
        >
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Form.Item
          name="newPassword"
          label="새 비밀번호"
          rules={[
            { required: true },
            { min: 8, message: "최소 8자" },
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirmPassword"
          label="새 비밀번호 확인"
          rules={[{ required: true }]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Space>
          <Button type="primary" htmlType="submit" loading={loading}>
            변경
          </Button>
        </Space>
      </Form>
    </Card>
  );
}
