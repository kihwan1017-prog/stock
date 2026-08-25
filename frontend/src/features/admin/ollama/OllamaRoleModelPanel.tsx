"use client";

/**
 * Ollama 역할별 모델 관리 — Select(설치 모델만) + SHADOW 표시.
 * REAL gate / 모델 설치·삭제 / LoRA 실행 없음.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Card,
  Col,
  Collapse,
  Form,
  Input,
  List,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import { useEffect, useMemo } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { PermissionButton } from "@/features/auth/components/PermissionButton";
import { asRecord, cell } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type RoleKey = "analysis" | "trading" | "teacher" | "fallback";

const ROLE_ORDER: RoleKey[] = [
  "analysis",
  "trading",
  "teacher",
  "fallback",
];

const ROLE_SETTING_KEY: Record<RoleKey, string> = {
  analysis: "analysis_llm_model",
  trading: "trading_llm_model",
  teacher: "teacher_llm_model",
  fallback: "ollama_model",
};

function formatSizeGb(sizeGb: unknown, sizeBytes: unknown): string {
  if (typeof sizeGb === "number" && Number.isFinite(sizeGb)) {
    return `약 ${sizeGb.toFixed(2)}GB`;
  }
  if (typeof sizeBytes === "number" && Number.isFinite(sizeBytes)) {
    return `약 ${(sizeBytes / 1024 ** 3).toFixed(2)}GB`;
  }
  return "—";
}

function healthLine(health: Record<string, unknown> | null): string {
  if (!health) return "telemetry 없음";
  const calls = health.calls;
  const ok = health.ok;
  const timeouts = health.timeouts;
  const errors = health.errors;
  const median = health.median_latency_ms;
  const parts = [
    `호출 ${cell(calls)}`,
    `성공 ${cell(ok)}`,
    `timeout ${cell(timeouts)}`,
    `error ${cell(errors)}`,
  ];
  if (median != null && median !== "") {
    parts.push(`median ${Number(median).toFixed(0)} ms`);
  }
  return parts.join(" · ");
}

export function OllamaRoleModelPanel() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm();

  const roleQuery = useQuery({
    queryKey: queryKeys.admin.ollamaRoleModels(),
    queryFn: () => adminApi.getOllamaRoleModels(),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  const modelsQuery = useQuery({
    queryKey: queryKeys.admin.ollamaModels(),
    queryFn: adminApi.listOllamaModels,
    retry: false,
    staleTime: 30_000,
  });

  const data = asRecord(roleQuery.data);
  const roles = asRecord(data?.roles);
  const installedNames = useMemo(() => {
    const fromRole = data?.installed_model_names;
    if (Array.isArray(fromRole)) {
      return fromRole.map(String);
    }
    const models = modelsQuery.data?.models ?? [];
    return models
      .map((m) => m.name)
      .filter((n): n is string => Boolean(n));
  }, [data?.installed_model_names, modelsQuery.data?.models]);

  const selectOptions = useMemo(
    () =>
      installedNames.map((name) => ({
        value: name,
        label: name,
      })),
    [installedNames],
  );

  useEffect(() => {
    if (!roles) return;
    const next: Record<string, string> = {};
    for (const key of ROLE_ORDER) {
      const role = asRecord(roles[key]);
      const settingKey = ROLE_SETTING_KEY[key];
      // Teacher DB 빈값이면 runtime resolve(ollama_model)를 Select에 표시
      const dbVal = String(role?.DB_VALUE ?? "");
      const runtime = String(role?.RUNTIME_RESOLVED_VALUE ?? "");
      next[settingKey] =
        key === "teacher" && !dbVal.trim() ? runtime : dbVal || runtime;
    }
    form.setFieldsValue(next);
  }, [roles, form, roleQuery.dataUpdatedAt]);

  const saveMut = useMutation({
    mutationFn: (payload: {
      analysis_llm_model: string;
      trading_llm_model: string;
      teacher_llm_model: string;
      ollama_model: string;
      change_reason?: string;
    }) => adminApi.updateOllamaRoleModels(payload),
    onSuccess: () => {
      message.success("역할별 모델이 저장되었습니다.");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.ollamaRoleModels(),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.ollamaStatus(),
      });
      void queryClient.invalidateQueries({
        queryKey: ["admin", "settings"],
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const onSave = async () => {
    const values = await form.validateFields();
    const analysis = String(values.analysis_llm_model || "").trim();
    const trading = String(values.trading_llm_model || "").trim();
    const teacher = String(values.teacher_llm_model || "").trim();
    const fallback = String(values.ollama_model || "").trim();
    for (const [label, model] of [
      ["분석", analysis],
      ["매매 판단", trading],
      ["Teacher", teacher],
      ["Fallback", fallback],
    ] as const) {
      if (!model) {
        message.error(`${label} 모델을 선택하세요.`);
        return;
      }
      if (!installedNames.includes(model)) {
        message.error(
          `${label} 모델 '${model}'은(는) 설치되지 않아 저장할 수 없습니다.`,
        );
        return;
      }
    }
    saveMut.mutate({
      analysis_llm_model: analysis,
      trading_llm_model: trading,
      teacher_llm_model: teacher,
      ollama_model: fallback,
      change_reason: String(values.change_reason || "").trim() || undefined,
    });
  };

  const installedRows = Array.isArray(data?.installed_models)
    ? (data.installed_models as Record<string, unknown>[])
    : [];

  const jsonCardError: Error | null = modelsQuery.error
    ? toApiError(modelsQuery.error)
    : roleQuery.error
      ? toApiError(roleQuery.error)
      : null;

  if (roleQuery.isError) {
    return (
      <Alert
        type="error"
        showIcon
        title="역할별 모델 조회 실패"
        description={toApiError(roleQuery.error).message}
      />
    );
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="역할별 모델 · SHADOW only"
        description="Trading LLM은 SHADOW입니다. 이 화면에서 REAL 주문 Gate를 켜지 않습니다. 모델 설치/삭제·LoRA 학습도 지원하지 않습니다."
      />

      <Card
        size="small"
        title="역할별 모델"
        loading={roleQuery.isLoading}
      >
        <Form form={form} layout="vertical">
          <Row gutter={[12, 12]}>
            {ROLE_ORDER.map((roleKey) => {
              const role = asRecord(roles?.[roleKey]);
              const settingKey = ROLE_SETTING_KEY[roleKey];
              const runtime = String(role?.RUNTIME_RESOLVED_VALUE ?? "");
              const installed = role?.installed === true;
              const notInstalled =
                Boolean(runtime) && !installedNames.includes(runtime);

              return (
                <Col xs={24} md={12} xl={6} key={roleKey}>
                  <Card
                    size="small"
                    type="inner"
                    title={cell(role?.label) || roleKey}
                    styles={{ body: { minHeight: 220 } }}
                  >
                    <Space
                      orientation="vertical"
                      size={8}
                      style={{ width: "100%" }}
                    >
                      <Typography.Text type="secondary">
                        용도: {cell(role?.purpose)}
                      </Typography.Text>
                      <Typography.Paragraph
                        type="secondary"
                        style={{ marginBottom: 0 }}
                      >
                        {cell(role?.description)}
                      </Typography.Paragraph>

                      {roleKey === "trading" ? (
                        <>
                          <Tag color="warning">SHADOW</Tag>
                          <Typography.Text type="secondary">
                            현재 LLM 판단은 실제 주문 Gate에 직접 연결되지
                            않습니다.
                          </Typography.Text>
                        </>
                      ) : null}

                      <Form.Item
                        name={settingKey}
                        label="모델"
                        rules={[{ required: true, message: "모델을 선택하세요" }]}
                        style={{ marginBottom: 8 }}
                      >
                        <Select
                          options={selectOptions}
                          showSearch
                          optionFilterProp="label"
                          placeholder="설치된 모델 선택"
                        />
                      </Form.Item>

                      <Space wrap size={4}>
                        {installed ? (
                          <Tag color="success">설치됨</Tag>
                        ) : (
                          <Tag color="default">역할 미확인</Tag>
                        )}
                        {notInstalled ? (
                          <Tag color="error">설치되지 않은 모델</Tag>
                        ) : null}
                        {runtime ? (
                          <Tag>runtime: {runtime}</Tag>
                        ) : null}
                      </Space>

                      {roleKey !== "fallback" ? (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {healthLine(asRecord(role?.health))}
                        </Typography.Text>
                      ) : null}

                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        fallback: {cell(role?.FALLBACK_RULE)}
                      </Typography.Text>
                    </Space>
                  </Card>
                </Col>
              );
            })}
          </Row>

          <Form.Item
            name="change_reason"
            label="변경 사유 (선택)"
            style={{ marginTop: 12, marginBottom: 8 }}
          >
            <Input maxLength={255} placeholder="예: 역할 모델 정렬" />
          </Form.Item>

          <PermissionButton
            permission="settings:write"
            type="primary"
            loading={saveMut.isPending}
            onClick={() => void onSave()}
          >
            역할 모델 저장
          </PermissionButton>
        </Form>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card
            size="small"
            title={`설치 모델 ${installedRows.length || installedNames.length}개`}
            loading={roleQuery.isLoading || modelsQuery.isLoading}
          >
            <List
              dataSource={
                installedRows.length
                  ? installedRows
                  : installedNames.map((name) => ({ name }))
              }
              renderItem={(item) => {
                const rec = asRecord(item) ?? {};
                const name = String(rec.name ?? "");
                const roleList = Array.isArray(rec.roles)
                  ? rec.roles.map(String)
                  : [];
                return (
                  <List.Item>
                    <Space
                      orientation="vertical"
                      size={2}
                      style={{ width: "100%" }}
                    >
                      <Typography.Text strong>{name}</Typography.Text>
                      <Typography.Text type="secondary">
                        크기: {formatSizeGb(rec.size_gb, rec.size_bytes)}
                      </Typography.Text>
                      <Space wrap size={4}>
                        <Tag color="success">설치됨</Tag>
                        {roleList.length ? (
                          roleList.map((r) => (
                            <Tag key={`${name}-${r}`}>사용 역할: {r}</Tag>
                          ))
                        ) : (
                          <Tag>사용 역할: 없음</Tag>
                        )}
                      </Space>
                    </Space>
                  </List.Item>
                );
              }}
            />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Collapse
            items={[
              {
                key: "raw",
                label: "개발자 상세 보기",
                children: (
                  <AdminJsonCard
                    title="GET /ollama/models · role-models"
                    loading={modelsQuery.isLoading || roleQuery.isLoading}
                    error={jsonCardError}
                    data={{
                      models: modelsQuery.data,
                      role_models: roleQuery.data,
                    }}
                  />
                ),
              },
            ]}
          />
        </Col>
      </Row>
    </Space>
  );
}
