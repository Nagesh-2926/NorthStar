"""Google Gemini GenerateContent adapter using a server-side API key."""

import httpx

from backend.app.llm.interface import LLMProvider

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, timeout: float = 15.0):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = httpx.post(
            f"{GEMINI_API_BASE}/{self.model}:generateContent",
            headers={"x-goog-api-key": self.api_key},
            json={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("Gemini returned no candidate content")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part["text"] for part in parts
                       if isinstance(part, dict) and isinstance(part.get("text"), str))
        if not text.strip():
            raise ValueError("Gemini returned empty content")
        return text
