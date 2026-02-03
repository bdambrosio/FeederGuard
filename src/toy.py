#!/usr/bin/env python3
"""
Squirrel detector: USB webcam → Qwen2.5-VL-7B via SGLang.
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

PROMPT = """Look at this bird feeder camera image. Is there a squirrel visible? 
Reply with exactly one line in this format:
SQUIRREL: YES or SQUIRREL: NO
Then a second line with a brief description of what you see."""


def encode_frame(frame):
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buf).decode("utf-8")


def ask_model(b64_image):
    resp = requests.post(
        SGLANG_URL,
        json={
            "model": MODEL,
            "max_tokens": 100,
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
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def main():
    cam = cv2.VideoCapture(0)
    if not cam.isOpened():
        print("Cannot open webcam")
        sys.exit(1)

    # set a modest resolution — no need for 4K
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

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