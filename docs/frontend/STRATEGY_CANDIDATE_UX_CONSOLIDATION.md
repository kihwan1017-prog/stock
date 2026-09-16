# STRATEGY_CANDIDATE Admin UX Consolidation

**일자:** 2026-08-21  
**범위:** Admin 사이드바「전략·후보」메뉴 통합 (API/DB/Runtime 미변경)

## 목적

운영자가 이해해야 하는 메뉴 수를 줄인다. Backend·Candidate/Strategy lifecycle·Upbit Portfolio Runtime은 보존한다.

## 사이드바 (After)

```text
전략·후보
 ├─ 전략 관리
 ├─ 후보 관리
 ├─ AI 전략 설정
 ├─ 전략 검증
 └─ 고급 관리
```

세부 화면은 Workspace 상단 Tab으로 기존 route에 진입한다. Bookmark URL은 404 없이 유지된다.

## 역할 분리

| 화면 | 역할 |
|------|------|
| 전략·후보 / AI 전략 설정 | 전역 전략·AI 시스템 설정 (Provider/Prompt/Policy) |
| 업비트 자동매매 설정 | UBA별 LIVE Portfolio 운영 정책 |

## Upbit 격리

UBA1380 FULL_MARKET_PORTFOLIO / LIVE / ARM / Position Slot 은 이 STEP에서 읽기만 한다. mutation·restart 없음.

## 구현 파일

- `frontend/src/config/menu.tsx` — leaf 5개 + `matchPaths`
- `frontend/src/components/layout/SidebarMenu.tsx` — matchPaths 선택
- `frontend/src/features/admin/strategy-candidate/*` — Workspace config + chrome
- `frontend/src/app/(admin)/layout.tsx` — chrome 연결
