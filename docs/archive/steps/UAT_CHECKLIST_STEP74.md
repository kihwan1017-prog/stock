# UAT_CHECKLIST_STEP74

Test 환경 전용. 운영 계정·운영 DB 금지.  
실제 Broker 주문 실행 금지.

각 항목: PASS / FAIL / N/A + 비고.

---

## AUTH / PROFILE

| ID | 절차 | 예상 | 결과 |
|----|------|------|------|
| UAT-A01 | 로그인 | 토큰 발급, 대시보드 | |
| UAT-A02 | Profile 조회 | 이메일·이름 표시, JWT 미표시 | |
| UAT-A03 | 프로필 수정 저장 | 반영 | |
| UAT-A04 | 비밀번호 변경 | 성공, 타기기 세션 종료 | |
| UAT-A05 | 세션 목록 | 현재 기기 Badge | |
| UAT-A06 | 다른 기기 로그아웃 | 세션 감소 | |
| UAT-A07 | 로그아웃 | 로그인 화면 | |

## ACCOUNT / PORTFOLIO

| ID | 절차 | 예상 | 결과 |
|----|------|------|------|
| UAT-B01 | Paper 계좌 생성 | 목록 표시 | |
| UAT-B02 | 기본 계좌 지정 | is_default | |
| UAT-B03 | Portfolio 진입 | Empty 또는 데이터 | |
| UAT-B04 | 타 account_id 직접 호출 | 403/404 | |
| UAT-B05 | 계좌 없을 때 Empty | 안내+링크 | |

## WATCHLIST / NEWS / DISCLOSURE

| ID | 절차 | 예상 | 결과 |
|----|------|------|------|
| UAT-C01 | 관심종목 추가 | 목록 | |
| UAT-C02 | 중복 추가 | 거부 | |
| UAT-C03 | 뉴스 목록·읽음 | unread 감소 | |
| UAT-C04 | 공시 목록·상세 | 표시 | |
| UAT-C05 | 공시 AI 요약 | 생성/재사용 (Ollama 가용 시) | |
| UAT-C06 | 그룹 생성 | N/A (미지원) | N/A |

## AI / NOTIFICATION / SETTINGS

| ID | 절차 | 예상 | 결과 |
|----|------|------|------|
| UAT-D01 | AI status | available 등, Host 미노출 | |
| UAT-D02 | 추천 요청 | QUEUED→COMPLETED/FAIL | |
| UAT-D03 | 알림 목록·전체 읽음 | unread=0 | |
| UAT-D04 | 구독 토글 | 저장 | |
| UAT-D05 | Settings Theme 저장 | 새로고침 유지 | |
| UAT-D06 | Settings Reset | 기본값 | |

## ATTACK

| ID | 절차 | 예상 | 결과 |
|----|------|------|------|
| UAT-E01 | `/api/v1/settings` 일반토큰 | 401/403 | |
| UAT-E02 | `/api/v1/ollama/status` 일반토큰 | 401/403 | |
| UAT-E03 | 타 user notification_id | 404 | |
| UAT-E04 | 타 session_id revoke | 404 | |
| UAT-E05 | Body에 user_id 조작 | 무시/거절 | |

## CONNECTIONS

| ID | 절차 | 예상 | 결과 |
|----|------|------|------|
| UAT-F01 | Profile 연결 상태 | KIWOOM/UPBIT/TELEGRAM 카드 | |
| UAT-F02 | Secret 미표시 | 마스킹만 | |
| UAT-F03 | 계좌 관리 링크 | `/user/account` | |
