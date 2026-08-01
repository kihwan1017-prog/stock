"use client";

import { ManualPane } from "./ManualPane";
import { USER_MANUAL_SECTIONS } from "./manualDataUser";

export function UserManual() {
  return (
    <ManualPane
      sections={USER_MANUAL_SECTIONS}
      searchPlaceholder="사용자 메뉴·기능 검색"
    />
  );
}
