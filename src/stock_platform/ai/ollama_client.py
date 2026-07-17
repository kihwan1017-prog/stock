import json, httpx
class OllamaClient:
    def __init__(self, base_url:str, model:str, timeout_seconds:float=60)->None:
        self.base_url=base_url.rstrip('/'); self.model=model; self.timeout_seconds=timeout_seconds
    async def generate_json(self,prompt:str)->dict:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response=await client.post(f"{self.base_url}/api/generate",json={"model":self.model,"prompt":prompt,"stream":False,"format":"json"})
            response.raise_for_status()
        return json.loads(response.json().get("response","{}"))
