from datetime import datetime, timezone
from uuid import uuid4

class ClientOrderIdGenerator:
    @staticmethod
    def generate(prefix: str = "ORD") -> str:
        now = datetime.now(timezone.utc)
        return f"{prefix}-{now:%Y%m%d%H%M%S}-{uuid4().hex[:10].upper()}"
