# STEP 19 — 불필요한 파일 정리

## .gitignore
이미 __pycache__, .coverage, .env, .env.* 포함. !.env.example 예외 유지.

## 조치 권고(삭제 승인 대기)
- 루트 .env.example-- → 정식 .env.example로 정리 후 중복 제거
- 루트 구형 README_AUDIT_*.md → docs/archive/obsolete/ 이동(기존 규칙)

본 STEP에서 보안 파일 강제 삭제는 하지 않음.

## 권장 커밋
chore(step19): document cleanup targets without destructive deletes
