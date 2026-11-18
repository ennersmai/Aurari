"""
Voice API Routes

Provides text-to-speech endpoints using Edge-TTS (cloud) or Qwen3-TTS (local).
The active provider is determined by AURA_TTS_PROVIDER config.
Qwen3-TTS supports emotional control mapped from Aura's emotion engine.
"""

import base64
import io
import logging
import re
from typing import Annotated, Any

import aiohttp
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from aura.config import settings
from aura.engines.voice.edge import EdgeEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])

# Initialize Edge-TTS engine (always available as fallback)
edge_engine = EdgeEngine()


# ---- Explicit CORS preflight handler for /voice/stream -------------------
@router.options("/stream")
async def voice_stream_preflight() -> dict[str, str]:
    return {}


# ---- Qwen3 TTS Client ---------------------------------------------------

class Qwen3TTSClient:
    """Async HTTP client for the Qwen3-TTS FastAPI server."""

    def __init__(self, base_url: str = "http://localhost:50000"):
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    async def is_available(self) -> bool:
        """Check if Qwen3-TTS server is reachable."""
        try:
            r = await self.client.get(f"{self.base_url}/health", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    async def get_speakers(self) -> list[str]:
        """Get available speakers."""
        try:
            r = await self.client.get(f"{self.base_url}/speakers", timeout=5.0)
            data = r.json()
            return data.get("speakers", [])
        except Exception:
            return ["serena", "vivian", "ryan", "aiden", "ono_anna", "sohee", "eric", "dylan", "uncle_fu"]

    async def generate(
        self,
        text: str,
        speaker: str = "serena",
        instruct: str | None = None,
    ) -> bytes:
        """
        Generate TTS audio via Qwen3-TTS server.

        Returns raw WAV bytes.
        """
        form_data = {
            "tts_text": text,
            "spk_id": speaker,
        }
        if instruct:
            form_data["instruct_text"] = instruct

        endpoint = "/inference_instruct" if instruct else "/inference_sft"

        try:
            r = await self.client.post(
                f"{self.base_url}{endpoint}",
                data=form_data,
                timeout=120.0,
            )
            r.raise_for_status()
            return r.content
        except httpx.ConnectError:
            raise ConnectionError(
                f"Qwen3-TTS server not reachable at {self.base_url}. "
                "Start it with: python server.py --port 50000 --model_dir ./Qwen3-TTS"
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"Qwen3-TTS HTTP error: {e.response.status_code} - {e.response.text[:500]}")
            raise

    async def _raw_post(self, endpoint: str, data: dict[str, str]) -> bytes:
        """Send a raw POST to the Qwen3-TTS server and return bytes."""
        r = await self.client.post(
            f"{self.base_url}{endpoint}",
            data=data,
            timeout=120.0,
        )
        r.raise_for_status()
        return r.content

    async def clone(
        self,
        text: str,
        speaker: str = "serena",
        instruct: str | None = None,
        language: str = "english",
        prompt_text: str = "",
        prompt_wav_bytes: bytes | None = None,
    ) -> bytes:
        """Send a voice clone request to the Qwen3-TTS server.

        Uses multipart/form-data if reference audio is provided,
        otherwise falls back to simple form POST.
        """
        form_data: dict[str, str] = {
            "tts_text": text,
            "spk_id": speaker,
            "language": language,
            "instruct_text": instruct or "",
            "prompt_text": prompt_text,
        }

        if prompt_wav_bytes and len(prompt_wav_bytes) > 44:
            clone_url = f"{self.base_url}/clone"
            async with aiohttp.ClientSession() as session:
                mpw = aiohttp.MultipartWriter("form-data")
                for key, val in form_data.items():
                    part = mpw.append(val)
                    part.set_content_disposition("form-data", name=key)
                part = mpw.append(prompt_wav_bytes)
                part.set_content_disposition(
                    "form-data", name="prompt_wav", filename="reference.wav"
                )
                part.headers["Content-Type"] = "audio/wav"

                async with session.post(
                    clone_url, data=mpw, timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status != 200:
                        text_resp = await resp.text()
                        raise HTTPException(resp.status, f"TTS server error: {text_resp[:500]}")
                    return await resp.read()
        else:
            return await self._raw_post("/inference_clone", form_data)

    async def get_config(self) -> dict:
        """Get Qwen3-TTS generation config."""
        r = await self.client.get(f"{self.base_url}/config", timeout=5.0)
        r.raise_for_status()
        return r.json()

    async def update_config(self, updates: dict) -> dict:
        """Update Qwen3-TTS generation config."""
        r = await self.client.post(
            f"{self.base_url}/config", json=updates, timeout=5.0
        )
        r.raise_for_status()
        return r.json()

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


# Lazy-initialized Qwen3 TTS client
_qwen3_client: Qwen3TTSClient | None = None


def _get_qwen3() -> Qwen3TTSClient:
    global _qwen3_client
    if _qwen3_client is None:
        _qwen3_client = Qwen3TTSClient(base_url=settings.qwen3_tts_base_url)
    return _qwen3_client


# ---- FishAudio TTS Client -------------------------------------------------

class FishAudioClient:
    """Async HTTP client for the FishAudio (Fish-Speech) FastAPI server."""

    def __init__(self, base_url: str = "http://localhost:50001"):
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    async def is_available(self) -> bool:
        """Check if FishAudio server is reachable."""
        try:
            r = await self.client.get(f"{self.base_url}/health", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    async def get_speakers(self) -> list[str]:
        """Get available speakers."""
        try:
            r = await self.client.get(f"{self.base_url}/speakers", timeout=5.0)
            data = r.json()
            return data.get("speakers", ["default"])
        except Exception:
            return ["default"]

    async def generate(
        self,
        text: str,
        speaker: str = "default",
        instruct: str | None = None,
    ) -> bytes:
        """
        Generate TTS audio via FishAudio server.

        Returns raw WAV bytes.
        """
        form_data = {
            "tts_text": text,
            "spk_id": speaker,
        }
        if instruct:
            form_data["instruct_text"] = instruct

        try:
            r = await self.client.post(
                f"{self.base_url}/inference",
                data=form_data,
                timeout=120.0,
            )
            r.raise_for_status()
            return r.content
        except httpx.ConnectError:
            raise ConnectionError(
                f"FishAudio server not reachable at {self.base_url}. "
                "Start it with: python server.py --port 50001 --model_dir ./FishAudio"
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"FishAudio HTTP error: {e.response.status_code} - {e.response.text[:500]}")
            raise

    async def clone(
        self,
        text: str,
        speaker: str = "default",
        instruct: str | None = None,
        language: str = "english",
        prompt_text: str = "",
        prompt_wav_bytes: bytes | None = None,
    ) -> bytes:
        """Send a voice clone request to the FishAudio server."""
        form_data: dict[str, str] = {
            "tts_text": text,
            "spk_id": speaker,
            "prompt_text": prompt_text or "",
        }

        if prompt_wav_bytes and len(prompt_wav_bytes) > 44:
            try:
                import aiohttp
                clone_url = f"{self.base_url}/inference_clone"
                mpw = aiohttp.MultipartWriter("form-data")
                for key, val in form_data.items():
                    part = mpw.append(val)
                    part.set_content_disposition("form-data", name=key)
                part = mpw.append(prompt_wav_bytes)
                part.set_content_disposition(
                    "form-data", name="prompt_wav", filename="reference.wav"
                )
                part.headers["Content-Type"] = "audio/wav"

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        clone_url, data=mpw, timeout=aiohttp.ClientTimeout(total=120)
                    ) as resp:
                        if resp.status != 200:
                            text_resp = await resp.text()
                            raise HTTPException(resp.status, f"TTS server error: {text_resp[:500]}")
                        return await resp.read()
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"FishAudio clone failed: {e}")
                raise
        else:
            # Fall back to standard inference with speaker
            return await self.generate(text=text, speaker=speaker, instruct=instruct)

    async def get_config(self) -> dict:
        """Get FishAudio generation config."""
        r = await self.client.get(f"{self.base_url}/config", timeout=5.0)
        r.raise_for_status()
        return r.json()

    async def update_config(self, updates: dict) -> dict:
        """Update FishAudio generation config."""
        r = await self.client.post(
            f"{self.base_url}/config", json=updates, timeout=5.0
        )
        r.raise_for_status()
        return r.json()

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


# Lazy-initialized FishAudio client
_fishaudio_client: FishAudioClient | None = None


def _get_fishaudio() -> FishAudioClient:
    global _fishaudio_client
    if _fishaudio_client is None:
        _fishaudio_client = FishAudioClient(base_url=settings.fish_audio_base_url)
    return _fishaudio_client


# ---- Emoji stripping utility --------------------------------------------

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"  # dingbats
    "\U000024C2-\U0001F251"  # enclosed characters
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended-A
    "\U00002600-\U000026FF"  # misc symbols
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero-width joiner
    "\U0000200C"             # zero-width non-joiner
    "]+",
    flags=re.UNICODE,
)


def strip_emojis(text: str) -> str:
    """Remove emojis and ZWJ sequences from text for cleaner TTS input."""
    return _EMOJI_PATTERN.sub("", text).strip()


# ---- Endpoints -----------------------------------------------------------


@router.get("/status")
async def get_voice_status() -> dict[str, Any]:
    """
    Get TTS provider status — checks if Qwen3-TTS and FishAudio are reachable.
    """
    qwen3_available = False
    if settings.qwen3_tts_enabled:
        try:
            qwen3 = _get_qwen3()
            qwen3_available = await qwen3.is_available()
        except Exception:
            qwen3_available = False

    fishaudio_available = False
    if settings.fish_audio_enabled:
        try:
            fishaudio = _get_fishaudio()
            fishaudio_available = await fishaudio.is_available()
        except Exception:
            fishaudio_available = False

    return {
        "active_provider": settings.tts_provider,
        "edge_available": True,
        "qwen3_available": qwen3_available,
        "qwen3_enabled": settings.qwen3_tts_enabled,
        "qwen3_url": settings.qwen3_tts_base_url,
        "qwen3_default_speaker": settings.qwen3_tts_default_speaker,
        "fishaudio_available": fishaudio_available,
        "fishaudio_enabled": settings.fish_audio_enabled,
        "fishaudio_url": settings.fish_audio_base_url,
        "fishaudio_default_speaker": settings.fish_audio_default_speaker,
    }


class VoiceRequest(BaseModel):
    """Request model for text-to-speech."""

    text: Annotated[str, Field(
        description="The text to convert to speech",
        min_length=1,
        max_length=5000
    )]
    voice: Annotated[str, Field(
        default="en-US-AriaNeural",
        description="The voice to use for speech synthesis"
    )]
    provider: str | None = Field(
        default=None,
        description="Override TTS provider: 'edge', 'qwen3', or 'fishaudio' (default: from config)"
    )
    emotion_state: dict[str, Any] | None = Field(
        default=None,
        description="Aura emotion state for Qwen3-TTS emotional control"
    )
    instruct: str | None = Field(
        default=None,
        description="Direct instruct text for Qwen3-TTS emotional style"
    )


def _emotion_to_instruct(emotion_state: dict[str, Any] | None) -> str | None:
    """Convert Aura emotion vector to a natural-language Qwen3-TTS instruction."""
    if not emotion_state:
        return None

    # Map dominant emotions to speech style instructions
    emotion_map = {
        "joy": "Speak cheerfully and warmly with a bright, happy tone.",
        "sadness": "Speak softly and gently with a melancholic, tender tone.",
        "anger": "Speak firmly and intensely with a serious, sharp tone.",
        "fear": "Speak quietly and cautiously with a nervous, hesitant tone.",
        "surprise": "Speak with an excited, energetic, and animated tone.",
        "love": "Speak warmly and affectionately with a gentle, loving tone.",
        "trust": "Speak calmly and reassuringly with a steady, confident tone.",
        "curiosity": "Speak inquisitively with an interested, engaged tone.",
        "serenity": "Speak peacefully and slowly with a calm, soothing tone.",
        "empathy": "Speak compassionately and understandingly with a caring tone.",
    }

    # Find the dominant emotion
    if isinstance(emotion_state, dict):
        # Try 'dominant' or find highest value
        dominant = emotion_state.get("dominant", "")
        if not dominant:
            # Find emotion with highest value
            non_meta = {k: v for k, v in emotion_state.items()
                        if isinstance(v, (int, float)) and k not in ("valence", "arousal", "entropy", "volatility", "timestamp", "current_state", "description")}
            if non_meta:
                dominant = max(non_meta, key=non_meta.get)

        if dominant and dominant.lower() in emotion_map:
            return emotion_map[dominant.lower()]

    return None


@router.post("/stream")
async def stream_voice(request: VoiceRequest) -> StreamingResponse:
    """
    Stream audio from text using the configured TTS provider.

    Automatically routes to Edge-TTS (cloud), Qwen3-TTS (local), or FishAudio (local)
    based on config. Qwen3-TTS and FishAudio support emotional control via
    emotion_state or instruct parameters.

    Args:
        request: Voice request containing text, voice, and optional emotion params

    Returns:
        StreamingResponse with audio content
    """
    provider = request.provider or settings.tts_provider

    # Strip emojis from TTS text to prevent sentence order issues
    clean_text = strip_emojis(request.text)

    try:
        logger.info(f"Voice stream [{provider}]: '{clean_text[:50]}...'")

        if provider == "qwen3":
            try:
                qwen3 = _get_qwen3()
                if not await qwen3.is_available():
                    logger.warning("Qwen3-TTS server not reachable, falling back to Edge-TTS")
                else:
                    # Determine speaker
                    speaker = request.voice
                    if speaker == "en-US-AriaNeural" or not speaker:
                        speaker = settings.qwen3_tts_default_speaker

                    # Determine instruct text
                    instruct = request.instruct
                    if not instruct and request.emotion_state:
                        instruct = _emotion_to_instruct(request.emotion_state)

                    # Generate audio (non-streaming from Qwen3 server, returned as single response)
                    wav_bytes = await qwen3.generate(
                        text=clean_text,
                        speaker=speaker,
                        instruct=instruct,
                    )

                    return Response(
                        content=wav_bytes,
                        media_type="audio/wav",
                        headers={
                            "Cache-Control": "no-cache",
                            "X-Content-Type-Options": "nosniff",
                            "X-TTS-Provider": "qwen3",
                            "Access-Control-Allow-Origin": "*",
                        }
                    )
            except (ConnectionError, Exception) as e:
                logger.warning(f"Qwen3-TTS failed ({e}), falling back to Edge-TTS")

        elif provider == "fishaudio":
            try:
                fishaudio = _get_fishaudio()
                if not await fishaudio.is_available():
                    logger.warning("FishAudio server not reachable, falling back to Edge-TTS")
                else:
                    # Determine speaker
                    speaker = request.voice
                    if speaker == "en-US-AriaNeural" or not speaker:
                        speaker = settings.fish_audio_default_speaker

                    # Generate audio
                    wav_bytes = await fishaudio.generate(
                        text=clean_text,
                        speaker=speaker,
                        instruct=request.instruct,
                    )

                    return Response(
                        content=wav_bytes,
                        media_type="audio/wav",
                        headers={
                            "Cache-Control": "no-cache",
                            "X-Content-Type-Options": "nosniff",
                            "X-TTS-Provider": "fishaudio",
                            "Access-Control-Allow-Origin": "*",
                        }
                    )
            except (ConnectionError, Exception) as e:
                logger.warning(f"FishAudio failed ({e}), falling back to Edge-TTS")

        # Edge-TTS (default / fallback)
        # When falling back from qwen3/fishaudio, request.voice may be a local speaker name
        # (e.g. "serena") which is NOT a valid Edge-TTS voice identifier. Reset to default.
        edge_voice = request.voice if (request.voice and request.voice.endswith("Neural")) else "en-US-AriaNeural"
        audio_stream = edge_engine.stream_audio(
            text=clean_text,
            voice=edge_voice
        )
        return StreamingResponse(
            audio_stream,
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
                "X-TTS-Provider": "edge",
                "Access-Control-Allow-Origin": "*",
            }
        )

    except Exception as e:
        logger.error(f"Error in voice stream: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate speech: {str(e)}"
        )


@router.get("/voices")
async def get_voices() -> dict[str, Any]:
    """
    Get available voices from all TTS providers.

    Returns:
        Dictionary with voices per provider
    """
    result: dict[str, Any] = {
        "success": True,
        "active_provider": settings.tts_provider,
        "edge_voices": EdgeEngine.get_available_voices(),
    }

    # Try to get Qwen3-TTS speakers
    if settings.qwen3_tts_enabled or settings.tts_provider == "qwen3":
        try:
            qwen3 = _get_qwen3()
            speakers = await qwen3.get_speakers()
            result["qwen3_speakers"] = speakers
            result["qwen3_available"] = True
        except Exception:
            result["qwen3_speakers"] = []
            result["qwen3_available"] = False

    # Try to get FishAudio speakers
    if settings.fish_audio_enabled or settings.tts_provider == "fishaudio":
        try:
            fishaudio = _get_fishaudio()
            speakers = await fishaudio.get_speakers()
            result["fishaudio_speakers"] = speakers
            result["fishaudio_available"] = True
        except Exception:
            result["fishaudio_speakers"] = ["default"]
            result["fishaudio_available"] = False

    return result


# ---- Voice Clone Endpoint ------------------------------------------------


class VoiceCloneRequest(BaseModel):
    """Request model for voice cloning / instruct-based TTS."""

    text: Annotated[str, Field(
        description="The text to convert to speech",
        min_length=1,
        max_length=5000,
    )]
    speaker: str = Field(
        default="serena",
        description="Qwen3-TTS speaker ID (serena, vivian, ryan, etc.)",
    )
    instruct: str | None = Field(
        default=None,
        description="Emotion/style instruction for the TTS model",
    )
    language: str = Field(
        default="english",
        description="Language code (english, chinese, japanese, korean, etc.)",
    )
    reference_audio: str | None = Field(
        default=None,
        description="Base64-encoded reference audio for voice cloning (Base model only)",
    )
    reference_text: str | None = Field(
        default=None,
        description="Transcript of the reference audio",
    )


@router.post("/clone")
async def voice_clone(request: VoiceCloneRequest) -> Response:
    """
    Voice cloning / instruct-based TTS endpoint.

    Uses Qwen3-TTS for voice generation.  When ``reference_audio`` is
    provided, attempts zero-shot voice cloning (requires the Base model
    variant).  Otherwise falls back to instruct-based generation using
    the CustomVoice model's 9 built-in speakers.

    Returns WAV audio.
    """
    try:
        qwen3 = _get_qwen3()

        # If reference audio is provided, decode it
        prompt_wav_bytes: bytes | None = None
        if request.reference_audio:
            try:
                b64 = request.reference_audio
                if "," in b64:
                    b64 = b64.split(",", 1)[1]
                prompt_wav_bytes = base64.b64decode(b64)
            except Exception as e:
                logger.warning(f"Failed to decode reference audio: {e}")

        wav_bytes = await qwen3.clone(
            text=request.text,
            speaker=request.speaker,
            instruct=request.instruct,
            language=request.language,
            prompt_text=request.reference_text or "",
            prompt_wav_bytes=prompt_wav_bytes,
        )

        return Response(
            content=wav_bytes,
            media_type="audio/wav",
            headers={
                "Cache-Control": "no-cache",
                "X-TTS-Provider": "qwen3",
                "Access-Control-Allow-Origin": "*",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Voice clone failed: {e}")
        raise HTTPException(500, f"Voice cloning failed: {str(e)}")


# ---- TTS Config Endpoints ------------------------------------------------


@router.get("/config")
async def get_tts_config() -> dict[str, Any]:
    """
    Get current Qwen3-TTS generation configuration.
    Requires the Qwen3-TTS server to be running.

    Returns keys: temperature, top_p, top_k,
                  repetition_penalty, max_new_tokens, do_sample, seed
    """
    try:
        qwen3 = _get_qwen3()
        if not await qwen3.is_available():
            return {
                "success": False,
                "error": "Qwen3-TTS server not reachable",
                "config": None,
            }
        config = await qwen3.get_config()
        return {"success": True, "config": config}
    except Exception as e:
        return {"success": False, "error": str(e), "config": None}


@router.post("/config")
async def update_tts_config(updates: dict[str, Any]) -> dict[str, Any]:
    """
    Update Qwen3-TTS generation configuration.

    Accepts a JSON body with any of:
      temperature, top_p, top_k, repetition_penalty,
      max_new_tokens, do_sample, seed
    """
    try:
        qwen3 = _get_qwen3()
        if not await qwen3.is_available():
            raise HTTPException(503, "Qwen3-TTS server not reachable")

        config = await qwen3.update_config(updates)
        return {"success": True, "config": config}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to update TTS config: {str(e)}")
