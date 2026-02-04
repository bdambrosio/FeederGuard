"""Configuration for Who's That? application."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
APP_DIR = Path(__file__).parent
PHOTOS_DIR = Path(os.getenv("PHOTOS_DIR", Path.home() / "photos"))
CONTACT_SHEET_PATH = PHOTOS_DIR / ".contact_sheet.jpg"

# Camera settings
CAMERA_IP = os.getenv("CAMERA_IP", "192.168.68.55")
CAMERA_USER = os.getenv("CAMERA_USER", "FeederGuard")
CAMERA_PASSWORD = os.getenv("CAMERA_PASSWORD", "")
CAMERA_URL_OVERRIDE = os.getenv("CAMERA_URL_OVERRIDE", "")

# RTSP paths to try
RTSP_PATHS = ["/stream1", "/stream2", "/live", "/h264", "/cam/realmonitor", "/"]
# HTTP MJPEG paths to try
HTTP_PATHS = ["/video", "/mjpeg", "/stream", "/cam.mjpg", "/snapshot.jpg"]

# VLM settings
VLM_URL = os.getenv("VLM_URL", "http://192.168.68.76:6000/v1/chat/completions")
VLM_MODEL = os.getenv("VLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")
VLM_TIMEOUT = int(os.getenv("VLM_TIMEOUT", "30"))

# Audio settings
AUDIO_DEVICE = os.getenv("AUDIO_DEVICE", "hw:3,0")
TTS_VOICE = os.getenv("TTS_VOICE", "nova")
TTS_MODEL = os.getenv("TTS_MODEL", "tts-1")

# Contact sheet settings
THUMBNAIL_SIZE = 256
CONTACT_SHEET_MAX_WIDTH = 1024
LABEL_FONT_SIZE = 24

# Server settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# VLM Prompts
DESCRIBE_PROMPT = """Describe what you see in this camera image. Include who or what is
present, what they're doing, and anything interesting about the scene.
Be friendly and fun - you're talking to kids!"""

IDENTIFY_PROMPT = """The first image is a reference sheet of people and pets I know,
with their names labeled below each photo.

The second image is a live camera photo.

Look at the live photo and tell me:
1. Do you recognize anyone or any pet from the reference sheet?
   If so, say who and describe what they're doing.
2. Describe anyone or anything else interesting in the scene.

Be friendly and conversational - you're talking to kids!
If you're not sure about an identification, say so rather than guessing."""


def get_runtime_config():
    """Get current runtime configuration (for settings endpoint)."""
    return {
        "camera_url_override": CAMERA_URL_OVERRIDE,
        "vlm_url": VLM_URL,
        "tts_voice": TTS_VOICE,
        "photos_dir": str(PHOTOS_DIR),
    }


def update_runtime_config(updates):
    """Update runtime configuration. Returns updated config."""
    global CAMERA_URL_OVERRIDE, VLM_URL, TTS_VOICE

    if "camera_url_override" in updates:
        CAMERA_URL_OVERRIDE = updates["camera_url_override"]
    if "vlm_url" in updates:
        VLM_URL = updates["vlm_url"]
    if "tts_voice" in updates:
        TTS_VOICE = updates["tts_voice"]

    return get_runtime_config()
