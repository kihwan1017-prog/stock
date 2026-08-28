# Admin UX/IA Full Redesign (WRK-008)

**FINAL_VERDICT:** ADMIN_UX_IA_REDESIGN_IMPLEMENTED  
**WORK_ID:** WRK-20260829-008-ADMIN-UX-IA-FULL-REDESIGN  
**BASE_COMMIT:** 4fabeb9  
**RESULT_COMMIT:** 469829f  
**INVENTORY:** WRK-005 `.run/k_current_full_menu_inventory.*` 재사용 (재 inventory 없음)

## Root cause

기능 중심 IA로 인해 운영 정보가 여러 화면에 중복되고 기술 상태가 사용자 핵심 정보보다 우선 노출됨.

## After menu tree

```
대시보드
자동매매
 ├─ 업비트
 ├─ 키움
 ├─ 주문·체결
 ├─ 보유자산·손익
 ├─ 일일 운영보고
 └─ 알림
분석
 ├─ 전략·후보
 ├─ 시장 분석
 ├─ 시장 데이터
 ├─ 뉴스·공시
 ├─ AI 분석
 └─ 연구 데이터
설정
 ├─ 계좌
 ├─ 리스크
 └─ AI 설정
운영·안전
 ├─ 안전 제어
 ├─ 장애·복구
 └─ 시스템 상태
고급 관리
 ├─ 프로세스·버전
 ├─ LLM 학습센터
 ├─ 전략 검증
 ├─ 스케줄·배치
 ├─ 로그·감사
 ├─ 데이터·API
 ├─ 환경 설정
 ├─ AI 인프라
 └─ 문서
```

## Primary owners

| Information | PRIMARY |
|-------------|---------|
| Accounts / LIVE/ARM | `/admin/accounts` |
| Portfolio | `/admin/portfolio` |
| Orders | `/admin/orders` |
| Upbit runtime | `/admin/autotrading/upbit` |
| Kiwoom runtime | `/admin/autotrading/kiwoom` |
| Risk | `/admin/risk` |
| Daily report | `/admin/autotrading/report` |
| Notifications | `/admin/notifications` |
| System health | `/admin/monitoring` |

## Mobile

Bottom nav: **홈 · 자동매매 · 주문 · 포지션 · 알림** (`/mobile/autotrading` 추가)

## Tests

- `npm run check:antd-compat` PASS  
- `tsc --noEmit` PASS  
- focused vitest 42 PASS  

## Safety

REAL/strategy/risk/portfolio/LIVE-ARM 변경 없음. Backend restart 0.

## Evidence JSON

`.run/k_admin_ux_ia_full_redesign.json`
