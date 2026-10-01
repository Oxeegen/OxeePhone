"""Small JSON chat helper for the org's analysis model (OpenAI-compatible)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx


def extract_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("the model did not answer with JSON")
    return json.loads(text[start : end + 1])


RETRY_DELAYS = (3.0, 8.0, 20.0)


async def chat_json(
    model: dict,
    system: str,
    payload: Any,
    *,
    max_tokens: int = 2000,
    temperature: float = 0.2,
    timeout: float = 120.0,
) -> dict:
    """Ask ``model`` ({base_url, api_key, model}) and parse its JSON answer."""
    headers = (
        {"Authorization": f"Bearer {model['api_key']}"} if model.get("api_key") else {}
    )
    body = {
        "model": model["model"],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    payload
                    if isinstance(payload, str)
                    else json.dumps(payload, ensure_ascii=False, default=str)
                ),
            },
        ],
        # Reasoning models (Qwen3 on vLLM) would otherwise think away the budget.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    url = f"{model['base_url'].rstrip('/')}/chat/completions"
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        for attempt in range(len(RETRY_DELAYS) + 1):
            response = await client.post(url, headers=headers, json=body)
            if response.status_code == 400 and "chat_template_kwargs" in response.text:
                body.pop("chat_template_kwargs")
                response = await client.post(url, headers=headers, json=body)
            # Gateways rate-limit bursts (nginx 503) and busy servers say 429.
            if response.status_code not in (429, 502, 503) or attempt == len(
                RETRY_DELAYS
            ):
                break
            await asyncio.sleep(RETRY_DELAYS[attempt])
    if response.status_code >= 400:
        raise RuntimeError(
            f"{url} answered HTTP {response.status_code}: {response.text[:200]}"
        )
    choice = response.json()["choices"][0]
    content = choice["message"].get("content") or ""
    if not content.strip() and choice.get("finish_reason") == "length":
        raise RuntimeError("the model used its whole token budget without answering")
    return extract_json(content)
