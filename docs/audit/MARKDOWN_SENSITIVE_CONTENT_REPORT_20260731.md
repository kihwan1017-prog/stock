# MARKDOWN SENSITIVE CONTENT REPORT — 2026-07-31

**PHASE 3A — 수정·삭제·값 출력 없음.**  
탐지 시 **파일 경로 + 패턴 종류 + 건수만** 기록. 매칭 문자열·시크릿 값은 **보고하지 않음**.

---

## 1. 스캔 패턴

| ID | 설명 |
|----|------|
| api_key_assign | API key = quoted value |
| secret_assign | password/secret = quoted |
| token_assign | long token assignment |
| jwt_like | eyJ… JWT shape |
| telegram_bot | botNNNN:token |
| aws_key | AKIA… |
| private_key_block | PEM private key |
| secrets_env_path | `secrets\…\.env` 경로 관례 |
| pg_url_creds | postgresql://user:pass@ |
| account_digits_near_label | 계좌/account 인근 긴 숫자 |
| token_prefix | sk-/ghp_/xoxb- |
| user_abs_path | `X:\Users\<name>\` |

---

## 2. 고위험 패턴 결과

| 패턴군 | 히트 파일 수 |
|--------|--------------|
| api_key_assign / secret_assign / token_assign / jwt_like / telegram_bot / aws_key / private_key_block / token_prefix | **0** |
| user_abs_path | **0** |

→ 문서에 **실제 시크릿 값으로 보이는 할당**은 본 스캔에서 미검출.

---

## 3. 저·중 위험 (경로·문서 관례)

| 패턴 | 파일 수 | 권장 |
|------|---------|------|
| secrets_env_path | 다수 (~20+) | 운영 문서의 **경로 예시** — 값 아님. Archive 시 유지 가능. 필요 시 3B+에서 `REDACT_BEFORE_ARCHIVE`는 **경로를 placeholder로** (승인 후) |
| pg_url_creds | 1 | `docs/audit/README_AUDIT_CODE_20260728.md` → **MANUAL_REVIEW** (값 노출 여부 육안) |
| account_digits_near_label | 3 | 이미 `docs/archive/steps/README_STEP29_*.md` — **MANUAL_REVIEW** · 이동 추가 불필요 |

### secrets_env_path 대표 경로 (값 없음)

- 루트: `INSTALL.md`, `OPERATIONS.md`, `README.md`, `RECOVERY.md`, `SECURITY.md`, `README_STEP60.md`
- Active: `docs/deployment/CONFIGURATION.md`, `INSTALL.md`, `DEPLOY_v1.1.0.md`, manual 일부
- Historical: `docs/archive/steps/README_STEP17/18/19/22/25…`

Active deployment/manual은 **Archive 대상 아님** — 민감 플래그만 기록.

---

## 4. 파일별 권고 (Archive 후보만)

| Source | Flag | Recommended |
|--------|------|-------------|
| INSTALL.md 등 루트 ops | secrets_env_path | MOVE 가능 · REDACT optional |
| docs/audit/README_AUDIT_CODE_20260728.md | pg_url_creds | MANUAL_REVIEW → 통과 시 archive/audits |
| archive STEP29_* | account_digits | KEEP_IN_PLACE · DELETE_AFTER_SECURE_REVIEW **비권장** (이력) |

**DELETE_AFTER_SECURE_REVIEW:** 본 PHASE에서 **제안하지 않음** (값 미확인·이력 가치).

---

## 5. 결론

- 민감 **값** 유출 증거: 스캔상 **없음**  
- 위험: 주로 **경로 예시** 및 **수동 검토 1+3파일**  
- PHASE 3B 이동 시에도 시크릿을 새 경로로 **복사 출력하지 말 것**
