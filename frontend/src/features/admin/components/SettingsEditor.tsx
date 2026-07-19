"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Table,
  Typography,
} from "antd";
import { useEffect, useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import type { SettingItem } from "@/features/admin/api/adminApi";
import { PermissionButton } from "@/features/auth/components/PermissionButton";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

interface SettingsEditorProps {
  category: string;
  title?: string;
}

export function SettingsEditor({ category, title }: SettingsEditorProps) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [reason, setReason] = useState("");

  const settingsQuery = useQuery({
    queryKey: queryKeys.admin.settings(category),
    queryFn: () => adminApi.listSettings(category),
  });

  const items = useMemo(
    () => settingsQuery.data ?? [],
    [settingsQuery.data],
  );

  useEffect(() => {
    const initial: Record<string, unknown> = {};
    for (const item of items) {
      if (item.value_type === "bool") {
        initial[item.key] =
          item.typed_value === true ||
          String(item.value).toLowerCase() === "true";
      } else if (item.value_type === "int" || item.value_type === "float") {
        initial[item.key] =
          item.typed_value ??
          (item.value === "" ? undefined : Number(item.value));
      } else {
        initial[item.key] = item.is_secret ? "" : item.value;
      }
    }
    form.setFieldsValue(initial);
  }, [form, items]);

  const saveMut = useMutation({
    mutationFn: (payload: Array<{ key: string; value: unknown }>) =>
      adminApi.updateSettings(payload, reason || undefined),
    onSuccess: (changed) => {
      message.success(
        changed.length
          ? `${changed.length}개 설정이 저장되었습니다.`
          : "변경된 설정이 없습니다.",
      );
      setReason("");
      void queryClient.invalidateQueries({
        queryKey: ["admin", "settings"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["admin", "setting-history"],
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const onSave = async () => {
    const values = await form.validateFields();
    const payload: Array<{ key: string; value: unknown }> = [];
    for (const item of items) {
      const next = values[item.key];
      if (item.is_secret) {
        const text = String(next ?? "").trim();
        if (!text || text === "********") {
          continue;
        }
        payload.push({ key: item.key, value: text });
        continue;
      }
      payload.push({ key: item.key, value: next });
    }
    saveMut.mutate(payload);
  };

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      {title ? (
        <Typography.Title level={5} style={{ margin: 0 }}>
          {title}
        </Typography.Title>
      ) : null}
      <Form form={form} layout="vertical" disabled={settingsQuery.isLoading}>
        {items.map((item) => (
          <SettingField key={item.key} item={item} />
        ))}
      </Form>
      <Input
        placeholder="변경 사유 (선택)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        maxLength={255}
      />
      <PermissionButton
        permission="settings:write"
        type="primary"
        loading={saveMut.isPending}
        onClick={() => void onSave()}
      >
        저장
      </PermissionButton>
    </Space>
  );
}

function SettingField({ item }: { item: SettingItem }) {
  const label = (
    <Space size={8}>
      <span>{item.description || item.key}</span>
      <Typography.Text type="secondary" code>
        {item.key}
      </Typography.Text>
    </Space>
  );

  if (item.value_type === "bool") {
    return (
      <Form.Item name={item.key} label={label} valuePropName="checked">
        <Switch />
      </Form.Item>
    );
  }

  if (item.allowed_values?.length) {
    return (
      <Form.Item name={item.key} label={label} rules={[{ required: true }]}>
        <Select
          options={item.allowed_values.map((value) => ({
            value,
            label: value,
          }))}
        />
      </Form.Item>
    );
  }

  if (item.value_type === "int" || item.value_type === "float") {
    return (
      <Form.Item name={item.key} label={label}>
        <InputNumber
          style={{ width: "100%" }}
          min={item.min_value ?? undefined}
          max={item.max_value ?? undefined}
          step={item.value_type === "float" ? 0.1 : 1}
        />
      </Form.Item>
    );
  }

  return (
    <Form.Item
      name={item.key}
      label={label}
      extra={
        item.is_secret
          ? "민감정보 — 변경 시에만 입력 (비우면 기존 값 유지)"
          : undefined
      }
    >
      {item.is_secret ? <Input.Password /> : <Input />}
    </Form.Item>
  );
}

export function SettingsHistoryPanel({
  settingKey,
}: {
  settingKey?: string;
}) {
  const queryClient = useQueryClient();
  const historyQuery = useQuery({
    queryKey: queryKeys.admin.settingHistory({
      setting_key: settingKey,
      limit: 50,
    }),
    queryFn: () =>
      adminApi.listSettingHistory({
        setting_key: settingKey,
        limit: 50,
      }),
  });

  return (
    <Space orientation="vertical" style={{ width: "100%" }} size={8}>
      <Button
        size="small"
        onClick={() =>
          void queryClient.invalidateQueries({
            queryKey: ["admin", "setting-history"],
          })
        }
      >
        새로고침
      </Button>
      <Table
        size="small"
        loading={historyQuery.isLoading}
        rowKey="history_id"
        dataSource={historyQuery.data ?? []}
        pagination={{ pageSize: 10 }}
        columns={[
          { title: "시각", dataIndex: "created_at", width: 180 },
          { title: "키", dataIndex: "key", width: 180 },
          {
            title: "이전",
            dataIndex: "old_value",
            ellipsis: true,
            render: (v) => v ?? "—",
          },
          {
            title: "이후",
            dataIndex: "new_value",
            ellipsis: true,
            render: (v) => v ?? "—",
          },
          { title: "액터", dataIndex: "actor", width: 120 },
          {
            title: "사유",
            dataIndex: "change_reason",
            render: (v) => v ?? "—",
          },
        ]}
      />
    </Space>
  );
}
