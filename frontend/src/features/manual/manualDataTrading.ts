import type { ManualGuideStep, ManualMarketFlow } from "./manualTypes";

export const AUTO_TRADING_COMMON_STEPS: ManualGuideStep[] = [
  { id: "s1", title: "계좌 등록", detail: "Paper/키움/업비트 계좌를 등록합니다." },
  {
    id: "s2",
    title: "Credential 검증",
    detail: "브로커 Credential을 검증합니다. Secret은 화면에 다시 보여주지 않습니다.",
  },
  {
    id: "s3",
    title: "시장 데이터 확인",
    detail: "시세·갱신 시각·WebSocket 상태를 확인합니다.",
  },
  {
    id: "s4",
    title: "기술지표 설정",
    detail: "관리자 기술지표 파라미터를 확인하고 필요 시 Preview 후 적용합니다.",
  },
  { id: "s5", title: "후보 생성", detail: "매매 후보·LLM 분석을 검토합니다." },
  {
    id: "s6",
    title: "전략 요청",
    detail: "사용자가 Strategy Request를 생성하고 관리자가 심사합니다.",
  },
  { id: "s7", title: "Draft 생성", detail: "승인 Request 위 Strategy Draft를 작성·버전 관리합니다." },
  { id: "s8", title: "관리자 검토", detail: "Draft/Definition을 승인 또는 반려합니다." },
  { id: "s9", title: "Backtest", detail: "백테스트를 실행합니다." },
  {
    id: "s10",
    title: "성과·위험 검증",
    detail: "Quality Gate·Sensitivity·Monte Carlo·Portfolio Validation을 통과시킵니다.",
  },
  { id: "s11", title: "Human Decision", detail: "최종 사람 승인/반려를 기록합니다." },
  { id: "s12", title: "Promotion", detail: "Promotion Commit으로 배포 가능 상태를 고정합니다." },
  { id: "s13", title: "Activation", detail: "전략을 활성화합니다." },
  {
    id: "s14",
    title: "Runtime Registration",
    detail: "Runtime에 전략을 등록합니다.",
  },
  {
    id: "s15",
    title: "Deployment Readiness",
    detail: "배포 준비 상태를 확인합니다.",
  },
  {
    id: "s16",
    title: "Operation Readiness",
    detail: "운영 준비 상태를 확인합니다.",
  },
  {
    id: "s17",
    title: "계좌 전략 연결",
    detail: "Account Strategy Link로 계좌와 전략을 연결합니다.",
  },
  { id: "s18", title: "리스크 설정", detail: "한도·Kill Switch·Pause 정책을 확인합니다." },
  {
    id: "s19",
    title: "Runtime 시작",
    detail: "허용된 모드에서만 START합니다. LIVE는 기본 OFF·승인·Unlock 필요.",
    status: "default_off",
  },
  {
    id: "s20",
    title: "주문·체결 확인",
    detail: "주문 상태·체결·전략 Provenance를 확인합니다.",
  },
  {
    id: "s21",
    title: "Position·Balance·PnL",
    detail: "원장과 브로커 잔고를 대조합니다.",
  },
  {
    id: "s22",
    title: "Monitoring·Recovery",
    detail: "운영센터·장애 복구·WebSocket을 지속 감시합니다.",
  },
];

export const AUTO_TRADING_MARKET_FLOWS: ManualMarketFlow[] = [
  {
    id: "paper",
    title: "A. Paper 자동매매",
    status: "available",
    steps: [
      "Paper 계좌 생성",
      "전략 승인·연결",
      "리스크 한도 설정",
      "Paper Runtime START",
      "주문·체결·PnL 확인",
    ],
    warnings: ["실거래소 주문이 아닙니다."],
  },
  {
    id: "kiwoom-mock",
    title: "B. Kiwoom MOCK 자동매매",
    status: "available",
    steps: [
      "키움 계좌·MOCK Credential 검증",
      "전략·리스크 준비",
      "MOCK Runtime START",
      "주문/체결 동기화 확인",
    ],
    warnings: ["MOCK과 LIVE Credential/Flag를 혼용하지 않습니다."],
  },
  {
    id: "upbit-shadow",
    title: "C. Upbit Shadow/Dry-run",
    status: "shadow_dry_run",
    steps: [
      "업비트 계좌·Credential 검증",
      "Shadow/Dry-run 경로로 사전 점검",
      "주문 미전송 또는 비실거래 모드 확인",
      "로그·상태 전이 확인",
    ],
    warnings: ["Shadow/Dry-run을 LIVE로 오인하지 않습니다."],
  },
  {
    id: "upbit-live",
    title: "D. Upbit LIVE 준비",
    status: "admin_approval",
    steps: [
      "Shadow/Dry-run·소액 LIVE 검증 완료",
      "관리자 승인·Risk Gate·Unlock",
      "LIVE Flag는 기본 OFF — 매뉴얼이 직접 ON을 지시하지 않음",
      "승인된 절차·체크리스트에 따라만 진행",
    ],
    warnings: [
      "모든 LIVE Flag 기본 OFF",
      "관리자 승인·Unlock·Risk Gate 필수",
      "임의 Flag 변경 금지",
    ],
  },
  {
    id: "kiwoom-live",
    title: "E. Kiwoom LIVE 준비",
    status: "limited",
    steps: [
      "MOCK 검증 완료",
      "OAuth/장중 검증 제한사항 확인",
      "관리자 승인·Risk Gate·Unlock",
      "LIVE Flag 기본 OFF 유지 원칙",
    ],
    warnings: [
      "OAuth·장중 제약으로 즉시 LIVE 불가할 수 있음",
      "제한사항 해소·승인 전 LIVE 시작 금지",
    ],
  },
];
