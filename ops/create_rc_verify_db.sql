-- STEP 8-5-21 — 검증용 빈 DB 생성 (DBA/슈퍼유저 전용)
-- 사용: psql -U postgres -f ops/create_rc_verify_db.sql
-- 운영 DB를 삭제·초기화하지 않는다.

SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'stock_platform_rc_verify'
  AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS stock_platform_rc_verify;
CREATE DATABASE stock_platform_rc_verify
  WITH OWNER = CURRENT_USER
       ENCODING = 'UTF8'
       TEMPLATE = template0;

-- 앱 역할에 연결·스키마 생성 권한 (역할명은 환경에 맞게 수정)
-- GRANT CONNECT ON DATABASE stock_platform_rc_verify TO stock_app;
-- GRANT CREATE ON DATABASE stock_platform_rc_verify TO stock_app;
