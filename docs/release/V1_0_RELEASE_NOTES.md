# v1.0 Release Notes (RC)

## 요약

v1.0 RC는 계좌 신원(UBA/Paper) 고정, Snapshot Freshness, EOD Settlement, Persistent Scheduler, LIVE Fail Closed를 포함한 자동매매 운영 후보 빌드이다.

## 이번 RC에 포함된 핵심 변경 (8-5-x)

- Account Identity Hardening (LIVE=UBA, Paper=paper_account_id)
- Legacy account_number 운영 경로 제거
- Snapshot UBA binding / ACTIVE 1건
- EOD Settlement · Recovery · Ambiguous Resolver
- **8-5-20:** `broker_pending_order` UBA FK·Unique, LIVE Health CRITICAL 주문 차단

## 기본 안전 모드

- Live 주문 플래그 기본 OFF
- Kiwoom Mock 기본 ON
- Health CRITICAL → LIVE 신규 주문 거부 (`SYSTEM_HEALTH_CRITICAL`)

## 알려진 제한

- 공개망 직접 노출 금지 (VPN/ACL)
- 고객 Live 전 Known Critical(SEC/TRD) 해소 필요
- Position Limit Admin UI는 v1.1
- 빈 DB 복구 검증은 DBA 권한으로 별도 수행

## Alembic

Head: `h1b2c3d4e5f6`
