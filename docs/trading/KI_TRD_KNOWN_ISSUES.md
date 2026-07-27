# KI-TRD Known Issues

| ID | 제목 | 코드 상태 | LIVE 영향 | 처리 |
|----|------|-----------|-----------|------|
| KI-TRD-01 | Outbox Paper 고정 | **MITIGATED** | 낮음 | 종결 |
| KI-TRD-02 | Outbox PROCESSING reclaim 레이스 | **FIXED** (8-5-22 Fencing) | 낮음 | [KI_TRD_02_OUTBOX_FENCING.md](KI_TRD_02_OUTBOX_FENCING.md) |
| KI-TRD-03 | Exit monitor skip_risk | **MITIGATED** | 낮음 | 종결 |
| KI-TRD-04 | account_id=1 하드코딩 | **MITIGATED** | Paper 한정 | 종결 |

소액 LIVE Critical(TRD): **0** (코드). Official Restore **PASS** · DB Release Blocker **0**.
