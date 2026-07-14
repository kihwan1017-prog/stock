from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


from stock_platform.scheduler.automatic import (
    AutomaticScheduler,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one automatic scheduler job now."
    )
    parser.add_argument(
        "job_name",
        choices=[
            "candidate_screening",
            "ai_orchestration",
            "position_planning",
        ],
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    result = await AutomaticScheduler().run_job_now(
        args.job_name
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
