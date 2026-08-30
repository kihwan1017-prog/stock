# Tailscale — Stock Platform Service (`stock.tail3bf7b2.ts.net`)

**목적:** LottoLab(`lottolab.tail3bf7b2.ts.net`)을 유지한 채, Stock Frontend만 별도 MagicDNS로 노출한다.  
**WRK:** `WRK-20260830-STOCK-PLATFORM-FINAL-PRODUCTION-HARDENING-V1`  
**Funnel(공개 인터넷) 사용 금지.** Tailnet 전용.

---

## 현재 PC 상태 (2026-08-30 점검)

| 항목 | 값 |
|------|-----|
| Tailscale | 1.102.3 |
| Device MagicDNS | `lottolab.tail3bf7b2.ts.net` |
| Tailscale IP | `100.79.126.15` |
| Node tags | **없음** (`Tags=None`) |
| Classic Serve | `https://lottolab…` → `http://127.0.0.1:8765` (LottoLab) |
| Stock local FE | `http://127.0.0.1:3000` (`0.0.0.0` bind) |
| Stock local BE | `http://127.0.0.1:8000` (Next `/api` rewrite) |

`tailscale serve --service=svc:stock …` 실행 시:

```text
service hosts must be tagged nodes
```

→ **Admin Console에서 노드 태그 + Service 정의/승인이 필요**하다.  
이 PC hostname을 `stock`으로 rename 하면 `lottolab` DNS가 깨지므로 **금지**.

---

## HUMAN_ACTION_REQUIRED — 한 번에 할 일

### 1) 노드에 태그 부여

1. [Tailscale Admin Console](https://login.tailscale.com/admin/machines) 열기  
2. 이 Windows 기기(`lottolab` / `kikicom`) 선택  
3. **Tags**에 예: `tag:server` (또는 `tag:stock-host`) 추가  
4. ACL에 해당 태그 허용이 없으면 정책에 추가

### 2) Service 정의

1. Admin → **Services** → **Define a Service**  
2. Name: `stock` (MagicDNS → `stock.<tailnet>.ts.net`)  
3. Ports: `tcp:443`  
4. 저장 후, 이 기기를 Service host로 **Approve**

### 3) 로컬 advertise (승인 후 PC에서)

```powershell
# LottoLab classic serve는 건드리지 않음 (reset 금지)
tailscale serve --service=svc:stock --https=443 http://127.0.0.1:3000
tailscale serve status
```

검증:

```text
https://stock.tail3bf7b2.ts.net/login
https://lottolab.tail3bf7b2.ts.net   # 기존 유지
```

---

## 앱 구성 원칙

- **Frontend만 expose** (3000). Backend(8000)·PostgreSQL(5432)은 Tailscale Service로 올리지 않는다.  
- 브라우저는 same-origin `/api` → Next rewrite → `127.0.0.1:8000`.  
- 기존 JWT 로그인 유지. CORS `*` / Funnel / 인증 우회 금지.  
- 임시 접근(Service 승인 전): Tailnet 내부 `http://100.79.126.15:3000` (HTTPS MagicDNS 아님).

---

## Persistence / 재부팅

- Tailscale Serve/Service 설정은 Tailscale 측에 persist.  
- Stock 앱은 canonical `ops/dev/start-dev.ps1` (또는 운영 NSSM)로 기동.  
- `tailscale serve reset` 은 LottoLab까지 지우므로 **사용 금지**.

---

## 회귀 체크리스트

- [ ] `https://lottolab.tail3bf7b2.ts.net` 200  
- [ ] `https://stock.tail3bf7b2.ts.net/login` 200  
- [ ] Stock 로그인 → `/api/v1/auth/me` → Admin Dashboard  
- [ ] 8000/5432 인터넷 미노출 · Funnel OFF  
