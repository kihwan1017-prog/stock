# `.run/` — runtime evidence (not source docs)

이 디렉터리는 **운영·검증 산출물** 전용이다. Canonical 제품 문서가 아니다.

## Policy

- WRK evidence: `k_<topic>.json` (필요 시 md 1개)
- 상세 작업 이력 SoT: `operation.ai_development_work_history`
- Git: 기본적으로 **ignore** (이 README만 추적)
- 장기 보관 권장 경로(정책만): `E:\StockTrading\evidence\stock-platform\YYYY\MM`  
  (강제 이동은 별도 승인)

## Layout (optional)

```text
.run/
  README.md          # tracked
  evidence/          # preferred for new dumps
  temp/              # disposable probes
```

기존 스크립트가 `.run/` 루트 경로를 쓰는 경우 **대규모 경로 변경하지 않는다.**  
호환을 위해 루트에 파일을 둘 수 있다.
