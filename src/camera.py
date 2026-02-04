"""Camera capture thread and MJPEG streaming for Who's That?"""

import cv2
import threading
import time
import base64
import os
from typing import Optional, Generator
import numpy as np

# Suppress FFmpeg/libav warnings (SEI truncation spam from H.264 streams)
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"


from config import (
    CAMERA_IP, CAMERA_USER, CAMERA_PASSWORD,
    CAMERA_URL_OVERRIDE, RTSP_PATHS, HTTP_PATHS
)


class CameraThread:
    """Thread-safe camera capture with MJPEG streaming support."""

    def __init__(self):
        self._frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._cam: Optional[cv2.VideoCapture] = None
        self._connected = False
        self._last_error: Optional[str] = None
        self._reconnect_interval = 5  # seconds

    def start(self):
        """Start the camera capture thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the camera capture thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._cam:
            self._cam.release()
            self._cam = None

    def _connect(self) -> bool:
        """Attempt to connect to the camera."""
        # Use override URL if provided
        if CAMERA_URL_OVERRIDE:
            print(f"[Camera] Using override URL: {CAMERA_URL_OVERRIDE}")
            self._cam = cv2.VideoCapture(CAMERA_URL_OVERRIDE)
            if self._cam.isOpened():
                ret, _ = self._cam.read()
                if ret:
                    self._cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    self._connected = True
                    self._last_error = None
                    print("[Camera] Connected via override URL")
                    return True
            self._cam.release()

        # Try RTSP streams
        print(f"[Camera] Connecting to camera at {CAMERA_IP}...")
        for path in RTSP_PATHS:
            url = f"rtsp://{CAMERA_USER}:{CAMERA_PASSWORD}@{CAMERA_IP}:554{path}"
            print(f"[Camera]   Trying RTSP: {path}")
            self._cam = cv2.VideoCapture(url)
            if self._cam.isOpened():
                ret, _ = self._cam.read()
                if ret:
                    self._cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    self._connected = True
                    self._last_error = None
                    print(f"[Camera] Connected via RTSP: {path}")
                    return True
            self._cam.release()

        # Fallback to HTTP MJPEG
        print("[Camera] RTSP failed, trying HTTP MJPEG...")
        for path in HTTP_PATHS:
            url = f"http://{CAMERA_USER}:{CAMERA_PASSWORD}@{CAMERA_IP}{path}"
            print(f"[Camera]   Trying HTTP: {path}")
            self._cam = cv2.VideoCapture(url)
            if self._cam.isOpened():
                ret, _ = self._cam.read()
                if ret:
                    self._cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    self._connected = True
                    self._last_error = None
                    print(f"[Camera] Connected via HTTP: {path}")
                    return True
            self._cam.release()

        self._connected = False
        self._last_error = f"Cannot connect to camera at {CAMERA_IP}"
        print(f"[Camera] {self._last_error}")
        return False

    def _capture_loop(self):
        """Main capture loop running in background thread."""
        # Suppress FFmpeg stderr spam in this thread only
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        os.close(devnull)

        while self._running:
            # Attempt connection if not connected
            if not self._connected or self._cam is None:
                if not self._connect():
                    time.sleep(self._reconnect_interval)
                    continue

            # Read frame
            ret, frame = self._cam.read()
            if not ret:
                print("[Camera] Frame grab failed, reconnecting...")
                self._connected = False
                self._cam.release()
                self._cam = None
                time.sleep(1)
                continue

            # Store frame thread-safely
            with self._frame_lock:
                self._frame = frame.copy()

            # Small delay to prevent CPU spinning
            time.sleep(0.033)  # ~30fps max

    def get_frame(self) -> Optional[np.ndarray]:
        """Get the latest frame (thread-safe)."""
        with self._frame_lock:
            if self._frame is not None:
                return self._frame.copy()
            return None

    def get_frame_jpeg(self, quality: int = 85) -> Optional[bytes]:
        """Get the latest frame as JPEG bytes."""
        frame = self.get_frame()
        if frame is None:
            return None
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes()

    def get_frame_base64(self, quality: int = 85) -> Optional[str]:
        """Get the latest frame as base64-encoded JPEG."""
        jpeg = self.get_frame_jpeg(quality)
        if jpeg is None:
            return None
        return base64.b64encode(jpeg).decode("utf-8")

    def generate_mjpeg(self) -> Generator[bytes, None, None]:
        """Generate MJPEG stream for Flask response."""
        while self._running:
            jpeg = self.get_frame_jpeg()
            if jpeg is None:
                # Send a placeholder frame when no camera
                jpeg = self._get_no_signal_frame()

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            )
            time.sleep(0.033)  # ~30fps

    def _get_no_signal_frame(self) -> bytes:
        """Generate a 'no signal' placeholder frame."""
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:] = (40, 40, 40)  # Dark gray background

        # Add "No Signal" text
        text = "No Signal"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1.5
        thickness = 3
        text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
        x = (640 - text_size[0]) // 2
        y = (480 + text_size[1]) // 2
        cv2.putText(img, text, (x, y), font, font_scale, (100, 100, 100), thickness)

        if self._last_error:
            err_font_scale = 0.5
            err_text_size = cv2.getTextSize(self._last_error, font, err_font_scale, 1)[0]
            err_x = (640 - err_text_size[0]) // 2
            cv2.putText(img, self._last_error, (err_x, y + 40), font, err_font_scale, (80, 80, 80), 1)

        _, buf = cv2.imencode(".jpg", img)
        return buf.tobytes()

    @property
    def is_connected(self) -> bool:
        """Check if camera is connected."""
        return self._connected

    @property
    def last_error(self) -> Optional[str]:
        """Get the last error message."""
        return self._last_error


# Global camera instance
camera = CameraThread()
