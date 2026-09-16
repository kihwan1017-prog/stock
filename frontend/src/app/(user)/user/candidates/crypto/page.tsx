"use client";

import { CandidatesView } from "@/features/user/candidates/CandidatesView";

export default function UserCandidatesCryptoPage() {
  return (
    <CandidatesView
      title="업비트 매매 후보"
      exchangeCode="UPBIT"
      description="암호화폐 종목 스코어링 배치 결과입니다. 관심종목 기반 참고 추천은 AI 추천 화면에서도 확인할 수 있습니다."
    />
  );
}
