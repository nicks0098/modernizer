"""Pluggable LLM backends. The default talks to any OpenAI-compatible server, which includes
Ollama (free, local), llama.cpp's llama-server, LM Studio, vLLM, Groq and OpenRouter."""
from __future__ import annotations

import json
import os
import urllib.request


class LLM:
    def complete(self, system: str, user: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class OpenAICompatLLM(LLM):
    def __init__(self, base_url: str | None = None, model: str | None = None,
                 api_key: str | None = None, timeout: int = 300):
        self.base_url = (base_url or os.getenv("MODERNIZER_LLM_URL", "http://localhost:11434/v1")).rstrip("/")
        self.model = model or os.getenv("MODERNIZER_LLM_MODEL", "qwen2.5-coder:7b")
        self.api_key = api_key or os.getenv("MODERNIZER_LLM_KEY", "")
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        body = json.dumps({
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)["choices"][0]["message"]["content"]


class StaticLLM(LLM):
    """Test double: wraps a function (system, user) -> str."""

    def __init__(self, fn):
        self.fn = fn
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self.fn(system, user)
