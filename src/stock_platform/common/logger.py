import logging

import structlog

from stock_platform.common.security_mask import structlog_redact_processor
from stock_platform.common.settings import get_settings


def configure_logging() -> None:
    level_name = get_settings().log_level.strip().upper() or "INFO"
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(message)s",
        force=True,
    )
    logging.getLogger().setLevel(level)

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog_redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
    )


logger = structlog.get_logger()
