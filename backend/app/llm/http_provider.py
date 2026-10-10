import httpx
from backend.app.llm.interface import LLMProvider


class JsonHttpProvider(LLMProvider):
    """Generic JSON-over-HTTP adapter; it does not encode vendor-specific business logic."""
    def __init__(self, endpoint: str, api_key: str, timeout: float = 15.0):
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = timeout

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"system_prompt": system_prompt, "user_prompt": user_prompt,
                      "response_format": "json"})
            response.raise_for_status()
        payload = response.json()
        content = payload.get("content") or payload.get("output")
        if not isinstance(content, str):
            raise ValueError("LLM provider returned no text content")
        return content
