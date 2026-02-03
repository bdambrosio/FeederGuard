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

SGLANG_URL = "http://localhost:6000/v1/chat/completions"
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
                except requests.RequestException:
                    pass  # Don't fail if description fails

                if "YES" in answer.upper().split("SQUIRREL")[-1][:10]:
                    print("  >>> SQUIRREL DETECTED! <<<\n")
                    # trigger deterrent here

            except requests.RequestException as e:
                print(f"Model request failed: {e}")

            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        cam.release()


if __name__ == "__main__":
    main()