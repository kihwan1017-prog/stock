import httpx
class NotificationService:
    def __init__(self, telegram_bot_token:str|None=None, telegram_chat_id:str|None=None, discord_webhook_url:str|None=None)->None:
        self.telegram_bot_token=telegram_bot_token; self.telegram_chat_id=telegram_chat_id; self.discord_webhook_url=discord_webhook_url
    async def send(self,message:str)->None:
        async with httpx.AsyncClient(timeout=15) as client:
            if self.telegram_bot_token and self.telegram_chat_id:
                await client.post(f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage",json={"chat_id":self.telegram_chat_id,"text":message})
            if self.discord_webhook_url:
                await client.post(self.discord_webhook_url,json={"content":message})
