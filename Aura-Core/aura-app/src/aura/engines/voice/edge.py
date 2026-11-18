"""
Edge-TTS Voice Engine

Provides streaming text-to-speech using Microsoft Edge's TTS service.
This is a cloud-based solution that requires no local VRAM.
"""

import logging
from typing import AsyncGenerator

import edge_tts

logger = logging.getLogger(__name__)


class EdgeEngine:
    """
    Edge-TTS engine for converting text to speech with streaming support.
    
    This engine uses Microsoft's Edge TTS service to generate natural-sounding
    speech without requiring local GPU resources.
    """
    
    def __init__(self) -> None:
        """Initialize the Edge-TTS engine."""
        self.logger = logger
        self.logger.info("Edge-TTS Engine initialized")
    
    async def stream_audio(
        self,
        text: str,
        voice: str = "en-US-AriaNeural"
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream audio bytes from text using Edge-TTS.
        
        Args:
            text: The text to convert to speech
            voice: The voice to use (default: en-US-AriaNeural)
            
        Yields:
            Audio data chunks as bytes
            
        Example voices:
            - en-US-AriaNeural (Female, friendly)
            - en-US-GuyNeural (Male, casual)
            - en-US-JennyNeural (Female, assistant)
            - en-GB-SoniaNeural (British Female)
            - en-GB-RyanNeural (British Male)
        """
        self.logger.info(f"Generating speech for text: '{text[:50]}...' with voice: {voice}")
        
        try:
            # Create communication object
            communicate = edge_tts.Communicate(text, voice)
            
            # Stream audio chunks
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
                    
            self.logger.info("Speech generation completed successfully")
            
        except Exception as e:
            self.logger.error(f"Error generating speech: {e}")
            raise
    
    @staticmethod
    def get_available_voices() -> list[str]:
        """
        Get a list of commonly used Edge-TTS voices.
        
        Returns:
            List of voice identifiers
        """
        return [
            "en-US-AriaNeural",      # Female, friendly
            "en-US-GuyNeural",       # Male, casual
            "en-US-JennyNeural",     # Female, assistant
            "en-US-EricNeural",      # Male, news
            "en-US-MichelleNeural",  # Female, expressive
            "en-GB-SoniaNeural",     # British Female
            "en-GB-RyanNeural",      # British Male
            "en-AU-NatashaNeural",   # Australian Female
            "en-AU-WilliamNeural",   # Australian Male
        ]

