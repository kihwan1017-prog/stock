"""STEP 9-6 — env LIVE 게이트만 true로 전환 (시크릿 미출력)."""

from __future__ import annotations

from pathlib import Path

ENV_PATH = Path(r"E:\StockTrading\secrets\stock-platform.env")
WANTED = {
    "GLOBAL_LIVE_ORDER_ENABLED": "true",
    "UPBIT_LIVE_ORDER_ENABLED": "true",
}


def main() -> None:
    text = ENV_PATH.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    found: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key, _, _value = stripped.partition("=")
        key = key.strip()
        if key in WANTED:
            out.append(f"{key}={WANTED[key]}")
            found.add(key)
        else:
            out.append(line)
    missing = [k for k in WANTED if k not in found]
    if missing:
        out.append("")
        out.append("# STEP 9-6 live order gates")
        for key in missing:
            out.append(f"{key}={WANTED[key]}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    # 검증 — 대상 키만
    vals: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        vals[k.strip()] = v.strip()
    for key in WANTED:
        print(f"{key}={vals.get(key)!r}")
    print(
        "UPBIT_USE_MOCK=",
        vals.get("UPBIT_USE_MOCK"),
        "KIWOOM_LIVE=",
        vals.get("KIWOOM_LIVE_ORDER_ENABLED"),
    )


if __name__ == "__main__":
    main()
