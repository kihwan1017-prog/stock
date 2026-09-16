"use client";

import { userRoutes } from "@/config/routes";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { ProfileWorkspace } from "@/features/user/profile/ProfileWorkspace";

export default function UserProfilePage() {
  return (
    <ProfileWorkspace
      Shell={UserPageShell}
      homeHref={userRoutes.dashboard}
      homeLabel="User"
      title="My Page"
    />
  );
}
