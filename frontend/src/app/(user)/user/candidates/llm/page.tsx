import { redirect } from "next/navigation";

import { userRoutes } from "@/config/routes";

/** LLM 분석은 기존 「AI 추천」 화면을 그대로 사용 */
export default function UserCandidatesLlmRedirectPage() {
  redirect(userRoutes.ai);
}
