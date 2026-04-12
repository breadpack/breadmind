"""Voice input foundation. Requires speech_recognition package."""
from __future__ import annotations
import logging
from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)

@tool("Record and transcribe voice input", read_only=True)
async def voice_listen(duration: int = 5, language: str = "en") -> str:
    """Listen for voice input and transcribe. Requires speech_recognition + pyaudio."""
    try:
        import speech_recognition as sr
    except ImportError:
        return "Voice input requires: pip install SpeechRecognition pyaudio"

    recognizer = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.listen(source, timeout=duration, phrase_time_limit=duration)

        text = recognizer.recognize_google(audio, language=language)
        return f"Transcribed: {text}"
    except sr.UnknownValueError:
        return "Could not understand audio"
    except sr.RequestError as e:
        return f"Transcription service error: {e}"
    except Exception as e:
        return f"Voice input error: {e}"

@tool("Text-to-speech: speak text aloud", read_only=True)
async def voice_speak(text: str, engine: str = "system") -> str:
    """Speak text. engine: 'system' (pyttsx3) or 'google' (gTTS)."""
    if engine == "system":
        try:
            import pyttsx3
            e = pyttsx3.init()
            e.say(text)
            e.runAndWait()
            return f"Spoke: {text[:50]}..."
        except ImportError:
            return "System TTS requires: pip install pyttsx3"
    elif engine == "google":
        try:
            from gtts import gTTS
            import tempfile
            tts = gTTS(text=text)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tts.save(f.name)
                return f"Audio saved: {f.name}"
        except ImportError:
            return "Google TTS requires: pip install gTTS"
    return f"Unknown engine: {engine}"
