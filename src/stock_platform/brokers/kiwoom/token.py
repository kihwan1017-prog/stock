from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True, slots=True)
class KiwoomAccessToken:
    """In-memory Kiwoom access token."""

    value: str
    token_type: str
    expires_at: datetime

    def is_expiring(
        self,
        within: timedelta = timedelta(minutes=5),
    ) -> bool:
        now = datetime.now(timezone.utc)
        return self.expires_at <= now + within
