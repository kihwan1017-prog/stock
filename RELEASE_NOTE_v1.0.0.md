# RELEASE_NOTE — v1.0.0

**버전:** 1.0.0 (GA)  
**일자:** 2026-07-20  
**결정:** **RELEASE WITH KNOWN ISSUES**

본 문서의 짧은 별칭: [RELEASE_NOTE.md](RELEASE_NOTE.md)

---

## 요약

Stock Platform을 **Version 1.0.0** 제품으로 고정합니다.  
신규 비즈니스 기능은 추가하지 않았고, 버전 일관성·문서·패키징·운영 인수인계·최종 검증을 완료했습니다.

배포 범위:

| 시나리오 | 허용 |
|----------|------|
| 사설망 + 단일 운영자 + Paper + Live OFF | ✅ (Known Issues 인지 필수) |
| 공개망 · 실고객 · Live 자동매매 | ❌ (STEP63 BLOCK) |

---

## 신규 기능 (1.0.0에 포함되는 누적 범위)

- JWT/RBAC Admin·User Web
- Paper 주문 · Outbox · Kill Switch · Daily Loss · Exit Monitor
- AI(Ollama) · Screener · News/Disclosure · Strategy Deployment
- Monitoring live/ready/overview (STEP61)
- Windows `ops/` 배포 (STEP60)
- Security hardening (STEP59/62)

---

## 보안 개선

- 민감 mutate Admin 강제 (부분 — 잔여는 Known Issues)
- 운영 docs/signup 차단 · CORS · rate limit · 마스킹
- JWT DB RBAC · refresh reuse revoke-all

---

## 성능 개선

- STEP58 핫패스 (pool, exit monitor thread, ollama cache)

---

## 리팩토링

- 본 STEP64에서는 **대규모 리팩터 없음**
- 버전 문자열만 `1.0.0`으로 통일 (`APP_VERSION`, OpenAPI, frontend package)

---

## 삭제

- OpenClaw · DEV_OPEN (이전 STEP)

---

## Breaking Change

RC1과 동일 + GA 버전 문자열:

- Admin 필수 API 확대
- 운영 OpenAPI 비활성
- 운영 Signup 403
- CORS localhost 단독 불가

---

## Known Issues (필수 인지)

1. 일부 mutate API 무인증 (pipeline/AI/sync/strategy-runtime 등)  
2. Outbox `PaperBrokerAdapter` 고정  
3. Telegram webhook secret 미설정 시 fail-open  
4. `account_id=1` 하드코딩 경로  
5. Live E2E 부재 · 단일 인스턴스 SPOF  

전체: [KNOWN_ISSUES.md](KNOWN_ISSUES.md) · [TOP_100_IMPROVEMENTS.md](TOP_100_IMPROVEMENTS.md)

---

## 검증

| 항목 | 결과 |
|------|------|
| pytest | 349 passed, 3 skipped |
| FE lint / typecheck / test / build | PASS |
| 버전 | Backend/Frontend/API `1.0.0` |

---

## Git Tag 안내

자동 태그/커밋은 수행하지 않습니다.  
기존 `v1.0.0` 태그가 **구 커밋(STEP40)** 을 가리킬 수 있으므로, 배포 커밋 확정 후 사용자가 재태깅해야 합니다.

절차: [README_STEP64.md](README_STEP64.md)
