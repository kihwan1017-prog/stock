"""호스트 리소스 관측 — psutil 선택, 없으면 stdlib 폴백 (STEP61)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


def build_resource_monitoring(
    *,
    disk_path: str | None = None,
) -> dict[str, Any]:
    path = disk_path or str(Path.cwd())
    disk: dict[str, Any]
    try:
        usage = shutil.disk_usage(path)
        disk = {
            "path": path,
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_percent": round(
                (usage.used / usage.total) * 100.0, 2
            )
            if usage.total
            else None,
        }
    except Exception as exc:
        disk = {"status": "UNAVAILABLE", "message": str(exc)[:120]}

    cpu: dict[str, Any] = {
        "logical_count": os.cpu_count(),
    }
    memory: dict[str, Any] = {}
    network: dict[str, Any] = {"status": "NOT_COLLECTED"}

    try:
        import psutil  # type: ignore

        cpu["percent"] = psutil.cpu_percent(interval=0.0)
        mem = psutil.virtual_memory()
        memory = {
            "total_bytes": mem.total,
            "available_bytes": mem.available,
            "used_percent": mem.percent,
            "source": "psutil",
        }
        net = psutil.net_io_counters()
        network = {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "source": "psutil",
        }
        cpu["source"] = "psutil"
    except Exception:
        memory = {
            "source": "unavailable",
            "message": "psutil not installed",
        }
        cpu["source"] = "stdlib"

    return {
        "cpu": cpu,
        "memory": memory,
        "disk": disk,
        "network": network,
    }
