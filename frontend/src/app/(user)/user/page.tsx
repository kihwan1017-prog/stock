import { redirect } from "next/navigation";

import { userRoutes } from "@/config/routes";

export default function UserIndexPage() {
  redirect(userRoutes.dashboard);
}
