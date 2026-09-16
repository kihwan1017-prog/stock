# Secret Rotation Checklist

원문 Secret은 이 문서에 기록하지 않는다.

## 대상

| 유형 | 위치 | Rotation 트리거 |
|------|------|-----------------|
| JWT_SECRET | ops env | 유출 의심·교체 주기 |
| DB_PASSWORD | ops env / PG | 유출·인원 변경 |
| KIWOOM APP/SECRET | Vault / env | 유출·키 재발급 |
| UPBIT keys | Vault | 동일 |
| TELEGRAM_BOT_TOKEN | ops env | Git/로그 노출 시 **필수** |
| TELEGRAM_WEBHOOK_SECRET | ops env | 미설정·유출 시 |
| Broker Vault master key | secrets | 키 분실·교체 |

## 절차

1. 새 Secret 발급 (외부 콘솔)
2. ops env / Vault 갱신 (백업 후)
3. 서비스 재시작
4. Health · 로그인 · Broker 연결 확인
5. 구 Secret 폐기
6. Audit에 rotation 사실만 기록 (값 금지)

## STEP 8-5-22

- 운영 `TELEGRAM_WEBHOOK_SECRET` **설정 완료** (길이 43, 원문 미기록)
- Git tracked Critical Secret: 0
- Rotation 권고: Bot Token은 이력 노출 시에만 (현재 webhook은 신규 발급)
