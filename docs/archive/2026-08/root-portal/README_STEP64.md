# README_STEP64 — Version 1.0.0 FINAL PRODUCT RELEASE

**일자:** 2026-07-20  
**목표:** 기능 추가 없이 v1.0.0 제품 완성 (문서 · 패키징 · 인수인계 · 검증)

---

## 한줄 요약

**RELEASE WITH KNOWN ISSUES** — 사설망 Paper 운영용 GA. 공개망/고객 Live는 비허용.

---

## 수행 내용

### 1. Version 고정

- Backend: `APP_VERSION` / `settings.app_version` = `1.0.0`
- FastAPI OpenAPI·`GET /` → `settings.app_version` 사용 (rc1 하드코딩 제거)
- Frontend: `package.json` → `1.0.0`
- UI: Admin Monitoring/Operations가 `GET /version` 표시

### 2. 문서

| 산출물 |
|--------|
| `CHANGELOG.md` · `RELEASE_NOTE_v1.0.0.md` · `RELEASE_NOTE.md` |
| `README.md` (인코딩 복구·인덱스) |
| `SECURITY.md` · `BACKUP.md` · `RECOVERY.md` |
| `API.md` · `ARCHITECTURE.md` · `DB_SCHEMA.md` |
| `RUNBOOK.md` · `INCIDENT_RESPONSE.md` · `GO_LIVE_CHECKLIST.md` |
| `LICENSE` · `THIRD_PARTY_NOTICES.md` |
| `FINAL_PRODUCT_REPORT.md` · 본 파일 |

기존 유지: `INSTALL.md` · `OPERATIONS.md` · STEP59–63 감사 문서

### 3. 검증

pytest 349 passed / FE lint·typecheck·test·build PASS

### 4. Git (자동 작업 없음)

커밋·태그·푸시는 **사용자가 요청할 때만** 수행합니다.

---

## Tag `v1.0.0` 안내 (수동)

저장소에 **이미** `v1.0.0` 태그가 있을 수 있으며, 과거 커밋(STEP40)을 가리킬 수 있습니다.

배포 커밋을 확정한 뒤 (예시):

```powershell
# 1) 변경사항 커밋 (사용자 요청 시)
git add -A
git status
git commit -m "release: ship stock-platform v1.0.0 GA documentation and version pins"

# 2) 잘못된 기존 태그 이동이 필요하면 (로컬)
git tag -d v1.0.0
git tag -a v1.0.0 -m "stock-platform v1.0.0 GA"

# 3) 원격에 강제 갱신 필요 시 — 팀 합의 후에만
# git push origin v1.0.0
# git push --force origin refs/tags/v1.0.0   # 위험: 합의 필수
```

또는 새 태그 `v1.0.0-ga`를 쓰고 문서를 맞추는 방법도 안전합니다.

---

## 결정 근거

| 항목 | 결과 |
|------|------|
| 제품 패키징·문서 | 완료 |
| 테스트 그린 | 완료 |
| STEP63 Critical 잔존 | 있음 → Known Issues |
| 고객 Live | BLOCK |

상세: [FINAL_PRODUCT_REPORT.md](FINAL_PRODUCT_REPORT.md)

---

## 하지 않은 것

- 신규 기능 / 대규모 리팩터 / Critical 보안 코드 수정 (의도적 — STEP64 범위 밖)
- 자동 커밋 · 자동 태그 · 자동 push
