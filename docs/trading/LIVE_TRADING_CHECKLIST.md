# 실전 전환 체크리스트 — stock-platform

실전 주문은 기본 차단입니다. 아래를 모두 통과한 뒤에만 활성화하세요.

## 이중 게이트 (필수 증적)

실전 주문은 **환경 플래그**와 **DB 승인**이 동시에 켜져야만 통과합니다.
어느 한쪽만으로는 LIVE adapter/주문이 열리지 않아야 합니다.

| 게이트 | 조건 | 확인 방법 | 증적 |
|--------|------|-----------|------|
| A. ENV | `KIWOOM_LIVE_ORDER_ENABLED=true` **그리고** `KIWOOM_USE_MOCK=false` | 기동 로그 / settings 덤프(마스킹) | 체크시각·운영자 |
| B. DB | live-transition **APPROVED + active** | `GET/POST /api/v1/broker/live-transition/*` 응답 | transition_id·승인자·승인문구 |
| C. 교차 검증 | A∧B만 LIVE 허용; mock+live 동시 true면 **기동 실패** | settings validator | CI/기동 스모크 |

- [ ] 게이트 A 확인 증적 첨부
- [ ] 게이트 B 확인 증적 첨부 (`ENABLE KIWOOM LIVE TRADING` 승인 문구 포함)
- [ ] 게이트 C: mock/live 교차 금지 스모크 통과
- [ ] Kill Switch OFF 상태에서만 전환 (이상 시 즉시 ON)

## 사전 조건

- [ ] 모의투자 E2E(주문→체결→포지션→손익) 검증 완료
- [ ] 필수 pytest / 회귀 테스트 통과 (`tests/test_security_step62.py` 포함)
- [ ] 최소 모의 운영 기간 충족
- [ ] 최대 손실 기준 충족
- [ ] `KIWOOM_ACCOUNT_NUMBER` 설정
- [ ] `KIWOOM_USE_MOCK=false`
- [ ] `KIWOOM_LIVE_ORDER_ENABLED=true` (승인 직전)
- [ ] WebSocket 구독 JSON 설정
- [ ] `ADMIN_API_KEY` 설정

## 승인 절차

1. `POST /api/v1/broker/live-transition/validate`
2. `POST /api/v1/broker/live-transition/request` (Admin key)
3. `POST /api/v1/broker/live-transition/{id}/approve`
   - 승인 문구: `ENABLE KIWOOM LIVE TRADING`
4. LIVE adapter 생성 시 DB 활성 승인 + 환경 플래그 동시 강제됨

## 초기 한도 권장값

- 초기 주문한도 ≤ 100,000 KRW
- 일손실 한도 ≤ 300,000 KRW
- 자동 전략 시작은 초기에는 OFF (`KIWOOM_RECOVERY_START_TRADING=false`)

## 전환 직후 모니터링

- [ ] `/health` UP
- [ ] 계좌상태 sync 성공
- [ ] 첫 주문은 Outbox 경로만 사용
- [ ] 알림(Telegram/Discord) 수신 확인
- [ ] 이상 시 즉시 Kill Switch + live-transition disable
