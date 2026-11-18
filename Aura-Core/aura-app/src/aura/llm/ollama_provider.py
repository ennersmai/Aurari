"""Ollama LLM client for local model inference via OpenAI-compatible API."""

import base64
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _encode_image(image_source: str) -> str:
    """
    Encode an image to base64 from a file path or URL.
    
    Args:
        image_source: File path or already-base64 string
        
    Returns:
        Base64-encoded image string
    """
    if image_source.startswith("data:"):
        # Already a data URI — extract the base64 part
        return image_source.split(",", 1)[1] if "," in image_source else image_source
    
    path = Path(image_source)
    if path.is_file():
        return base64.b64encode(path.read_bytes()).decode("utf-8")
    
    # Assume it's already base64
    return image_source


def _image_mime(path_or_name: str) -> str:
    """Guess MIME type from extension."""
    lower = path_or_name.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"  # sensible default


class OllamaClient:
    """
    Ollama API client for local LLM inference.

    Ollama exposes an OpenAI-compatible API at /v1/chat/completions,
    so this client mirrors OpenRouterClient's interface for seamless swapping.
    Supports multimodal models (LLaVA, Qwen2-VL, Llama 3.2 Vision).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
    ):
        """
        Initialize Ollama client.

        Args:
            base_url: Ollama server URL (default: http://localhost:11434)
        """
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=120.0)  # Local models may need longer

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> str:
        """
        Generate completion using Ollama's OpenAI-compatible API.

        Args:
            messages: Chat messages in OpenAI format
            model: Model name (e.g., "llama3.2", "qwen2.5:14b", "mistral")
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters (response_format, etc.)

        Returns:
            Generated text response
        """
        # Strip unsupported kwargs for Ollama
        sanitized_kwargs = {k: v for k, v in kwargs.items() if k not in ("reasoning",)}

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            **sanitized_kwargs,
        }

        try:
            response = await self.client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            if "choices" in data and len(data["choices"]) > 0:
                msg = data["choices"][0].get("message", {})
                content = msg.get("content")
                if content is None or (isinstance(content, str) and content.strip() == ""):
                    # Exponential fallback: content → reasoning → reasoning_details
                    for fallback_key in ("reasoning", "reasoning_details"):
                        fallback = msg.get(fallback_key)
                        if fallback and isinstance(fallback, str) and fallback.strip():
                            logger.info(
                                f"Ollama returned empty content, "
                                f"using '{fallback_key}' as fallback."
                            )
                            return fallback
                    raise ValueError("Empty completion returned from Ollama")
                return content
            else:
                raise ValueError("No completion returned from Ollama")

        except httpx.ConnectError:
            logger.error(
                "❌ Cannot connect to Ollama. Is it running? "
                f"Tried: {self.base_url}"
            )
            raise ConnectionError(
                f"Ollama server not reachable at {self.base_url}. "
                "Start it with: ollama serve"
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"Ollama HTTP error: {e.response.status_code} - {e.response.text[:500]}")
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
        Stream completion using Ollama's OpenAI-compatible API.

        Args:
            messages: Chat messages
            model: Model name
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            **kwargs: Additional parameters

        Yields:
            Text chunks as they arrive
        """
        sanitized_kwargs = {k: v for k, v in kwargs.items() if k not in ("reasoning",)}

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            **sanitized_kwargs,
        }

        try:
            async with self.client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]

                        if data_str.strip() == "[DONE]":
                            break

                        try:
                            import json

                            data = json.loads(data_str)
                            if "choices" in data and len(data["choices"]) > 0:
                                delta = data["choices"][0].get("delta", {})
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
            logger.error(f"❌ Cannot connect to Ollama at {self.base_url}")
            raise ConnectionError(
                f"Ollama server not reachable at {self.base_url}. "
                "Start it with: ollama serve"
            )

    async def complete_with_images(
        self,
        prompt: str,
        images: list[str],
        model: str = "llava:13b",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        system: str | None = None,
    ) -> str:
        """
        Generate completion with image inputs (multimodal vision).

        Uses OpenAI vision message format supported by Ollama for models
        like LLaVA, Qwen2-VL, Llama 3.2 Vision.

        Args:
            prompt: Text prompt / question about the image(s)
            images: List of image sources (file paths, base64 strings, or data URIs)
            model: Vision-capable model (e.g., "llava:13b", "llama3.2:11b")
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            system: Optional system message

        Returns:
            Generated text response describing/analyzing the image(s)
        """
        # Build multimodal content array (OpenAI vision format)
        content: list[dict[str, Any]] = []

        for img_src in images:
            b64 = _encode_image(img_src)
            mime = _image_mime(img_src)
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime};base64,{b64}",
                },
            })

        content.append({"type": "text", "text": prompt})

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        try:
            response = await self.client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            if "choices" in data and len(data["choices"]) > 0:
                msg = data["choices"][0].get("message", {})
                result = msg.get("content")
                if result is None or (isinstance(result, str) and not result.strip()):
                    raise ValueError("Empty vision response from Ollama")
                return result
            raise ValueError("No completion returned from Ollama vision")

        except httpx.ConnectError:
            raise ConnectionError(
                f"Ollama not reachable at {self.base_url}. Start it with: ollama serve"
            )

    async def list_models(self) -> list[dict[str, Any]]:
        """
        List models available in Ollama.

        Returns:
            List of model info dictionaries with name, size, etc.
        """
        try:
            response = await self.client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return data.get("models", [])
        except httpx.ConnectError:
            logger.warning(f"Ollama not reachable at {self.base_url}")
            return []
        except Exception as e:
            logger.error(f"Failed to list Ollama models: {e}")
            return []

    async def pull_model(self, model_name: str) -> bool:
        """
        Pull (download) a model to Ollama.

        Args:
            model_name: Model to pull (e.g., "llama3.2", "qwen2.5:14b")

        Returns:
            True if successful
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/api/pull",
                json={"name": model_name},
                timeout=600.0,  # Models can be large
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to pull model {model_name}: {e}")
            return False

    async def is_available(self) -> bool:
        """Check if Ollama server is running and accessible."""
        try:
            response = await self.client.get(f"{self.base_url}/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    async def get_model_info(self, model_name: str) -> dict[str, Any] | None:
        """
        Get detailed info about a specific model.

        Args:
            model_name: Model name

        Returns:
            Model info dict or None
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/api/show",
                json={"name": model_name},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get model info for {model_name}: {e}")
            return None

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
