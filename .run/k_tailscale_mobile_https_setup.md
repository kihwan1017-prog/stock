# Tailscale Mobile HTTPS Serve

FINAL_VERDICT: **TAILSCALE_MOBILE_HTTPS_READY**

## MOBILE_ACCESS_URL

**https://kikicom.tail3bf7b2.ts.net/mobile**

## Tailscale

| Item | Value |
|------|--------|
| Version | 1.102.3 |
| Device | kikicom |
| Tailscale IPv4 | 100.79.126.15 |
| MagicDNS | kikicom.tail3bf7b2.ts.net |
| Service | Running / Automatic |
| Peer phone | s23 (android) seen on tailnet |

## Serve

- ENABLED / BACKGROUND: YES
- TARGET: `http://127.0.0.1:3000`
- HTTPS: `https://kikicom.tail3bf7b2.ts.net`
- TAILNET_ONLY: YES
- FUNNEL: **OFF**

## Security

- Port forwarding: NO
- Public internet / Funnel: NO
- Backend `:8000` / Ollama `:11434` loopback only
- Auth required (app login); Tailscale ≠ stock-platform auth bypass
- Backend direct TS IP:8000 unreachable

## Tests (mini-PC)

- `/` `/mobile` `/manifest.webmanifest` `/sw-mobile.js` → 200
- overview via HTTPS same-origin proxy → 200 (auth)
- overview latency AUTH P50≈36ms / P95≈50ms

## Phone / LTE

PHYSICAL_PHONE_ACTION_REQUIRED = YES  
PHYSICAL_LTE_VERIFY_REQUIRED = YES  

1. Phone Tailscale ON (same Tailnet)  
2. Wi-Fi OFF → LTE/5G  
3. Open HTTPS URL above → admin login → `/mobile`  
4. Optional PWA install  

## Ops script

`ops/dev/setup-tailscale-mobile-serve.ps1` — install/login/serve helper (no Funnel).

## NEXT_ACTION

PHYSICAL_PHONE_LTE_PWA_VERIFY

- GIT_COMMIT: b1f980c
