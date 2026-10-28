"""OpenAI-compatible chat client for a local model (Ollama or similar)."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from benchlib.scoring import estimate_tokens

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "qwen2.5:3b"


@dataclass(frozen=True)
class Completion:
    text: str
    latency_s: float
    prompt_tokens: int
    completion_tokens: int
    token_source: str


class ChatClient:
    """Chat completions against an OpenAI-compatible endpoint. Temperature is 0."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        api_key: str = "ollama",
        seed: int = 1729,
        timeout_s: float = 120.0,
    ) -> None:
        self.model = model
        self.seed = seed
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def close(self) -> None:
        self._client.close()

    def complete(self, messages: list[dict[str, str]]) -> Completion:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "seed": self.seed,
        }
        started = time.perf_counter()
        response = self._client.post("/chat/completions", json=payload)
        latency_s = time.perf_counter() - started
        response.raise_for_status()
        body = response.json()
        text = body["choices"][0]["message"]["content"] or ""
        usage = body.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
            source = "api"
        else:
            prompt_text = "\n".join(message["content"] for message in messages)
            prompt_tokens = estimate_tokens(prompt_text)
            completion_tokens = estimate_tokens(text)
            source = "estimate"
        return Completion(
            text=text.strip(),
            latency_s=latency_s,
            prompt_tokens=int(prompt_tokens),
            completion_tokens=int(completion_tokens),
            token_source=source,
        )
