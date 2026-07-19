"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Drawer,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import type { TablePaginationConfig } from "antd/es/table";
import type { SorterResult } from "antd/es/table/interface";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import type { MemberRecord } from "@/features/admin/api/adminApi";
import { AdminDataTable } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { PermissionButton } from "@/features/auth/components/PermissionButton";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

interface MemberFilters {
  q?: string;
  is_active?: boolean;
  role?: string;
  include_deleted: boolean;
  sort_by: string;
  sort_order: "asc" | "desc";
  limit: number;
  offset: number;
}

export default function AdminMembersPage() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();

  const [filters, setFilters] = useState<MemberFilters>({
    include_deleted: false,
    sort_by: "created_at",
    sort_order: "desc",
    limit: 20,
    offset: 0,
  });
  const [detailId, setDetailId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<MemberRecord | null>(null);
  const [resetTarget, setResetTarget] = useState<MemberRecord | null>(null);
  const [tempPassword, setTempPassword] = useState<string | null>(null);

  const listQuery = useQuery({
    queryKey: queryKeys.admin.members(filters),
    queryFn: () => adminApi.listMembers(filters),
  });

  const detailQuery = useQuery({
    queryKey: queryKeys.admin.memberDetail(detailId ?? ""),
    queryFn: () => adminApi.getMember(detailId!, filters.include_deleted),
    enabled: detailId !== null,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "members"] });
  };

  const createMut = useMutation({
    mutationFn: adminApi.createMember,
    onSuccess: () => {
      message.success("회원이 등록되었습니다.");
      setCreateOpen(false);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const updateMut = useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string;
      body: Parameters<typeof adminApi.updateMember>[1];
    }) => adminApi.updateMember(id, body),
    onSuccess: () => {
      message.success("회원 정보가 수정되었습니다.");
      setEditTarget(null);
      invalidate();
      if (detailId) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.admin.memberDetail(detailId),
        });
      }
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const deleteMut = useMutation({
    mutationFn: adminApi.softDeleteMember,
    onSuccess: () => {
      message.success("회원이 Soft Delete 처리되었습니다.");
      setDetailId(null);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const activateMut = useMutation({
    mutationFn: adminApi.activateMember,
    onSuccess: () => {
      message.success("회원이 활성화되었습니다.");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const deactivateMut = useMutation({
    mutationFn: adminApi.deactivateMember,
    onSuccess: () => {
      message.success("회원이 비활성화되었습니다.");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const resetMut = useMutation({
    mutationFn: ({
      id,
      password,
    }: {
      id: string;
      password?: string;
    }) => adminApi.resetMemberPassword(id, password),
    onSuccess: (data) => {
      setTempPassword(data.temporary_password);
      setResetTarget(null);
      message.success("비밀번호가 초기화되었습니다.");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const rows = useMemo(() => listQuery.data?.items ?? [], [listQuery.data]);

  const onTableChange = (
    pagination: TablePaginationConfig,
    _filters: unknown,
    sorter: SorterResult<MemberRecord> | SorterResult<MemberRecord>[],
  ) => {
    const single = Array.isArray(sorter) ? sorter[0] : sorter;
    const pageSize = pagination.pageSize ?? filters.limit;
    const current = pagination.current ?? 1;
    setFilters((prev) => ({
      ...prev,
      limit: pageSize,
      offset: (current - 1) * pageSize,
      sort_by:
        typeof single?.field === "string" ? single.field : prev.sort_by,
      sort_order:
        single?.order === "ascend"
          ? "asc"
          : single?.order === "descend"
            ? "desc"
            : prev.sort_order,
    }));
  };

  return (
    <AdminPageShell
      title="회원관리"
      description="GET/POST/PUT/DELETE /api/v1/users — Soft Delete · 검색·필터·정렬·페이징"
      extra={
        <PermissionButton
          permission="users:write"
          type="primary"
          onClick={() => setCreateOpen(true)}
        >
          회원 등록
        </PermissionButton>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Form
          layout="inline"
          onFinish={(values: {
            q?: string;
            role?: string;
            is_active?: string;
            include_deleted?: boolean;
          }) => {
            setFilters((prev) => ({
              ...prev,
              q: values.q || undefined,
              role: values.role || undefined,
              is_active:
                values.is_active === "true"
                  ? true
                  : values.is_active === "false"
                    ? false
                    : undefined,
              include_deleted: Boolean(values.include_deleted),
              offset: 0,
            }));
          }}
        >
          <Form.Item name="q" label="검색">
            <Input allowClear placeholder="username / display_name" style={{ width: 200 }} />
          </Form.Item>
          <Form.Item name="role" label="역할">
            <Select
              allowClear
              placeholder="role"
              style={{ width: 120 }}
              options={[
                { value: "admin", label: "admin (관리자)" },
                { value: "operator", label: "operator (운영자)" },
                { value: "viewer", label: "viewer (조회자)" },
              ]}
            />
          </Form.Item>
          <Form.Item name="is_active" label="상태">
            <Select
              allowClear
              placeholder="전체"
              style={{ width: 120 }}
              options={[
                { value: "true", label: "활성" },
                { value: "false", label: "비활성" },
              ]}
            />
          </Form.Item>
          <Form.Item name="include_deleted" label="삭제 포함" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Button type="primary" htmlType="submit">
            검색
          </Button>
        </Form>

        <AdminDataTable<MemberRecord>
          title="회원 목록"
          loading={listQuery.isLoading}
          error={listQuery.error ? toApiError(listQuery.error) : null}
          rowKey={(row) => row.id}
          dataSource={rows}
          onChange={onTableChange}
          pagination={{
            current: Math.floor(filters.offset / filters.limit) + 1,
            pageSize: filters.limit,
            total: listQuery.data?.total ?? 0,
            showSizeChanger: true,
          }}
          columns={[
            {
              title: "ID",
              dataIndex: "id",
              sorter: true,
              width: 80,
            },
            {
              title: "username",
              dataIndex: "username",
              sorter: true,
            },
            {
              title: "display_name",
              dataIndex: "display_name",
              sorter: true,
            },
            {
              title: "roles",
              dataIndex: "roles",
              render: (roles: string[]) =>
                roles?.map((role) => <Tag key={role}>{role}</Tag>),
            },
            {
              title: "활성",
              dataIndex: "is_active",
              sorter: true,
              render: (value: boolean) =>
                value ? <Tag color="success">Y</Tag> : <Tag>N</Tag>,
            },
            {
              title: "삭제",
              dataIndex: "deleted_at",
              render: (value?: string | null) =>
                value ? <Tag color="error">deleted</Tag> : "-",
            },
            {
              title: "created_at",
              dataIndex: "created_at",
              sorter: true,
            },
            {
              title: "작업",
              key: "actions",
              render: (_, row) => (
                <Space wrap size={4}>
                  <Button size="small" onClick={() => setDetailId(row.id)}>
                    상세
                  </Button>
                  <Button
                    size="small"
                    disabled={Boolean(row.deleted_at)}
                    onClick={() => setEditTarget(row)}
                  >
                    수정
                  </Button>
                  {row.is_active ? (
                    <Button
                      size="small"
                      disabled={Boolean(row.deleted_at)}
                      onClick={() => deactivateMut.mutate(row.id)}
                    >
                      비활성
                    </Button>
                  ) : (
                    <Button
                      size="small"
                      disabled={Boolean(row.deleted_at)}
                      onClick={() => activateMut.mutate(row.id)}
                    >
                      활성
                    </Button>
                  )}
                  <Button
                    size="small"
                    disabled={Boolean(row.deleted_at)}
                    onClick={() => setResetTarget(row)}
                  >
                    PW초기화
                  </Button>
                  <PermissionButton
                    permission="users:delete"
                    size="small"
                    danger
                    disabled={Boolean(row.deleted_at)}
                    onClick={() => {
                      modal.confirm({
                        title: "Soft Delete 확인",
                        content: `${row.username} 회원을 삭제(soft)할까요?`,
                        onOk: () => deleteMut.mutateAsync(row.id),
                      });
                    }}
                  >
                    삭제
                  </PermissionButton>
                </Space>
              ),
            },
          ]}
        />
      </Space>

      <Drawer
        title={`회원 상세 #${detailId}`}
        open={detailId !== null}
        onClose={() => setDetailId(null)}
        size={480}
      >
        {detailQuery.isLoading ? (
          <Typography.Text>불러오는 중...</Typography.Text>
        ) : null}
        {detailQuery.error ? (
          <Typography.Text type="danger">
            {toApiError(detailQuery.error).message}
          </Typography.Text>
        ) : null}
        {detailQuery.data ? (
          <pre style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>
            {JSON.stringify(detailQuery.data, null, 2)}
          </pre>
        ) : null}
      </Drawer>

      <Modal
        title="회원 등록"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        footer={null}
        destroyOnHidden
      >
        <Form
          layout="vertical"
          onFinish={(values: {
            username: string;
            password: string;
            display_name?: string;
            roles: string[];
            is_active: boolean;
          }) => createMut.mutate(values)}
          initialValues={{ roles: ["viewer"], is_active: true }}
        >
          <Form.Item name="username" label="username" rules={[{ required: true, min: 3 }]}>
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item name="password" label="password" rules={[{ required: true, min: 8 }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="display_name" label="display_name">
            <Input />
          </Form.Item>
          <Form.Item name="roles" label="roles" rules={[{ required: true }]}>
            <Select
              mode="multiple"
              options={[
                { value: "admin", label: "admin (관리자)" },
                { value: "operator", label: "operator (운영자)" },
                { value: "viewer", label: "viewer (조회자)" },
              ]}
            />
          </Form.Item>
          <Form.Item name="is_active" label="활성" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={createMut.isPending} block>
            등록
          </Button>
        </Form>
      </Modal>

      <Modal
        title={`회원 수정 — ${editTarget?.username ?? ""}`}
        open={Boolean(editTarget)}
        onCancel={() => setEditTarget(null)}
        footer={null}
        destroyOnHidden
      >
        {editTarget ? (
          <Form
            layout="vertical"
            initialValues={{
              display_name: editTarget.display_name ?? "",
              roles: editTarget.roles,
              is_active: editTarget.is_active,
            }}
            onFinish={(values: {
              display_name?: string;
              roles: string[];
              is_active: boolean;
            }) =>
              updateMut.mutate({
                id: editTarget.id,
                body: values,
              })
            }
          >
            <Form.Item name="display_name" label="display_name">
              <Input />
            </Form.Item>
            <Form.Item name="roles" label="roles" rules={[{ required: true }]}>
              <Select
                mode="multiple"
                options={[
                  { value: "admin", label: "admin (관리자)" },
                  { value: "operator", label: "operator (운영자)" },
                  { value: "viewer", label: "viewer (조회자)" },
                ]}
              />
            </Form.Item>
            <Form.Item name="is_active" label="활성" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={updateMut.isPending} block>
              저장
            </Button>
          </Form>
        ) : null}
      </Modal>

      <Modal
        title={`비밀번호 초기화 — ${resetTarget?.username ?? ""}`}
        open={Boolean(resetTarget)}
        onCancel={() => setResetTarget(null)}
        footer={null}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary">
          새 비밀번호를 비우면 임시 비밀번호가 자동 생성됩니다.
        </Typography.Paragraph>
        <Form
          layout="vertical"
          onFinish={(values: { new_password?: string }) => {
            if (!resetTarget) return;
            resetMut.mutate({
              id: resetTarget.id,
              password: values.new_password || undefined,
            });
          }}
        >
          <Form.Item name="new_password" label="새 비밀번호 (선택)">
            <Input.Password placeholder="비우면 자동 생성" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={resetMut.isPending} block>
            초기화
          </Button>
        </Form>
      </Modal>

      <Modal
        title="임시 비밀번호"
        open={Boolean(tempPassword)}
        onOk={() => setTempPassword(null)}
        onCancel={() => setTempPassword(null)}
      >
        <Typography.Paragraph>
          한 번만 표시됩니다. 안전한 채널로 전달하세요.
        </Typography.Paragraph>
        <Typography.Text code copyable>
          {tempPassword}
        </Typography.Text>
      </Modal>
    </AdminPageShell>
  );
}
