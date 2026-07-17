from datetime import datetime, time
from zoneinfo import ZoneInfo
KST=ZoneInfo("Asia/Seoul")
class MarketSession:
    def __init__(self, open_time: time=time(9,0), close_time: time=time(15,30)) -> None:
        self.open_time=open_time; self.close_time=close_time
    def is_open(self, now: datetime|None=None) -> bool:
        current=now.astimezone(KST) if now else datetime.now(KST)
        return current.weekday()<5 and self.open_time <= current.time().replace(tzinfo=None) <= self.close_time
