# -*- coding: utf-8 -*-
"""READ-ONLY pre/post snapshot helpers for Ollama role-model prod reload verify."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000"


def load_token() -> str:
    sess = json.loads(
        (ROOT / ".run" / "_auth_browser_session.json").read_text(encoding="utf-8")
    )
    return str(sess.get("access_token") or "")


def get_json(path: str, token: str, timeout: float = 25.0) -> dict[str, Any]:
    req = urllib.request.Request(
        API + path,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
            return {"http": resp.status, "body": body}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="ignore")[:500]
        try:
            body = json.loads(raw)
        except Exception:  # noqa: BLE001
            body = raw
        return {"http": exc.code, "body": body}
    except Exception as exc:  # noqa: BLE001
        return {"http": None, "error": type(exc).__name__, "message": str(exc)[:200]}


def pick_uba_fields(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"raw_type": type(body).__name__}
    keys = [
        "live_order_enabled",
        "live_armed",
        "arm_expires_at",
        "connection_status",
        "runtime_status",
        "runtime_running",
        "runner_status",
        "runner_running",
        "worker_status",
        "worker_running",
        "scanner_status",
        "exit_monitor_status",
        "feed_status",
        "market_feed_status",
        "overall_status",
        "ready",
        "blocking_reasons",
        "broker_code",
        "mode",
        "is_running",
        "running",
        "status",
    ]
    out: dict[str, Any] = {}
    for k in keys:
        if k in body:
            out[k] = body[k]
    # nested common shapes
    for nest in ("live", "runtime", "runner", "worker", "scanner", "exit", "feed", "ops"):
        if isinstance(body.get(nest), dict):
            out[nest] = {
                kk: vv
                for kk, vv in body[nest].items()
                if kk
                in {
                    "status",
                    "running",
                    "enabled",
                    "live_armed",
                    "live_order_enabled",
                    "connected",
                    "mode",
                }
            }
    out["top_keys"] = sorted(body.keys())[:40]
    return out


def snapshot(label: str) -> dict[str, Any]:
    token = load_token()
    paths = {
        "ollama_status": "/api/v1/ollama/status",
        "ollama_models": "/api/v1/ollama/models",
        "ollama_role_models": "/api/v1/ollama/role-models",
        "uba1380_readiness": "/api/v1/admin/autotrading/uba/1380/readiness",
        "uba1380_status": "/api/v1/admin/autotrading/uba/1380/status",
        "uba1380_ops": "/api/v1/admin/autotrading/uba/1380/ops-status",
        "uba1380_live": "/api/v1/admin/live-order/accounts/1380",
        "uba1381_readiness": "/api/v1/admin/autotrading/uba/1381/readiness",
        "uba1381_status": "/api/v1/admin/autotrading/uba/1381/status",
        "uba1381_ops": "/api/v1/admin/autotrading/uba/1381/ops-status",
        "uba1381_live": "/api/v1/admin/live-order/accounts/1381",
        "kiwoom_market_rt": "/api/v1/admin/autotrading/kiwoom/market-realtime/status",
        "dual_llm": "/api/v1/admin/upbit/dual-llm/status",
    }
    raw: dict[str, Any] = {}
    summary: dict[str, Any] = {"label": label}
    for name, path in paths.items():
        res = get_json(path, token)
        raw[name] = res
        body = res.get("body")
        if name.startswith("uba") or name.startswith("kiwoom"):
            summary[name] = {
                "http": res.get("http"),
                **pick_uba_fields(body if isinstance(body, dict) else {}),
            }
        elif name == "ollama_role_models" and isinstance(body, dict):
            roles = body.get("roles") or {}
            summary[name] = {
                "http": res.get("http"),
                "ANALYSIS": (roles.get("analysis") or {}).get("RUNTIME_RESOLVED_VALUE"),
                "TRADING": (roles.get("trading") or {}).get("RUNTIME_RESOLVED_VALUE"),
                "TEACHER": (roles.get("teacher") or {}).get("RUNTIME_RESOLVED_VALUE"),
                "FALLBACK": (roles.get("fallback") or {}).get("RUNTIME_RESOLVED_VALUE"),
                "TRADING_LLM_MODE": body.get("TRADING_LLM_MODE"),
                "TRADING_LLM_REAL_GATE": body.get("TRADING_LLM_REAL_GATE"),
                "installed_model_count": body.get("installed_model_count"),
            }
        elif name == "ollama_models" and isinstance(body, dict):
            models = body.get("models") or []
            names = [m.get("name") for m in models if isinstance(m, dict)]
            summary[name] = {
                "http": res.get("http"),
                "count": len(names),
                "names": names,
            }
        elif name == "ollama_status":
            summary[name] = {
                "http": res.get("http"),
                "body": body if isinstance(body, dict) else str(body)[:120],
            }
        elif name == "dual_llm" and isinstance(body, dict):
            summary[name] = {
                "http": res.get("http"),
                "ANALYSIS_LLM_MODEL": body.get("ANALYSIS_LLM_MODEL"),
                "TRADING_LLM_MODEL": body.get("TRADING_LLM_MODEL"),
                "TEACHER_LLM_MODEL": body.get("TEACHER_LLM_MODEL"),
                "REFERENCE_MODEL": body.get("REFERENCE_MODEL"),
                "TRADING_LLM_MODE": body.get("TRADING_LLM_MODE"),
            }
    return {"summary": summary, "raw_http": {k: v.get("http") for k, v in raw.items()}, "raw": raw}


if __name__ == "__main__":
    import sys

    label = sys.argv[1] if len(sys.argv) > 1 else "snap"
    out = ROOT / ".run" / f"_ollama_reload_{label}.json"
    data = snapshot(label)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
    print("WROTE", out)
