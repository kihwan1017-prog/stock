# STEP 16 — 프런트엔드 미구현 기능

## 구현됨/연결됨
Kill Switch UI(admin), 계좌·프로필·워치리스트·로그인 RBAC, 메뉴 분리.

## 의도적 미구현(노출 최소화·문서화)
- Portfolio Optimize / Backup Restore UI: 백엔드 ops 우선
- 실시간 SSE 시세 전면: 별도 WS 제품화 필요
- 자동매매 일정 CRUD 고도화: scheduler-admin API 수동 실행만

## 수정
roles/LoginForm 테스트를 현재 보안 계약(forbidden, next undefined)에 맞춤.

## 권장 커밋
	est(step16): align frontend auth tests with RBAC contract
