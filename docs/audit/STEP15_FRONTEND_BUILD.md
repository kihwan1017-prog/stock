# STEP 15 — 프런트엔드 의존성·빌드 복구

## 조치
- 
pm install로 package-lock 동기화 (Playwright 1.61)
- 
pm ci 성공
- typecheck / build 성공
- lint: **0 errors** (warnings 7)
- vitest: **65 passed**

## 권장 커밋
ix(step15): sync frontend lockfile and restore npm ci
