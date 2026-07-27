"""STEP 8-5-21 — 운영 env RC 안전값 정렬 (Secret 원문 미출력)."""

from __future__ import annotations

from pathlib import Path

ENV_PATH = Path(r"E:\StockTrading\secrets\stock-platform.env")

WANTED = {
    "GLOBAL_LIVE_ORDER_ENABLED": "false",
    "KIWOOM_USE_MOCK": "true",
    "KIWOOM_LIVE_ORDER_ENABLED": "false",
    "UPBIT_LIVE_ORDER_ENABLED": "false",
    "DEBUG": "false",
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
        out.append("# STEP 8-5-21 RC safety defaults")
        for key in missing:
            out.append(f"{key}={WANTED[key]}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("updated_keys", sorted(WANTED))
    print("added_keys", missing)
    # 검증 마스킹
    vals: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        vals[k.strip()] = v.strip()
    for key in list(WANTED) + ["APP_ENV"]:
        print(f"{key}={vals.get(key, '<MISSING>')!r}")


if __name__ == "__main__":
    main()
