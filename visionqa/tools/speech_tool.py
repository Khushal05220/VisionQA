"""
Speech Tool for VisionQA
Handles speech-to-text and text-to-speech functionality.
Uses browser Web Speech API via frontend with server-side processing support.
"""

import logging
from typing import Any

logger = logging.getLogger("visionqa.tools.speech")


class SpeechTool:
    """
    Speech processing tool.

    Primary speech-to-text is handled by the browser's Web Speech API on the frontend.
    This tool provides server-side processing, formatting, and optional
    Google Cloud Speech-to-Text integration.
    """

    def __init__(self, language: str = "en-US"):
        self._language = language
        self._cloud_client = None

        try:
            from google.cloud import speech
            self._cloud_client = speech.SpeechClient()
            logger.info("Google Cloud Speech-to-Text initialized")
        except Exception as e:
            logger.info(
                f"Cloud Speech-to-Text not available, using browser Web Speech API: {e}"
            )

    async def process_voice_command(self, transcript: str) -> dict[str, Any]:
        """
        Process a voice command transcript.
        Cleans up and normalizes the text for agent consumption.

        Args:
            transcript: Raw transcript from speech-to-text.

        Returns:
            Processed command with intent classification.
        """
        # Clean and normalize
        cleaned = transcript.strip().lower()

        # Classify intent
        intent = self._classify_intent(cleaned)

        return {
            "status": "success",
            "original": transcript,
            "cleaned": cleaned,
            "intent": intent,
            "language": self._language,
        }

    def _classify_intent(self, text: str) -> str:
        """Classify the user's intent from voice command."""
        intent_keywords = {
            "open_page": ["open", "go to", "navigate", "visit", "load"],
            "test_page": ["test", "check", "verify", "validate", "inspect"],
            "create_plan": ["create test", "make test", "generate test", "plan"],
            "save_tests": ["save", "store", "persist", "export"],
            "run_plan": ["run", "execute", "start", "begin", "launch"],
            "analyze": ["analyze", "analyse", "look at", "examine", "review"],
            "screenshot": ["screenshot", "capture", "snap", "photo"],
            "help": ["help", "what can", "how to", "instructions"],
        }

        for intent, keywords in intent_keywords.items():
            for keyword in keywords:
                if keyword in text:
                    return intent

        return "general"

    async def transcribe_audio(self, audio_bytes: bytes) -> dict[str, Any]:
        """
        Transcribe audio bytes using Google Cloud Speech-to-Text.
        Fallback when browser Web Speech API is not available.

        Args:
            audio_bytes: Raw audio data.

        Returns:
            Transcription result.
        """
        if not self._cloud_client:
            return {
                "status": "error",
                "error": "Cloud Speech-to-Text not configured. Use browser Web Speech API.",
            }

        try:
            from google.cloud import speech

            audio = speech.RecognitionAudio(content=audio_bytes)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
                sample_rate_hertz=48000,
                language_code=self._language,
                enable_automatic_punctuation=True,
            )

            response = self._cloud_client.recognize(config=config, audio=audio)

            if response.results:
                transcript = response.results[0].alternatives[0].transcript
                confidence = response.results[0].alternatives[0].confidence
                return {
                    "status": "success",
                    "transcript": transcript,
                    "confidence": confidence,
                }
            else:
                return {"status": "success", "transcript": "", "confidence": 0.0}

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return {"status": "error", "error": str(e)}

    async def text_to_speech(self, text: str) -> dict[str, Any]:
        """
        Convert text to speech audio.
        Primary TTS is handled by browser's speechSynthesis API.
        This provides server-side fallback via Google Cloud TTS.

        Args:
            text: Text to convert to speech.

        Returns:
            Audio data or instruction for browser-side TTS.
        """
        try:
            from google.cloud import texttospeech

            client = texttospeech.TextToSpeechClient()
            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice = texttospeech.VoiceSelectionParams(
                language_code=self._language,
                ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL,
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
            )

            response = client.synthesize_speech(
                input=synthesis_input, voice=voice, audio_config=audio_config
            )

            import base64
            audio_b64 = base64.b64encode(response.audio_content).decode("utf-8")

            return {
                "status": "success",
                "audio_base64": audio_b64,
                "content_type": "audio/mp3",
            }
        except Exception:
            # Fallback: instruct frontend to use browser TTS
            return {
                "status": "browser_tts",
                "text": text,
                "message": "Use browser speechSynthesis API",
            }


# Global instance
_speech_tool: SpeechTool | None = None


def get_speech_tool() -> SpeechTool:
    """Get or create the global speech tool."""
    global _speech_tool
    if _speech_tool is None:
        from visionqa.backend.config import get_settings
        settings = get_settings()
        _speech_tool = SpeechTool(language=settings.speech_language)
    return _speech_tool
