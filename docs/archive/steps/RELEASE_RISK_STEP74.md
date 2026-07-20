# RELEASE_RISK_STEP74

## 판정

**CONDITIONAL APPROVAL** — STEP65–73 사용자 모듈 모듈리스 운영 가능.  
전체 제품(자동매매 UI·Telegram 실발송·E2E 자동화)은 STEP75+ 필요.

---

## 미수정 / 잔여 위험

| ID | 등급 | 영향 | 우회 | 예정 |
|----|------|------|------|------|
| R74-01 | Medium | Telegram 실발송/DLQ 없음 | Web Inbox로 확인 | STEP75+ |
| R74-02 | Medium | Watchlist 그룹 없음 | flat 목록 사용 | 요구 시 |
| R74-03 | Medium | Trading/Strategies/Auto-trading UX·admin API 혼재 | 해당 메뉴 제한 안내 | STEP75 |
| R74-04 | Medium | npm postcss moderate | next 패치 대기, force 금지 | 의존성 점검 |
| R74-05 | Low | Playwright E2E 미자동화 | 수동 UAT | STEP75 |
| R74-06 | Low | 오류 code 표준화 불완전 | message 표시 | 점진 적용 |
| R74-07 | Low | 2FA/이메일 변경/탈퇴 없음 | 문서 명시 | 후속 |
| R74-08 | Low | Refresh Token localStorage | HttpOnly 전환 검토 | 보안 강화 |

---

## 차단 조건 (현재 해당 없음)

- Critical IDOR / Secret 노출 / Kill Switch 우회 / Migration multiple heads
