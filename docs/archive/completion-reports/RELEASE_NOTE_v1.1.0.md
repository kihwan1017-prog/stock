# RELEASE_NOTE — v1.1.0

**버전:** 1.1.0 (GA)  
**일자:** 2026-07-21  
**결정:** **GO (CONDITIONAL)** — STEP74 CONDITIONAL APPROVAL 기반  
**이전:** [RELEASE_NOTE_v1.0.0.md](RELEASE_NOTE_v1.0.0.md)

---

## 요약

Stock Platform **Version 1.1.0**은 일반 사용자 Self 기능(계좌·포트폴리오·관심종목·뉴스·공시·AI·알림·설정·프로필)을  
Admin 운영 콘솔과 분리하여 Production 패키징한 릴리즈입니다.

신규 대규모 기능 개발은 STEP75에서 하지 않았습니다 (Release Freeze).

---

## 신규 기능 (사용자)

| STEP | 기능 |
|------|------|
| 65 | 사용자 계좌 소유권 · Paper/키움/업비트 연결 Self API |
| 66 | 포트폴리오 자산 이력 · Snapshot · MDD |
| 67 | 관심종목 |
| 68 | 관심종목 뉴스 · 읽음/북마크 |
| 69 | 관심종목 공시 · 사용자 AI 요약 |
| 70 | AI 종목 추천 (주문 비연결) |
| 71 | Notification Center · 구독 · Quiet Time |
| 72 | User Preferences (admin Settings 분리) |
| 73 | Profile · 비밀번호 · 세션 · 연결 상태 |

---

## 개선사항

- 사용자 화면에서 관리자 Settings/Ollama 의존 제거
- Header 알림 Badge · Preferences Theme 연동
- 통합 감사(STEP74) Quiet Time 실적용

---

## 보안 강화

- Self API JWT 소유권 · IDOR 차단
- 세션 public id · 민감정보 마스킹
- Refresh reuse revoke · 비밀번호 Rate Limit
- STEP62/74 보안 리뷰 반영 확인

---

## 성능

- STEP58 핫패스 유지
- STEP74: 부하 P95 미측정(스모크만) — 운영 전 권장 측정

---

## 관리자 기능

- v1.0.0 Admin 콘솔·Ops·Settings·Monitoring 유지
- Breaking Change 없음

---

## 버그 수정 (1.1.0 패키징 포함)

- `userApi` 미사용 admin `/settings`·`/ollama` 래퍼 제거
- Notification Quiet Time Telegram 억제 누락 수정

---

## 알려진 제한

- Telegram DLQ/실발송 워커 미완
- Watchlist 그룹 없음
- Trading/Strategies/Auto-trading 일부 UI 미완
- Playwright E2E 미자동화
- Live 주문·공개 SaaS는 계속 BLOCK 기조

상세: [docs/archive/steps/RELEASE_RISK_STEP74.md](docs/archive/steps/RELEASE_RISK_STEP74.md)

---

## Migration

```bash
# 배포 전 백업 후 Test/Prod에서 수동
.\.venv\Scripts\python.exe -m alembic upgrade head
# head = g3b4c5d6e7f8
```

---

## Freeze

- Migration Freeze (신규 revision 금지 until next minor)
- Prompt Version Freeze
- API 계약 변경 금지 (버그픽스만)
