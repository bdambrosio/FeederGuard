"""Text-to-speech and audio playback for Who's That?"""

import os
import threading
import queue
import tempfile
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI

from config import AUDIO_DEVICE, TTS_VOICE, TTS_MODEL, APP_DIR

# Set audio output before importing pygame
os.environ['SDL_AUDIODRIVER'] = 'alsa'
os.environ['AUDIODEV'] = AUDIO_DEVICE

import pygame


class TTSEngine:
    """Text-to-speech engine with queued playback."""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._openai_client: Optional[OpenAI] = None
        self._mixer_initialized = False
        self._temp_dir = APP_DIR / "audio_temp"
        self._volume = 1.0

    def start(self):
        """Initialize TTS engine and start playback thread."""
        if self._running:
            return

        # Initialize OpenAI client (dotenv loads .env into os.environ, so this checks both)
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("[TTS] Warning: OPENAI_API_KEY not found in environment or .env, TTS will be disabled")
        else:
            self._openai_client = OpenAI(api_key=api_key)
            print("[TTS] OpenAI client initialized")

        # Initialize pygame mixer
        try:
            print("[TTS] Initializing pygame mixer...")
            pygame.mixer.init()
            self._mixer_initialized = True
            print(f"[TTS] Mixer initialized: {pygame.mixer.get_init()}")
        except Exception as e:
            print(f"[TTS] Failed to initialize mixer: {e}")
            self._mixer_initialized = False

        # Create temp directory
        self._temp_dir.mkdir(exist_ok=True)

        # Start playback thread
        self._running = True
        self._thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the TTS engine."""
        self._running = False
        self._queue.put(None)  # Signal to stop
        if self._thread:
            self._thread.join(timeout=2)
        if self._mixer_initialized:
            pygame.mixer.quit()

    def speak(self, text: str, blocking: bool = False):
        """
        Queue text for speech synthesis and playback.

        Args:
            text: Text to speak
            blocking: If True, wait for playback to complete
        """
        if not text or not text.strip():
            return

        if blocking:
            self._synthesize_and_play(text)
        else:
            self._queue.put(text)

    def set_volume(self, volume: float):
        """Set playback volume (0.0 to 1.0)."""
        self._volume = max(0.0, min(1.0, volume))
        if self._mixer_initialized:
            pygame.mixer.music.set_volume(self._volume)

    def _playback_loop(self):
        """Background thread for processing TTS queue."""
        while self._running:
            try:
                text = self._queue.get(timeout=1)
                if text is None:
                    break
                self._synthesize_and_play(text)
            except queue.Empty:
                continue

    def synthesize(self, text: str) -> Optional[bytes]:
        """
        Synthesize speech and return MP3 bytes.

        Args:
            text: Text to synthesize

        Returns:
            MP3 audio bytes or None if synthesis failed
        """
        if not self._openai_client:
            print(f"[TTS] No OpenAI client, cannot synthesize: {text[:50]}...")
            return None

        try:
            print(f"[TTS] Synthesizing: {text[:50]}...")
            response = self._openai_client.audio.speech.create(
                model=TTS_MODEL,
                voice=TTS_VOICE,
                input=text
            )
            print("[TTS] Synthesis complete")
            return response.content

        except Exception as e:
            print(f"[TTS] Error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _synthesize_and_play(self, text: str):
        """Synthesize speech and play it locally (legacy, for Pi speaker)."""
        audio_data = self.synthesize(text)
        if not audio_data:
            return

        if not self._mixer_initialized:
            print(f"[TTS] Mixer not initialized, cannot play locally")
            return

        try:
            # Write to temp file for pygame
            temp_file = self._temp_dir / f"tts_{int(time.time() * 1000)}.mp3"
            temp_file.write_bytes(audio_data)

            # Play the audio
            pygame.mixer.music.set_volume(self._volume)
            pygame.mixer.music.load(str(temp_file))
            pygame.mixer.music.play()

            # Wait for playback to complete
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)

            # Clean up temp file
            try:
                temp_file.unlink()
            except OSError:
                pass

            print("[TTS] Playback complete")

        except Exception as e:
            print(f"[TTS] Error: {e}")
            import traceback
            traceback.print_exc()

    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        if self._mixer_initialized:
            return pygame.mixer.music.get_busy()
        return False

    def stop_playback(self):
        """Stop current playback."""
        if self._mixer_initialized:
            pygame.mixer.music.stop()


# Global TTS instance
tts = TTSEngine()
