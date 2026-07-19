# 운영 매뉴얼 (Manual)

제품 운영·사용을 위한 매뉴얼 모음입니다.  
**코드에 구현된 기능만** 기술합니다. Admin UI의 Coming Soon 메뉴는 미구현으로 명시합니다.

개발/설계 문서 목차: [../README.md](../README.md)

## 문서 목록

| 문서 | 대상 | 설명 |
|------|------|------|
| [사용자매뉴얼.md](사용자매뉴얼.md) | 운영 사용자 | Admin 웹 사용 (STEP41 범위) |
| [관리자매뉴얼.md](관리자매뉴얼.md) | 관리자 | 구조·환경·스케줄러·연동 |
| [설치매뉴얼.md](설치매뉴얼.md) | 설치 담당 | Windows 11 설치 |
| [운영매뉴얼.md](운영매뉴얼.md) | 운영자 | 기동·종료·스케줄·백업 개요 |
| [API사용매뉴얼.md](API사용매뉴얼.md) | 개발·운영 | API 그룹·권한·OpenAPI |
| [DB관리매뉴얼.md](DB관리매뉴얼.md) | DBA·개발 | Schema·Alembic |
| [백업복구매뉴얼.md](백업복구매뉴얼.md) | 운영 | PostgreSQL 백업·복구 |
| [장애대응매뉴얼.md](장애대응매뉴얼.md) | 운영 | 장애 징후·복구 |
| [FAQ.md](FAQ.md) | 공통 | 자주 묻는 질문 |
| [CHANGELOG_GUIDE.md](CHANGELOG_GUIDE.md) | 공통 | 변경 이력 보는 법 |
| [VERIFICATION.md](VERIFICATION.md) | 공통 | 작성 검증 메모 |

## 빠른 시작

1. [설치매뉴얼.md](설치매뉴얼.md)
2. Backend `http://127.0.0.1:8000/docs`
3. Admin `http://localhost:3000` → [사용자매뉴얼.md](사용자매뉴얼.md)
4. 일일 점검: [../trading/OPERATIONS_RUNBOOK.md](../trading/OPERATIONS_RUNBOOK.md)

## 구현 범위 요약 (v1.0 + STEP41)

| 영역 | 상태 |
|------|------|
| FastAPI Backend | 구현됨 |
| Admin Frontend Dashboard | STEP41 골격 (health 연결) |
| Admin 기타 메뉴 | Coming Soon (미구현 UI) |
| JWT 로그인 | 미구현 (`AUTH_MODE=disabled` 개발 입장) |
| Docker / Redis | 사용하지 않음 |
