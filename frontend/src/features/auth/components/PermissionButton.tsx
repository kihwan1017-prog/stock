"use client";

import { Button } from "antd";
import type { ButtonProps } from "antd";

import { useAuth } from "@/features/auth/hooks/useAuth";
import {
  hasAnyPermission,
  hasPermission,
} from "@/features/auth/utils/permissions";

interface PermissionButtonProps extends ButtonProps {
  /** 모두 필요 */
  permission?: string | string[];
  /** 하나라도 있으면 표시 */
  anyPermission?: string | string[];
  /** 권한 없을 때 숨김(기본) / 비활성 */
  mode?: "hide" | "disable";
}

function toList(value?: string | string[]): string[] {
  if (!value) {
    return [];
  }
  return Array.isArray(value) ? value : [value];
}

/** 권한 기반 버튼 — 없으면 숨기거나 비활성 */
export function PermissionButton({
  permission,
  anyPermission,
  mode = "hide",
  disabled,
  children,
  ...rest
}: PermissionButtonProps) {
  const { user } = useAuth();
  const allCodes = toList(permission);
  const anyCodes = toList(anyPermission);

  let allowed = true;
  if (allCodes.length) {
    allowed = hasPermission(user, ...allCodes);
  }
  if (allowed && anyCodes.length) {
    allowed = hasAnyPermission(user, ...anyCodes);
  }

  if (!allowed && mode === "hide") {
    return null;
  }

  return (
    <Button {...rest} disabled={disabled || (!allowed && mode === "disable")}>
      {children}
    </Button>
  );
}

interface PermissionGateProps {
  permission?: string | string[];
  anyPermission?: string | string[];
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

/** 권한 있을 때만 children 렌더 */
export function PermissionGate({
  permission,
  anyPermission,
  children,
  fallback = null,
}: PermissionGateProps) {
  const { user } = useAuth();
  const allCodes = toList(permission);
  const anyCodes = toList(anyPermission);

  let allowed = true;
  if (allCodes.length) {
    allowed = hasPermission(user, ...allCodes);
  }
  if (allowed && anyCodes.length) {
    allowed = hasAnyPermission(user, ...anyCodes);
  }

  if (!allowed) {
    return <>{fallback}</>;
  }
  return <>{children}</>;
}
