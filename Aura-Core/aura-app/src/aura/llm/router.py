"""
Unified LLM Routing Proxy — context-mode-aware inference dispatch.

Routes all L1/L2/L3 generation requests based on the active
context_mode flag set by the sovereign orchestrator.

  * context_mode == "deep_work"  → OpenRouter (cloud)
  * context_mode == "private_rp" → Local OpenAI-compatible endpoint
                                    (llama.cpp, vLLM, Ollama API, text-generation-webui)

Provides a single 'generate(...)' entry-point that callers use
instead of reaching directly into OpenRouterClient or OllamaClient.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Literal

import httpx

from aura.config import settings
from aura.llm.provider import OpenRouterClient
from aura.llm.ollama_provider import OllamaClient
from aura.llm.tool_calls import (
    ModelTurn,
    StreamToolCallAccumulator,
    parse_openai_tool_calls,
)

logger = logging.getLogger(__name__)

ContextMode = Literal["deep_work", "private_rp"]


class LocalInferenceClient:
    """
    Generic OpenAI-compatible client targeting a local inference server.

    Works with:
    - llama.cpp server (--api)
    - text-generation-webui (--api)
    - vLLM
    - Ollama (OpenAI-compatible endpoint)
    - llama-box / LM Studio
    """

    def __init__(self) -> None:
        self._base_url: str = settings.local_inference_url.rstrip("/")
        self._api_key: str = settings.local_inference_api_key
        self._timeout: float = settings.local_inference_timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                headers=headers,
            )
        return self._client

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> str:
        """
        Single-turn completion against the local OpenAI-compatible endpoint.

        Raises ConnectionError with a descriptive message when the endpoint
        is unreachable — callers are expected to handle this gracefully.
        """
        client = await self._get_client()

        # Strip unsupported parameters for vanilla OpenAI-compatible endpoints
        sanitized = {k: v for k, v in kwargs.items() if k not in ("reasoning",)}

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            **sanitized,
        }

        try:
            resp = await client.post(self._base_url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if "choices" in data and len(data["choices"]) > 0:
                msg = data["choices"][0].get("message", {})
                content = msg.get("content")
                if content is None or (isinstance(content, str) and content.strip() == ""):
                    # Exponential fallback: content → reasoning → reasoning_details
                    for fallback_key in ("reasoning", "reasoning_details"):
                        fallback = msg.get(fallback_key)
                        if fallback and isinstance(fallback, str) and fallback.strip():
                            logger.info(
                                f"Local inference returned empty content, "
                                f"using '{fallback_key}' as fallback."
                            )
                            return fallback
                    raise ValueError("Local inference returned empty completion")
                return content
            raise ValueError("No completion returned from local inference endpoint")

        except httpx.ConnectError:
            raise ConnectionError(
                f"Local inference endpoint unreachable at {self._base_url}. "
                "Ensure your local LLM server (llama.cpp, vLLM, Ollama) is running."
            )
        except httpx.TimeoutException:
            raise ConnectionError(
                f"Local inference endpoint timed out ({self._timeout}s) at {self._base_url}."
            )

    async def complete_with_tools(
        self,
        messages: list[dict[str, str]],
        model: str,
        tools: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> ModelTurn:
        """Completion that offers ``tools`` and returns text plus tool calls.

        Same payload shape and error mapping as :meth:`complete`; the local
        endpoint keeps no retry or fallback of its own.
        """
        client = await self._get_client()

        sanitized = {k: v for k, v in kwargs.items() if k not in ("reasoning",)}

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "tools": tools,
            "tool_choice": "auto",
            **sanitized,
        }

        try:
            resp = await client.post(self._base_url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if "choices" in data and len(data["choices"]) > 0:
                msg = data["choices"][0].get("message", {})
                content = msg.get("content")
                return ModelTurn(
                    text=content if isinstance(content, str) else "",
                    tool_calls=parse_openai_tool_calls(msg.get("tool_calls")),
                )
            raise ValueError("No completion returned from local inference endpoint")

        except httpx.ConnectError:
            raise ConnectionError(
                f"Local inference endpoint unreachable at {self._base_url}. "
                "Ensure your local LLM server (llama.cpp, vLLM, Ollama) is running."
            )
        except httpx.TimeoutException:
            raise ConnectionError(
                f"Local inference endpoint timed out ({self._timeout}s) at {self._base_url}."
            )

    async def stream_complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """
        Stream completion from the local OpenAI-compatible endpoint.
        """
        client = await self._get_client()

        sanitized = {k: v for k, v in kwargs.items() if k not in ("reasoning",)}

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            **sanitized,
        }

        try:
            async with client.stream("POST", self._base_url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk_data = json.loads(data_str)
                            if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                                delta = chunk_data["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                                else:
                                    # Exponential fallback: content → reasoning → reasoning_details
                                    for fallback_key in ("reasoning", "reasoning_details"):
                                        fallback = delta.get(fallback_key, "")
                                        if fallback:
                                            yield fallback
                                            break
                        except json.JSONDecodeError:
                            continue
        except httpx.ConnectError:
            raise ConnectionError(
                f"Local inference endpoint unreachable at {self._base_url}."
            )

    async def stream_with_tools(
        self,
        messages: list[dict[str, str]],
        model: str,
        tools: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ):
        """Stream ``("text", chunk)`` items and one final ``("tool_calls", calls)``.

        Same endpoint and error mapping as :meth:`stream_complete`; argument
        fragments are joined by index as they arrive.
        """
        client = await self._get_client()

        sanitized = {k: v for k, v in kwargs.items() if k not in ("reasoning",)}

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "tools": tools,
            "tool_choice": "auto",
            **sanitized,
        }

        accumulator = StreamToolCallAccumulator()

        try:
            async with client.stream("POST", self._base_url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk_data = json.loads(data_str)
                            if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                                delta = chunk_data["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield ("text", content)
                                else:
                                    # Exponential fallback: content → reasoning → reasoning_details
                                    for fallback_key in ("reasoning", "reasoning_details"):
                                        fallback = delta.get(fallback_key, "")
                                        if fallback:
                                            yield ("text", fallback)
                                            break
                                accumulator.add(delta.get("tool_calls") or [])
                        except json.JSONDecodeError:
                            continue
        except httpx.ConnectError:
            raise ConnectionError(
                f"Local inference endpoint unreachable at {self._base_url}."
            )

        yield ("tool_calls", accumulator.calls())

    async def is_available(self) -> bool:
        """Probe whether the local endpoint is live."""
        try:
            client = await self._get_client()
            # Try a lightweight models list or health check
            base = self._base_url.rsplit("/v1/", 1)[0]
            resp = await client.get(f"{base}/v1/models", timeout=httpx.Timeout(5.0))
            return resp.status_code == 200
        except Exception:
            # Fallback: try a quick POST
            try:
                client2 = await self._get_client()
                resp2 = await client2.post(
                    self._base_url,
                    json={
                        "model": ".",
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                    timeout=httpx.Timeout(5.0),
                )
                return resp2.status_code < 500
            except Exception:
                return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class ContextModeRouter:
    """
    Sovereign routing proxy — every L1/L2/L3 request passes through here.

    The orchestrator sets context_mode on each query; the router
    dispatches to the correct backend transparently.

    Lifecycle
    --------
    - Created once at startup (by main.py).
    - Held by LLMLayers and the orchestrator.
    - ``.close()`` tears down the HTTP clients.

    Error Semantics
    ---------------
    If context_mode == "private_rp" and the local endpoint is down,
    a ``ConnectionError`` is raised with a descriptive message.
    The caller (orchestrator) is expected to surface this as a
    user-visible error rather than silently falling back to cloud,
    preserving the user's privacy expectation.
    """

    def __init__(
        self,
        openrouter: OpenRouterClient | None = None,
        local: LocalInferenceClient | None = None,
        ollama: OllamaClient | None = None,
    ) -> None:
        self._cloud = openrouter or OpenRouterClient()
        self._local = local or LocalInferenceClient()
        self._ollama = ollama or OllamaClient(base_url=settings.ollama_base_url)
        self._mode: ContextMode = "deep_work"

    # ------------------------------------------------------------------
    # Mode management
    # ------------------------------------------------------------------

    @property
    def context_mode(self) -> ContextMode:
        return self._mode

    @context_mode.setter
    def context_mode(self, value: ContextMode) -> None:
        if value not in ("deep_work", "private_rp"):
            raise ValueError(f"Invalid context_mode: {value}")
        self._mode = value
        logger.info(f"ContextModeRouter switched to: {value}")

    # ------------------------------------------------------------------
    # Generation (dispatched by context_mode)
    # ------------------------------------------------------------------

    async def generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> str:
        """
        Complete a generation, routing based on active context_mode.
        """
        if self._mode == "private_rp":
            return await self._generate_local(messages, model, temperature, max_tokens, **kwargs)
        return await self._generate_cloud(messages, model, temperature, max_tokens, **kwargs)

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """
        Stream a generation, routing based on active context_mode.
        """
        if self._mode == "private_rp":
            async for chunk in self._stream_local(messages, model, temperature, max_tokens, **kwargs):
                yield chunk
        else:
            async for chunk in self._stream_cloud(messages, model, temperature, max_tokens, **kwargs):
                yield chunk

    # ------------------------------------------------------------------
    # Native tool calls (dispatched by context_mode)
    # ------------------------------------------------------------------

    async def generate_with_tools(
        self,
        messages: list[dict[str, str]],
        model: str,
        tools: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> ModelTurn:
        """Complete with ``tools``, routed like :meth:`generate`."""
        client = self._local if self._mode == "private_rp" else self._cloud
        try:
            return await client.complete_with_tools(
                messages=messages, model=model, tools=tools,
                temperature=temperature, max_tokens=max_tokens, **kwargs,
            )
        except ConnectionError:
            raise
        except Exception as e:
            if client is self._local:
                logger.error(f"Local inference failed: {e}")
                raise ConnectionError(
                    f"Local inference endpoint failed: {e}. "
                    "The private_rp context mode requires a running local LLM server."
                )
            raise

    async def generate_stream_with_tools(
        self,
        messages: list[dict[str, str]],
        model: str,
        tools: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[str, Any]]:
        """Stream with ``tools``, routed like :meth:`generate_stream`."""
        client = self._local if self._mode == "private_rp" else self._cloud
        try:
            async for item in client.stream_with_tools(
                messages=messages, model=model, tools=tools,
                temperature=temperature, max_tokens=max_tokens, **kwargs,
            ):
                yield item
        except ConnectionError:
            raise
        except Exception as e:
            if client is self._local:
                logger.error(f"Local inference stream failed: {e}")
                raise ConnectionError(
                    f"Local inference endpoint failed: {e}."
                )
            raise

    # ------------------------------------------------------------------
    # Internal dispatch helpers
    # ------------------------------------------------------------------

    async def _generate_cloud(
        self, messages: list[dict[str, str]], model: str,
        temperature: float, max_tokens: int, **kwargs: Any,
    ) -> str:
        return await self._cloud.complete(
            messages=messages, model=model,
            temperature=temperature, max_tokens=max_tokens, **kwargs,
        )

    async def _generate_local(
        self, messages: list[dict[str, str]], model: str,
        temperature: float, max_tokens: int, **kwargs: Any,
    ) -> str:
        try:
            return await self._local.complete(
                messages=messages, model=model,
                temperature=temperature, max_tokens=max_tokens, **kwargs,
            )
        except ConnectionError:
            raise  # Re-raise — caller MUST handle
        except Exception as e:
            logger.error(f"Local inference failed: {e}")
            raise ConnectionError(
                f"Local inference endpoint failed: {e}. "
                "The private_rp context mode requires a running local LLM server."
            )

    async def _stream_cloud(
        self, messages: list[dict[str, str]], model: str,
        temperature: float, max_tokens: int, **kwargs: Any,
    ) -> AsyncIterator[str]:
        async for chunk in self._cloud.stream_complete(
            messages=messages, model=model,
            temperature=temperature, max_tokens=max_tokens, **kwargs,
        ):
            yield chunk

    async def _stream_local(
        self, messages: list[dict[str, str]], model: str,
        temperature: float, max_tokens: int, **kwargs: Any,
    ) -> AsyncIterator[str]:
        try:
            async for chunk in self._local.stream_complete(
                messages=messages, model=model,
                temperature=temperature, max_tokens=max_tokens, **kwargs,
            ):
                yield chunk
        except ConnectionError:
            raise
        except Exception as e:
            logger.error(f"Local inference stream failed: {e}")
            raise ConnectionError(
                f"Local inference endpoint failed: {e}."
            )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    async def is_local_available(self) -> bool:
        """Check whether the local inference endpoint is reachable."""
        return await self._local.is_available()

    async def is_ollama_available(self) -> bool:
        """Check whether Ollama is reachable (legacy compat)."""
        return await self._ollama.is_available()

    async def get_cloud_client(self) -> OpenRouterClient:
        """Expose the cloud client for direct access if needed."""
        return self._cloud

    async def get_local_client(self) -> LocalInferenceClient:
        """Expose the local client for direct access if needed."""
        return self._local

    async def close(self) -> None:
        await self._cloud.close()
        await self._local.close()
        await self._ollama.close()
