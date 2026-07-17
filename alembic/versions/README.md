# Deprecated — Alembic overlay (적용 금지)

이 디렉터리의 migration 파일은 **Alembic revision chain에 포함되지 않습니다**.

- 표준 경로: `database/alembic/versions/`
- 참고용 복사본: `docs/migration-overlays/`

`alembic.ini`는 `database/alembic`만 로드하므로, 이 파일들은 자동 실행되지 않습니다.
새 migration은 `database/alembic/versions/`에만 추가하세요.
