# UPBIT Full-Market Dynamic LIVE Autotrading

**상태:** `UPBIT_FULL_MARKET_AUTOTRADING_READY_TO_ENABLE`  
**기본 모드:** `FIXED_SYMBOL` (기존 KRW-XRP 고정 전략 유지)  
**Enable:** 관리자 명시 승인 후에만 `FULL_MARKET_AUTO`

REAL 테스트 주문·자동 Enable 금지. UBA1381(KIWOOM) 대상 아님.

---

## 운영 모드

### FIXED_SYMBOL

- Deployment/Strategy 템플릿 심볼(예: KRW-XRP) 고정
- Opportunity Scanner는 SHADOW_ONLY 유지
- LIVE 심볼은 assignment `current_symbol = template_symbol`

### FULL_MARKET_AUTO

```text
UPBIT KRW universe
→ Opportunity Scanner (SHADOW 유지)
→ Ranked candidates
→ LIVE Selection Service (gated)
→ Runtime operational assignment (current_symbol)
→ Warmup / market fresh
→ Strategy signal
→ AI/Risk/LIVE safety
→ BUY → Fill → Position (strategy-owned binding)
→ SL/TP/Trailing EXIT
→ Cooldown → next eligible candidate
```

Deployment 원본 심볼을 15분마다 UPDATE하지 않는다.  
운영 assignment만 교체한다.

---

## 안전 Gate (Fail Closed)

신규 ENTRY 금지 조건 예:

- LIVE/ARM/Unattended/Activation 무효
- Kill / Risk / Conflict / Recovery 실패
- Scanner stale / AI HOLD·BLOCK
- Warmup 미완료 / target switch 미완료
- Strategy position OPEN / open order
- Daily ENTRY limit (EXIT는 verified_exit로 ENTRY quota 미적용)
- Duplicate selection / lease

보호 EXIT는 AI HOLD로 막지 않는 기존 정책을 유지한다.

---

## Admin UI

- AUTO TRADING 요약: MODE / CURRENT TARGET / SCANNER
- Drawer: Dynamic Selection ON/OFF
- Enable 확인 문구: `전체시장 자동선정 모드 시작`
- Disable: `전체시장 자동선정 모드 중지`

---

## API

- `GET /api/v1/admin/autotrading/uba/{id}/full-market`
- `POST .../full-market/enable`
- `POST .../full-market/disable`
- `POST .../full-market/dry-select` (주문 없음)

---

## NEXT_ACTION

관리자 UI에서 UBA1380에 대해:

**ENABLE UBA1380 FULL MARKET AUTO MODE FROM ADMIN UI**
