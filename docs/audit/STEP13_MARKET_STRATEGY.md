# STEP 13 — 시장 데이터·지표·전략 검증

## 현황
키움/업비트 일봉 collector·parser·sync 테스트 존재. 지표(MA/RSI 등)·후보 파이프라인은 기존 모듈·테스트로 동작.

## 갭(문서화)
수정주가 전용 검증, look-ahead bias 자동화 테스트 보강, 업비트 list_markets 단위 테스트.

## 조치
본 STEP에서 대규모 재작성 없이 회귀 테스트 유지. Upbit sync 인증 강화(STEP11)로 수집 엔드포인트 보호.

## 권장 커밋
(문서만) docs(step13): record market-strategy audit findings
