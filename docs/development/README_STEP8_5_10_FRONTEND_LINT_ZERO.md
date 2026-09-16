# STEP 8-5-10 — Frontend Lint Warning 0 및 정적 품질 기준 강화

## 1. 기존 Lint 설정

- 설정: `frontend/eslint.config.mjs` (`eslint-config-next` core-web-vitals + typescript)
- Script: `eslint .` → 이번 STEP에서 `eslint . --max-warnings=0`으로 강화
- Rule 완화·disable·ignore 추가 없음

## 2. 최초 Warning 6건 목록

| # | 파일 | 위치 | Rule | 메시지 |
|---|------|------|------|--------|
| 1 | `src/app/(auth)/onboarding/page.tsx` | 3:24 | `@typescript-eslint/no-unused-vars` | `'Result' is defined but never used` |
| 2 | `src/app/(user)/user/watchlist/page.tsx` | 179:9 | `react-hooks/exhaustive-deps` | `'items' … wrap … in its own useMemo()` |
| 3 | `src/components/layout/AuthGuard.tsx` | 9:10 | `@typescript-eslint/no-unused-vars` | `'adminRoutes' is defined but never used` |
| 4 | `src/lib/storage/tokenStorage.ts` | 61:41 | `@typescript-eslint/no-unused-vars` | `'_persist' is assigned a value but never used` |
| 5 | `src/lib/storage/tokenStorage.ts` | 73:48 | `@typescript-eslint/no-unused-vars` | `'_persist' is assigned a value but never used` |
| 6 | `src/lib/storage/tokenStorage.ts` | 84:31 | `@typescript-eslint/no-unused-vars` | `'_persist' is defined but never used` |

## 3. Warning별 Rule ID

위 표 참고.

## 4. Warning별 원인

1. antd `Result` import만 있고 JSX 미사용
2. `listQuery.data?.items ?? []`가 매 렌더 새 배열 → `useMemo([items])` deps 불안정
3. `adminRoutes` import 미사용
4–6. Remember Me 제거 후 `_persist` 인자만 남김(이름 `_`로 방치)

## 5. 수정 내용

- 미사용 Import 제거 (`Result`, `adminRoutes`)
- `items`를 `useMemo(() => data?.items ?? [], [listQuery.data])`로 안정화
- `setToken`/`setRefreshToken`에서 persist 인자 제거(항상 sessionStorage)
- `setRememberMe` API 삭제, `authStore`는 사용자 프로필 저장에만 rememberMe 사용

## 6. React Hook 수정

Watchlist `ids` useMemo의 의존 `items`가 안정 참조를 갖도록 상위에서 memo화. 무한 호출·불필요 재조회 없음.

## 7. 미사용 코드 수정

미사용 Import 2건, 레거시 `setRememberMe` 및 persist 인자 제거.

## 8. 접근성 수정

해당 Warning 없음 (이번 6건에 a11y 없음).

## 9. 비동기 처리 수정

해당 Warning 없음.

## 10. 타입 안전성 수정

토큰 API 시그니처를 실제 정책(session-only)에 맞게 축소.

## 11. ESLint 설정 변경 여부

Rule off/완화 없음. `eslint.config.mjs` 변경 없음.

## 12. `--max-warnings=0` 적용 여부

**적용함** — `"lint": "eslint . --max-warnings=0"`

## 13. CI·검증 Script 반영

- `frontend/package.json`: `verify` = test + typecheck + lint + build
- `.github/workflows/ci.yml` frontend job: lint + build 추가

## 14. 변경 파일

- `frontend/src/app/(auth)/onboarding/page.tsx`
- `frontend/src/app/(user)/user/watchlist/page.tsx`
- `frontend/src/components/layout/AuthGuard.tsx`
- `frontend/src/lib/storage/tokenStorage.ts`
- `frontend/src/lib/storage/tokenStorage.test.ts`
- `frontend/src/features/auth/store/authStore.ts`
- `frontend/package.json`
- `.github/workflows/ci.yml`
- `docs/development/README_STEP8_5_10_FRONTEND_LINT_ZERO.md`

## 15. 추가·수정 테스트

`tokenStorage.test.ts` — localStorage에 access token 미기록 검증 추가.

## 16. Frontend 검증 결과

- Vitest: **84 passed / 0 failed** (tokenStorage 테스트 +1)
- TypeScript: 통과
- Lint: **0 errors / 0 warnings** (`--max-warnings=0`)
- Production Build: 성공

## 17. Backend 회귀 결과

- pytest: **691 passed / 0 failed / 3 skipped**
- Alembic Head: **y2c3d4e5f6a7** (single)
- Migration: 없음

## 18. Migration 여부

**Migration 없음** — Head `y2c3d4e5f6a7` 유지.

## 19. 운영 적용

Frontend 재배포만. DB 변경 없음.

## 20. 남은 문제

대규모 미사용 Component/API 정리·Route 재편은 별도 STEP.
