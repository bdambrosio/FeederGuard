#!/usr/bin/env python3
"""
Squirrel detector: WiFi IP camera → Qwen2.5-VL-7B via SGLang.
Captures a frame every couple of seconds and asks the model what it sees.
"""

import cv2
import base64
import requests
import time
import sys
import os
from openai import OpenAI
import pygame
from dotenv import load_dotenv

# Load environment variables and initialize audio
load_dotenv()

# Set audio output to headphones (card 2) before initializing pygame
os.environ['SDL_AUDIODRIVER'] = 'alsa'
os.environ['AUDIODEV'] = 'hw:3,0'  # card 3, device 0 = WM8960

# Debug audio devices
print("[Audio] Initializing pygame mixer...")
pygame.mixer.init()
print(f"[Audio] Mixer initialized: {pygame.mixer.get_init()}")

# List available audio devices using SDL
import subprocess
try:
    result = subprocess.run(['aplay', '-l'], capture_output=True, text=True)
    print("[Audio] Available ALSA playback devices:")
    print(result.stdout)
except Exception as e:
    print(f"[Audio] Could not list ALSA devices: {e}")

# Show current default device
try:
    result = subprocess.run(['pactl', 'get-default-sink'], capture_output=True, text=True)
    print(f"[Audio] PulseAudio default sink: {result.stdout.strip()}")
except Exception as e:
    print(f"[Audio] Could not get PulseAudio default: {e}")

# OpenAI client for text-to-speech
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SGLANG_URL = "http://192.168.68.76:6000/v1/chat/completions"
MODEL = "Qwen/Qwen2.5-VL-7B-Instruct"
INTERVAL = 2  # seconds between checks

# WiFi camera settings
CAMERA_IP = "192.168.68.55"
CAMERA_USER = "FeederGuard"
CAMERA_PASSWORD = "1947NWnw!"

# Common RTSP paths to try
RTSP_PATHS = ["/stream1", "/stream2", "/live", "/h264", "/cam/realmonitor", "/"]
# Common HTTP MJPEG paths
HTTP_PATHS = ["/video", "/mjpeg", "/stream", "/cam.mjpg", "/snapshot.jpg"]

PROMPT = """Look at this bird feeder camera image. Is there a squirrel or pigeon visible? 
songbirds, mourning doves, and crows are allowed, do NOT report them. 
Reply with exactly one line in this format:
SQUIRREL/PIGEON: YES or SQUIRREL/PIGEON: NO
Then a second line with a brief description of what you see."""

DESCRIBE_PROMPT = """Describe this bird feeder camera scene in detail. Include:
- What animals or birds are visible
- Their positions and activities
- The overall condition of the feeder
- Weather or lighting conditions
- Any notable events or behaviors
Be concise but informative."""


def encode_frame(frame):
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buf).decode("utf-8")


def ask_model(b64_image, prompt=PROMPT, max_tokens=100):
    resp = requests.post(
        SGLANG_URL,
        json={
            "model": MODEL,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64_image}"
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def describe_scene(b64_image):
    """Get a detailed description of the scene."""
    return ask_model(b64_image, prompt=DESCRIBE_PROMPT, max_tokens=200)


def speak(text):
    """Convert text to speech and play it."""
    try:
        print(f"[TTS] Starting speech synthesis for {len(text)} chars...")
        with openai_client.audio.speech.with_streaming_response.create(
            model="tts-1",
            voice="alloy",
            input=text
        ) as response:
            print("[TTS] Got response, streaming to file...")
            response.stream_to_file('response.mp3')
        print("[TTS] File written, loading into pygame...")
        pygame.mixer.music.load('response.mp3')
        print("[TTS] Playing audio...")
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
        print("[TTS] Playback complete.")
    except Exception as e:
        print(f"[TTS] Speech failed: {e}")
        import traceback
        traceback.print_exc()


def main():
    cam = None
    
    # Try RTSP streams first
    print(f"Connecting to camera at {CAMERA_IP}...")
    for path in RTSP_PATHS:
        url = f"rtsp://{CAMERA_USER}:{CAMERA_PASSWORD}@{CAMERA_IP}:554{path}"
        print(f"  Trying RTSP: {url}")
        cam = cv2.VideoCapture(url)
        if cam.isOpened():
            # Test if we can actually read a frame
            ret, _ = cam.read()
            if ret:
                print(f"  ✓ Connected via RTSP: {path}")
                break
        cam.release()
        cam = None
    
    # Fallback to HTTP MJPEG if RTSP fails
    if cam is None or not cam.isOpened():
        print("RTSP failed, trying HTTP MJPEG...")
        for path in HTTP_PATHS:
            url = f"http://{CAMERA_USER}:{CAMERA_PASSWORD}@{CAMERA_IP}{path}"
            print(f"  Trying HTTP: {url}")
            cam = cv2.VideoCapture(url)
            if cam.isOpened():
                ret, _ = cam.read()
                if ret:
                    print(f"  ✓ Connected via HTTP: {path}")
                    break
            cam.release()
            cam = None
    
    if cam is None or not cam.isOpened():
        print(f"\nCannot open camera at {CAMERA_IP}")
        print("Tried multiple RTSP and HTTP paths. Check camera documentation for correct stream URL.")
        sys.exit(1)
    
    # Set buffer size to reduce latency
    cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    print("Watching for squirrels... (Ctrl+C to stop)\n")

    try:
        while True:
            ret, frame = cam.read()
            if not ret:
                print("Frame grab failed, retrying...")
                time.sleep(1)
                continue

            b64 = encode_frame(frame)
            try:
                answer = ask_model(b64)
                timestamp = time.strftime("%H:%M:%S")
                print(f"[{timestamp}] {answer}\n")

                # Get detailed scene description
                try:
                    description = describe_scene(b64)
                    print(f"  Scene: {description}\n")
                    speak(description)
                except requests.RequestException:
                    pass  # Don't fail if description fails

                answer_upper = answer.upper()
                if "YES" in answer_upper.split("SQUIRREL")[-1][:10]:
                    print("  >>> SQUIRREL DETECTED! <<<\n")
                    speak("Alert! Squirrel detected at the bird feeder!")
                    # trigger deterrent here
                elif "PIGEON" in answer_upper and "YES" in answer_upper.split("PIGEON")[-1][:10]:
                    print("  >>> PIGEON DETECTED! <<<\n")
                    speak("Alert! Pigeon detected at the bird feeder!")

            except requests.RequestException as e:
                print(f"Model request failed: {e}")

            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        cam.release()


if __name__ == "__main__":
    main()