"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Card,
  Checkbox,
  Col,
  Row,
  Space,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import type { RoleRecord } from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { PermissionButton } from "@/features/auth/components/PermissionButton";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const ROLE_COLORS: Record<string, string> = {
  admin: "magenta",
  operator: "blue",
  viewer: "default",
};

export default function AdminRolesPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [selectedRoleId, setSelectedRoleId] = useState<number | null>(null);
  const [draftByRoleId, setDraftByRoleId] = useState<Record<number, string[]>>(
    {},
  );

  const rolesQuery = useQuery({
    queryKey: queryKeys.admin.roles(),
    queryFn: adminApi.listRoles,
  });

  const permissionsQuery = useQuery({
    queryKey: queryKeys.admin.permissions(),
    queryFn: () => adminApi.listPermissions(),
  });

  const roles = useMemo(
    () => rolesQuery.data ?? [],
    [rolesQuery.data],
  );

  const selected: RoleRecord | undefined = useMemo(() => {
    if (!roles.length) {
      return undefined;
    }
    return roles.find((role) => role.id === selectedRoleId) ?? roles[0];
  }, [roles, selectedRoleId]);

  const draftPermissions = useMemo(() => {
    if (!selected) {
      return [];
    }
    return draftByRoleId[selected.id] ?? selected.permissions;
  }, [draftByRoleId, selected]);

  const selectRole = (role: RoleRecord) => {
    setSelectedRoleId(role.id);
    setDraftByRoleId((prev) =>
      prev[role.id] ? prev : { ...prev, [role.id]: role.permissions },
    );
  };

  const saveMut = useMutation({
    mutationFn: () =>
      adminApi.updateRolePermissions(selected!.id, draftPermissions),
    onSuccess: (updated) => {
      message.success("역할 권한이 저장되었습니다.");
      setDraftByRoleId((prev) => ({
        ...prev,
        [updated.id]: updated.permissions,
      }));
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.roles(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const permissionsByCategory = useMemo(() => {
    const map = new Map<string, adminApi.PermissionRecord[]>();
    for (const perm of permissionsQuery.data ?? []) {
      const list = map.get(perm.category) ?? [];
      list.push(perm);
      map.set(perm.category, list);
    }
    return map;
  }, [permissionsQuery.data]);

  const isAdminRole = selected?.code === "admin";

  return (
    <AdminPageShell
      title="권한관리"
      description="Role / Permission / RolePermission — 관리자·운영자·조회자"
    >
      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}>
          <Card title="역할" loading={rolesQuery.isLoading} size="small">
            <Space orientation="vertical" style={{ width: "100%" }}>
              {roles.map((role) => (
                <Card
                  key={role.id}
                  size="small"
                  hoverable
                  type={selected?.id === role.id ? "inner" : undefined}
                  onClick={() => selectRole(role)}
                  style={{
                    borderColor:
                      selected?.id === role.id ? "#1677ff" : undefined,
                  }}
                >
                  <Space>
                    <Tag color={ROLE_COLORS[role.code] ?? "default"}>
                      {role.code}
                    </Tag>
                    <Typography.Text strong>{role.name}</Typography.Text>
                  </Space>
                  <Typography.Paragraph
                    type="secondary"
                    style={{ marginBottom: 0, marginTop: 8 }}
                  >
                    {role.description}
                  </Typography.Paragraph>
                  <Typography.Text type="secondary">
                    permissions: {role.permissions.length}
                  </Typography.Text>
                </Card>
              ))}
            </Space>
          </Card>
        </Col>
        <Col xs={24} md={16}>
          <Card
            title={
              selected
                ? `${selected.name} (${selected.code}) 권한`
                : "권한 선택"
            }
            loading={permissionsQuery.isLoading}
            extra={
              <PermissionButton
                permission="roles:write"
                type="primary"
                disabled={!selected || isAdminRole || saveMut.isPending}
                onClick={() => saveMut.mutate()}
              >
                저장
              </PermissionButton>
            }
          >
            {isAdminRole ? (
              <Typography.Paragraph type="secondary">
                admin 역할은 전체 권한이 고정됩니다. 변경할 수 없습니다.
              </Typography.Paragraph>
            ) : null}
            {[...permissionsByCategory.entries()].map(
              ([category, perms]) => (
                <div key={category} style={{ marginBottom: 16 }}>
                  <Typography.Title level={5}>{category}</Typography.Title>
                  <Checkbox.Group
                    disabled={isAdminRole}
                    value={draftPermissions}
                    onChange={(values) => {
                      if (!selected) {
                        return;
                      }
                      setDraftByRoleId((prev) => ({
                        ...prev,
                        [selected.id]: values as string[],
                      }));
                    }}
                    options={perms.map((perm) => ({
                      label: `${perm.name} (${perm.code})`,
                      value: perm.code,
                    }))}
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 8,
                    }}
                  />
                </div>
              ),
            )}
          </Card>
        </Col>
      </Row>
    </AdminPageShell>
  );
}
