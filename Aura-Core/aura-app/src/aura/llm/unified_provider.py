"""Unified LLM provider that routes to OpenRouter (cloud) or Ollama (local) per layer."""

import logging
from typing import Any

from aura.config import settings
from aura.llm.ollama_provider import OllamaClient
from aura.llm.provider import OpenRouterClient

logger = logging.getLogger(__name__)


class UnifiedLLMClient:
    """
    Unified LLM client that seamlessly routes requests to either
    OpenRouter (cloud) or Ollama (local) based on per-layer configuration.

    Each cognitive layer (L1-L5) can independently use local or cloud inference.
    The routing is transparent to the caller — same interface regardless of backend.
    """

    def __init__(
        self,
        openrouter_client: OpenRouterClient | None = None,
        ollama_client: OllamaClient | None = None,
    ):
        """
        Initialize unified client with both providers.

        Args:
            openrouter_client: Cloud provider (creates new if None)
            ollama_client: Local provider (creates new if None)
        """
        self.cloud = openrouter_client or OpenRouterClient()
        self.local = ollama_client or OllamaClient(
            base_url=settings.ollama_base_url
        )
        self._ollama_available: bool | None = None

    def _resolve_provider(self, model: str) -> tuple[Any, str, str]:
        """
        Determine which provider and model to use for a given model identifier.

        Local models are prefixed with "local/" (e.g., "local/llama3.2").
        Cloud models use their full identifier (e.g., "anthropic/claude-3.5-sonnet").

        Args:
            model: Model identifier, possibly prefixed with "local/"

        Returns:
            Tuple of (client, actual_model_name, provider_name)
        """
        if model.startswith("local/"):
            actual_model = model[6:]  # Strip "local/" prefix
            return self.local, actual_model, "ollama"
        else:
            return self.cloud, model, "openrouter"

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> str:
        """
        Generate completion, automatically routing to the correct provider.

        Args:
            messages: Chat messages in OpenAI format
            model: Model identifier (prefix with "local/" for Ollama)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional model parameters

        Returns:
            Generated text response
        """
        client, actual_model, provider = self._resolve_provider(model)
        logger.debug(f"Routing to {provider}: {actual_model}")

        try:
            return await client.complete(
                messages=messages,
                model=actual_model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        except (ConnectionError, Exception) as e:
            # If local fails and fallback is enabled, try cloud
            if provider == "ollama" and settings.local_llm_fallback_to_cloud:
                cloud_model = self._get_cloud_fallback(model)
                if cloud_model:
                    logger.warning(
                        f"⚠️ Local model {actual_model} failed ({e}). "
                        f"Falling back to cloud: {cloud_model}"
                    )
                    return await self.cloud.complete(
                        messages=messages,
                        model=cloud_model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **kwargs,
                    )
            raise

    async def stream_complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ):
        """
        Stream completion, automatically routing to the correct provider.

        Args:
            messages: Chat messages
            model: Model identifier (prefix with "local/" for Ollama)
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            **kwargs: Additional parameters

        Yields:
            Text chunks as they arrive
        """
        client, actual_model, provider = self._resolve_provider(model)
        logger.debug(f"Streaming from {provider}: {actual_model}")

        try:
            async for chunk in client.stream_complete(
                messages=messages,
                model=actual_model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            ):
                yield chunk
        except (ConnectionError, Exception) as e:
            if provider == "ollama" and settings.local_llm_fallback_to_cloud:
                cloud_model = self._get_cloud_fallback(model)
                if cloud_model:
                    logger.warning(
                        f"⚠️ Local stream {actual_model} failed ({e}). "
                        f"Falling back to cloud: {cloud_model}"
                    )
                    async for chunk in self.cloud.stream_complete(
                        messages=messages,
                        model=cloud_model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **kwargs,
                    ):
                        yield chunk
                    return
            raise

    def _get_cloud_fallback(self, local_model: str) -> str | None:
        """
        Get the cloud fallback model for a local model.

        Maps the layer's local model back to its cloud counterpart.
        """
        # Check which layer this model belongs to and return the cloud version
        layer_map = {
            settings.l1_model: settings.l1_model_fallback or "meta-llama/llama-3.1-8b-instruct",
            settings.l2_model: settings.l2_model_fallback or "deepseek/deepseek-chat",
            settings.l3_model: settings.l3_model_fallback or "deepseek/deepseek-chat",
            settings.l4_model: settings.l4_model_fallback or "qwen/qwen-2.5-72b-instruct",
            settings.l5_model: settings.l5_model_fallback or "google/gemini-2.0-flash-001",
        }
        return layer_map.get(local_model)

    async def is_local_available(self) -> bool:
        """Check if Ollama is running and accessible."""
        self._ollama_available = await self.local.is_available()
        return self._ollama_available

    async def list_local_models(self) -> list[dict[str, Any]]:
        """List models available in Ollama."""
        return await self.local.list_models()

    async def pull_local_model(self, model_name: str) -> bool:
        """Pull a model to Ollama."""
        return await self.local.pull_model(model_name)

    async def close(self) -> None:
        """Close both clients."""
        await self.cloud.close()
        await self.local.close()
