# AI_SECURITY_RULE

**최종 갱신:** 2026-07-31

---

- **Authentication:** JWT + refresh. production에서 secret 미설정 시 기동 실패.  
- **Authorization:** ADMIN/USER · API key admin. RBAC DB 재검증 패턴 존중.  
- **Ownership / IDOR:** account·strategy·UBA 소유권 검사 우회 금지.  
- **Credential Vault:** 키·시크릿 평문 로그/응답/문서 금지. Masking 유지.  
- **Rate Limit:** Upbit 등 브로커·API 한도 존중.  
- **LIVE API 보호:** 다단계 gate · 기본 OFF · audit.  
- **Audit:** 민감 변경·LIVE 이벤트 기록.  
- 상세 ops: 루트 `SECURITY.md`, `docs/security/`.
