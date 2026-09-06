# UPBIT Operator Authorization (24/48/72H) — Activation/ARM lease policy

**SoT:** `operation.live_unattended_authorization` (= Operator Authorization)  
**관련 코드:** `operator_authorization_policy.py`, `live_unattended_authorization_service.py`, `safe_auto_recovery/classification.py`

## 권한 계층

```
OPERATOR AUTHORIZATION (unattended lease horizon: 24|48|72h)
        ↓
ACTIVATION (live_trading_transition, ≤ authorization)
        ↓
ARM (≤ activation − safety margin, default 60s)
        ↓
LIVE EXECUTION
```

## Invariants

- `ARM_EXPIRES_AT <= ACTIVATION_EXPIRES_AT - SAFETY_MARGIN`
- `ACTIVATION_EXPIRES_AT <= AUTHORIZATION_EXPIRES_AT`
- 무기한 승인 금지. UPBIT 승인기간은 **24 / 48 / 72**만.

## Auto renewal

Authorization ACTIVE + `auto_renew_enabled` + safety precheck PASS일 때만
Activation successor / ARM renew 허용 (`renew_due_for_uba` / horizon auto-renew).

## Fail-closed on authorization expiry

- 오픈 포지션 있음: `PROTECTIVE_EXIT_ONLY` (ENTRY OFF, protective EXIT 유지)
- 포지션 없음: LIVE/ARM OFF full fail-closed

## Safe auto-recovery

- Class A/B: **Operator Authorization ACTIVE** 필수
- Class C / Circuit Open / Kill Switch: 자동복구 금지 (Authorization보다 우선)

## 운영 주의

Cursor/에이전트는 코드 배포 후 **실계좌 Authorization을 임의 생성·ON 하지 않는다.**  
ChatGPT 검토 후 별도 승인으로 적용.

관련: [UPBIT_UBA1380_24X7_SESSION_RENEWAL.md](UPBIT_UBA1380_24X7_SESSION_RENEWAL.md)
