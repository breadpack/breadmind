"""Tests for voice input foundation tools."""
from __future__ import annotations
import sys
from unittest.mock import patch

from breadmind.tools.voice_input import voice_listen, voice_speak


async def test_listen_no_speech_recognition():
    with patch.dict(sys.modules, {"speech_recognition": None}):
        result = await voice_listen()
    assert "pip install" in result or "SpeechRecognition" in result


async def test_speak_no_pyttsx3():
    with patch.dict(sys.modules, {"pyttsx3": None}):
        result = await voice_speak("hello", engine="system")
    assert "pip install" in result or "pyttsx3" in result
