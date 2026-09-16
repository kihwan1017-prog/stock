"use client";

import { ManualPane } from "./ManualPane";
import { ADMIN_MANUAL_SECTIONS } from "./manualDataAdmin";

export function AdminManual() {
  return (
    <ManualPane
      sections={ADMIN_MANUAL_SECTIONS}
      searchPlaceholder="관리자 메뉴·기능 검색"
    />
  );
}
