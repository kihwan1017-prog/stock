/**
 * 사용자 화면 DISPLAY 라벨 사전.
 * API/DB/enum 원본값은 변경하지 않는다 — UI title/column만.
 */

export const UI_LABEL_KO = {
  portfolioSlots: "자동매매 후보 슬롯",
  slot: "슬롯",
  symbol: "종목",
  score: "점수",
  ai: "AI 판단",
  confidence: "신뢰도",
  ownership: "구분",
  status: "상태",
  waitingAge: "대기 시간",
  lastEvaluated: "최근 평가",
  entryDecision: "매수 판단",
  blockReason: "차단 사유",
  reservedKrw: "예약 금액",
  orderId: "주문번호",
  autoPositions: "자동매매 보유 포지션",
  qty: "수량",
  entry: "진입가",
  current: "현재가",
  pnl: "손익(PnL)",
  allocated: "배정 금액",
  slTpTrailing: "손절 / 익절 / 트레일링",
  highest: "고점",
  exitMonitor: "청산 감시",
  binding: "포지션 바인딩",
  entryBlockSummary: "최근 매수 평가 차단 요약",
  // runtime cards
  h24: "24시간 자동운영",
  live: "실거래(LIVE)",
  arm: "자동주문 승인(ARM)",
  runtime: "자동매매 런타임",
  worker: "주문 처리 워커",
  executionRunner: "주문 실행기",
  feed: "실시간 시세",
  entryEvaluator: "매수조건 평가기",
  readiness: "자동매매 준비상태",
  // research
  entryForwardValidation: "진입 전략 Forward 검증",
  candidate: "검증 후보",
  progress: "검증 진행률",
  combined: "전체 표본",
  newSample: "신규 미사용 표본",
  baseline: "현재 기준 전략",
  candidateB1: "후보 B1",
  filterBenefit: "필터 개선 효과",
  earlyDump: "진입 직후 하락",
  promotion: "REAL 적용 검토",
  notReady: "표본 수집 중",
  reviewReady: "적용 검토 가능",
  // common actions / empty
  refresh: "새로고침",
  details: "상세보기",
  preview: "미리보기",
  noData: "데이터가 없습니다.",
  loading: "불러오는 중...",
  loadFailed: "데이터를 불러오지 못했습니다.",
} as const;

export const UI_TOOLTIP_KO = {
  arm: "실제 주문을 제출할 수 있도록 일정 시간 동안 승인된 상태입니다.",
  readiness:
    "LIVE, ARM, Runtime, 시세, Risk 등 실제 자동매매에 필요한 조건을 종합한 상태입니다.",
  reservedKrw: "매수 주문을 위해 포트폴리오 슬롯에 임시로 확보한 금액입니다.",
  mfe: "진입 후 가장 유리했던 최대 수익률입니다.",
  mae: "진입 후 가장 불리했던 최대 손실률입니다.",
  forward:
    "아직 REAL에 적용하지 않은 진입 후보를, 이후 시장 데이터로만 검증합니다.",
  shadow: "실주문 없이 분석용으로만 추적하는 가상 진입입니다.",
  live: "실제 자금으로 주문이 나갈 수 있는 실거래 모드입니다.",
} as const;
