"""OpenRouter LLM client for unified model access."""

import asyncio
import logging
from typing import Any

import httpx

from aura.config import settings
from aura.llm.tool_calls import (
    ModelTurn,
    StreamToolCallAccumulator,
    parse_openai_tool_calls,
)

logger = logging.getLogger(__name__)

# Retry configuration for transient errors
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0


class OpenRouterClient:
    """
    OpenRouter API client for accessing multiple LLM providers.

    Based on Cognitive PRD Section 4.3.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        """
        Initialize OpenRouter client.

        Args:
            api_key: OpenRouter API key (defaults to settings)
            base_url: API base URL (defaults to settings)
        """
        self.api_key = api_key or settings.openrouter_api_key
        self.base_url = base_url or settings.openrouter_base_url

        if not self.api_key:
            logger.warning("OpenRouter API key not configured")

        self.client = httpx.AsyncClient(timeout=60.0)

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> str:
        """
        Generate completion using OpenRouter with automatic fallback on failure.

        Implements exponential backoff retry for transient errors (429, 504).

        Args:
            messages: Chat messages in OpenAI format
            model: Model identifier (e.g., "mistralai/mistral-7b-instruct")
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional model parameters

        Returns:
            Generated text response
        """
        # Retry logic with exponential backoff for transient errors (429, 504)
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                return await self._execute_complete(messages, model, temperature, max_tokens, **kwargs)
            except (httpx.HTTPStatusError, httpx.RequestError, ValueError) as e:
                # Determine if this error is retryable
                is_retryable = False
                status_code = None
                
                if isinstance(e, httpx.HTTPStatusError):
                    status_code = e.response.status_code
                    # 429 = rate limit, 504 = gateway timeout, 502/503 = bad gateway/unavailable
                    is_retryable = status_code in (429, 502, 503, 504)
                
                # Check if this is a 400 error that should fallback (not retry)
                is_fallback_only = False
                if isinstance(e, httpx.HTTPStatusError) and status_code == 400:
                    # 400 errors often indicate model doesn't support the endpoint/format
                    # These should fallback, not retry
                    is_fallback_only = True
                
                if is_retryable and attempt < MAX_RETRIES:
                    # Calculate exponential backoff with jitter
                    backoff_time = min(
                        BASE_BACKOFF_SECONDS * (2 ** attempt),
                        MAX_BACKOFF_SECONDS
                    )
                    # Add small jitter (0-0.5s) to prevent thundering herd
                    import random
                    backoff_time += random.uniform(0, 0.5)
                    
                    logger.warning(
                        f"⏳ Transient error (status={status_code}, model={model}, attempt {attempt+1}/{MAX_RETRIES+1}). "
                        f"Retrying in {backoff_time:.1f}s..."
                    )
                    await asyncio.sleep(backoff_time)
                    last_error = e
                    continue
                
                # Store error for fallback logic
                last_error = e
                
                # Check if this is a rate limit (429), server error (5xx), invalid request (400), or request error
                should_fallback = False
                if isinstance(e, httpx.HTTPStatusError):
                    should_fallback = status_code in (429, 400) or (500 <= status_code < 600)
                    # Log upstream diagnostics (helps debug "empty response" / provider issues)
                    request_id = e.response.headers.get("x-request-id") or e.response.headers.get("x-openrouter-request-id")
                    try:
                        body_preview = e.response.text[:500]
                    except Exception:
                        body_preview = "<unavailable>"
                    logger.warning(
                        f"OpenRouter HTTP error (status={status_code}, model={model}, request_id={request_id}): {body_preview}"
                    )
                elif isinstance(e, httpx.RequestError):
                    should_fallback = True
                    logger.warning(f"Request error for model={model}: {e}")
                elif isinstance(e, ValueError):
                    # Treat empty / missing completions as eligible for fallback
                    msg = str(e).lower()
                    should_fallback = "no completion" in msg or "empty completion" in msg
                
                if should_fallback or isinstance(e, httpx.RequestError):
                    # Check for fallback
                    fallback_model = settings.get_fallback(model)
                    
                    if fallback_model and fallback_model != model:
                        logger.warning(
                            f"⚠️ Primary model {model} failed ({str(e)}). "
                            f"Switching to fallback: {fallback_model}"
                        )
                        try:
                            try:
                                return await self._execute_complete(
                                    messages, fallback_model, temperature, max_tokens, **kwargs
                                )
                            except httpx.HTTPStatusError as fallback_http:
                                # If the fallback rejects the request (often due to response_format / reasoning),
                                # retry once with a sanitized payload.
                                if fallback_http.response.status_code == 400:
                                    sanitized_kwargs = dict(kwargs)
                                    sanitized_kwargs.pop("response_format", None)
                                    sanitized_kwargs.pop("reasoning", None)
                                    logger.warning(
                                        f"⚠️ Fallback model {fallback_model} returned 400; retrying without response_format/reasoning"
                                    )
                                    return await self._execute_complete(
                                        messages, fallback_model, temperature, max_tokens, **sanitized_kwargs
                                    )
                                raise
                        except Exception as fallback_e:
                            logger.error(
                                f"❌ Fallback model {fallback_model} also failed: {fallback_e}"
                            )
                            raise last_error or e  # Raise original error if both fail
                
                raise last_error or e

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

        Routing through :meth:`complete` keeps its retry and fallback policy:
        the tools travel in the payload, and with them present the request
        executor returns a :class:`ModelTurn` instead of text.
        """
        return await self.complete(
            messages,
            model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice="auto",
            **kwargs,
        )

    async def _execute_complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> str:
        """Internal execution method for completion."""
        if not self.api_key:
            raise ValueError("OpenRouter API key not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # OpenRouter specific: reasoning parameter can be passed directly in payload
        # (When using httpx directly, we don't need extra_body like the OpenAI client library)
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
        )

        response.raise_for_status()
        data = response.json()

        with_tools = kwargs.get("tools") is not None
        if "choices" in data and len(data["choices"]) > 0:
            msg = data["choices"][0].get("message", {}) if isinstance(data["choices"][0], dict) else {}
            content = msg.get("content") if isinstance(msg, dict) else None
            if with_tools:
                return ModelTurn(
                    text=content if isinstance(content, str) else "",
                    tool_calls=parse_openai_tool_calls(
                        msg.get("tool_calls") if isinstance(msg, dict) else None
                    ),
                )
            if content is None or (isinstance(content, str) and content.strip() == ""):
                # Exponential fallback: content → reasoning → reasoning_details
                # Reasoning models (e.g. qwen3.6-27b, grok-4.3) may return output in
                # 'reasoning' or 'reasoning_details' instead of 'content'.
                for fallback_key in ("reasoning", "reasoning_details"):
                    fallback = msg.get(fallback_key) if isinstance(msg, dict) else None
                    if fallback and isinstance(fallback, str) and fallback.strip():
                        logger.info(
                            f"OpenRouter returned empty content, "
                            f"using '{fallback_key}' as fallback (model={model})."
                        )
                        return fallback
                request_id = response.headers.get("x-request-id") or response.headers.get("x-openrouter-request-id")
                logger.warning(
                    f"OpenRouter returned no message.content (model={model}, request_id={request_id}). "
                    f"message_keys={list(msg.keys()) if isinstance(msg, dict) else type(msg)}"
                )
                raise ValueError("No completion returned from API")
            return content
        else:
            raise ValueError("No completion returned from API")

    async def stream_complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ):
        """
        Stream completion using OpenRouter with automatic fallback on failure.

        Args:
            messages: Chat messages
            model: Model identifier
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            **kwargs: Additional parameters

        Yields:
            Text chunks as they arrive
        """
        try:
            async for chunk in self._execute_stream(
                messages, model, temperature, max_tokens, **kwargs
            ):
                yield chunk
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            # Check if this is a rate limit (429) or server error (5xx)
            should_fallback = False
            if isinstance(e, httpx.HTTPStatusError):
                status_code = e.response.status_code
                should_fallback = status_code == 429 or (500 <= status_code < 600)
            
            if should_fallback or isinstance(e, httpx.RequestError):
                # Check for fallback
                fallback_model = settings.get_fallback(model)
                
                if fallback_model and fallback_model != model:
                    logger.warning(
                        f"⚠️ Primary stream {model} failed. "
                        f"Switching to fallback: {fallback_model}"
                    )
                    try:
                        async for chunk in self._execute_stream(
                            messages, fallback_model, temperature, max_tokens, **kwargs
                        ):
                            yield chunk
                        return
                    except Exception:
                        pass  # Fall through to raise original
            
            raise e

    async def stream_with_tools(
        self,
        messages: list[dict[str, str]],
        model: str,
        tools: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ):
        """Stream text deltas and, at the end, the joined tool calls.

        Routing through :meth:`stream_complete` keeps its fallback policy;
        with ``tools`` in the payload the stream yields ``("text", chunk)``
        items and one final ``("tool_calls", calls)`` item.
        """
        async for item in self.stream_complete(
            messages,
            model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice="auto",
            **kwargs,
        ):
            yield item

    async def _execute_stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ):
        """Internal streaming method."""
        if not self.api_key:
            raise ValueError("OpenRouter API key not configured")

        with_tools = kwargs.get("tools") is not None
        accumulator = StreamToolCallAccumulator() if with_tools else None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # OpenRouter specific: reasoning parameter can be passed directly in payload
        # (When using httpx directly, we don't need extra_body like the OpenAI client library)
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            **kwargs,
        }

        async with self.client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
        ) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]  # Remove "data: " prefix

                    if data_str.strip() == "[DONE]":
                        break

                    try:
                        import json

                        data = json.loads(data_str)
                        if "choices" in data and len(data["choices"]) > 0:
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield ("text", content) if with_tools else content
                            else:
                                # Exponential fallback: content → reasoning → reasoning_details
                                for fallback_key in ("reasoning", "reasoning_details"):
                                    fallback = delta.get(fallback_key, "")
                                    if fallback:
                                        yield ("text", fallback) if with_tools else fallback
                                        break
                            if accumulator is not None:
                                accumulator.add(delta.get("tool_calls") or [])
                    except json.JSONDecodeError:
                        continue

        if accumulator is not None:
            yield ("tool_calls", accumulator.calls())

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
