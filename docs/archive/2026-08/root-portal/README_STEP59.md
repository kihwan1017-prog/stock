# README_STEP59 — Release Candidate (v1.0.0-RC1)

## 목적

프로젝트를 **Release Candidate(RC1)** 수준으로 운영 준비합니다.

- 신규 기능 없음
- API 변경 최소화 (보안 가드·에러 포맷 정렬)
- 운영 점검 · 문서 · 검증 중심

---

## 수행 내용

### Production Configuration
- `LOG_LEVEL`, `CORS_ALLOW_ORIGINS` 추가
- 운영에서 CORS localhost 단독 거부
- `.env.example` RC 주석 · bootstrap 비밀번호 placeholder

### Security
- Critical mutate API에 `require_admin` (Broker / Realtime / Recovery / Order transition / Strategy deployment / Safety)
- 운영 Swagger/OpenAPI 비활성
- 운영 공개 Signup 403

### Error Handling
- `HTTPException` / `RequestValidationError` / 미처리 `Exception` → 통일 포맷  
  `{ code, message, detail, request_id }`
- 운영 500은 내부 메시지 숨김

### Logging
- `LOG_LEVEL` 반영
- (기존) 시크릿 감사 마스킹 · Exit/Notification 로그 축소 유지

### Startup / Shutdown
- 기존 fail-fast(settings+DB) + optional degrade 유지
- Lifecycle 알림 timeout(STEP58) 유지
- Exit monitor shutdown `wait=False` 유지

### Backup
- `RELEASE_CHECKLIST.md`에 dump/restore 절차 요약
- 상세는 `docs/manual/백업복구매뉴얼.md`

---

## Production 점검 요약

| 항목 | 결과 |
|------|------|
| JWT / ADMIN_API_KEY (prod) | 기동 필수 ✅ |
| DEV_OPEN | 제거됨 ✅ |
| Swagger (prod) | 숨김 ✅ |
| Signup (prod) | 차단 ✅ |
| Broker mutate auth | Admin 필수 ✅ |
| `/health` 상세 | 잔여 (KNOWN_ISSUES) |
| Docker | 없음 (KNOWN_ISSUES) |

---

## 산출 문서

| 파일 | 용도 |
|------|------|
| `RELEASE_CHECKLIST.md` | 배포 전 체크리스트 + Backup |
| `KNOWN_ISSUES.md` | 잔여 이슈·제약 |
| `RELEASE_NOTE_v1.0.0_RC1.md` | RC1 릴리즈 노트 |
| `README_STEP59.md` | 본 문서 |

---

## 최종 평가 (100점 만점)

| 항목 | 점수 | 근거 |
|------|------|------|
| Architecture | **78** | 계층·스키마 분리 양호. broker/brokers·일부 라우터 권한 불균일 잔존 |
| Security | **72** | Critical 무인증 mutate 봉쇄·docs/signup 운영 차단. 조회 API·health 상세는 후속 |
| Performance | **74** | STEP58 pool/to_thread/cache. Screener N+1·health 지연 잔존 |
| Maintainability | **80** | 매뉴얼·STEP README·설정 카탈로그. dead code 정리(STEP56) |
| Scalability | **58** | 단일 인스턴스·동기 ORM·공유 스케줄러 다수. 수평 확장 전제 약함 |
| Testing | **76** | 단위/API 스모크 풍부. E2E·부하·Live broker 통합은 약함 |
| Documentation | **85** | 운영 매뉴얼·체크리스트·Known Issues·Release Note |
| Production Readiness | **70** | **내부망 RC1 가능**. 공개망·Live 자동매매 완전체는 체크리스트+후속 필수 |

**종합: 약 74 / 100 — Internal RC1 Ready**

판정:
- ✅ 사설망 + Paper/모니터링 중심 RC 배포 가능
- ⚠️ Live 주문은 `RELEASE_CHECKLIST` 완료 + 별도 승인 후
- ❌ 멀티테넌시/공개 SaaS 수준 아님

---

## 검증 (2026-07-20 실행)

| 검사 | 결과 |
|------|------|
| `pytest` | PASS — **340 passed**, 3 skipped, 0 failed |
| frontend `lint` | PASS (unused-vars warning 2) |
| frontend `typecheck` | PASS |
| frontend `test` | PASS (16 files / 37 tests) |
| frontend `build` | PASS |

```bash
pytest
# frontend
npm run lint && npm run typecheck && npm run test && npm run build
```

---

## 권장 다음 단계 (RC2 / GA)

1. 잔여 조회 API RBAC  
2. health liveness/readiness 분리  
3. Docker 배포  
4. Screener/Outbox 성능 후속  
5. Live 주문 운영 런북 리허설
