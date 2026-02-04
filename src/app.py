#!/usr/bin/env python3
"""Who's That? - A kid-friendly photo identification app using VLM."""

import atexit
from flask import Flask, Response, jsonify, request, render_template, send_file
import cv2
import numpy as np
import io

from config import HOST, PORT, DEBUG, APP_DIR, get_runtime_config, update_runtime_config
from camera import camera
from audio import tts
from library import library
from vlm import describe_scene, identify_subjects, chat_followup, build_initial_conversation, VLMError

app = Flask(__name__)

# Store current conversation state (in production, use sessions or Redis)
current_conversation = {
    "contact_sheet_b64": None,
    "frame_b64": None,
    "history": []
}


@app.route("/")
def index():
    """Serve the main page."""
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    """Stream MJPEG video from the camera."""
    return Response(
        camera.generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/snapshot", methods=["POST"])
def snapshot():
    """Capture and return a single frame as JPEG."""
    jpeg = camera.get_frame_jpeg()
    if jpeg is None:
        return jsonify({"error": "No camera frame available"}), 503

    return Response(jpeg, mimetype="image/jpeg")


@app.route("/describe", methods=["POST"])
def describe():
    """One-shot scene description with TTS."""
    import base64
    data = request.get_json()

    # Get frame from request (browser camera) or fall back to Pi camera
    if data and "frame" in data:
        frame_b64 = data["frame"]
    else:
        frame_b64 = camera.get_frame_base64()

    if frame_b64 is None:
        return jsonify({"error": "No camera frame available"}), 503

    try:
        description = describe_scene(frame_b64)
        # Generate audio for browser playback
        audio_data = tts.synthesize(description)
        audio_b64 = None
        if audio_data:
            audio_b64 = base64.b64encode(audio_data).decode("utf-8")
        return jsonify({"description": description, "audio": audio_b64})
    except VLMError as e:
        return jsonify({"error": str(e)}), 503


@app.route("/enroll", methods=["POST"])
def enroll():
    """Enroll a photo with a name label."""
    import base64
    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "Name is required"}), 400

    name = data["name"].strip()
    if not name:
        return jsonify({"error": "Name cannot be empty"}), 400

    # Get frame from request (browser camera) or fall back to Pi camera
    if data and "frame" in data:
        # Decode base64 frame to numpy array
        frame_bytes = base64.b64decode(data["frame"])
        frame_array = np.frombuffer(frame_bytes, dtype=np.uint8)
        frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
    else:
        frame = camera.get_frame()

    if frame is None:
        return jsonify({"error": "No camera frame available"}), 503

    result = library.enroll(name, frame)

    # Generate audio for browser playback
    audio_data = tts.synthesize(result["message"])
    if audio_data:
        result["audio"] = base64.b64encode(audio_data).decode("utf-8")

    return jsonify(result)


@app.route("/library", methods=["GET"])
def get_library():
    """List all enrolled subjects."""
    subjects = library.list_subjects()
    return jsonify({"subjects": subjects})


@app.route("/library/<name>/thumbnail", methods=["GET"])
def get_thumbnail(name):
    """Get thumbnail for a subject."""
    size = request.args.get("size", 150, type=int)
    thumb = library.get_subject_thumbnail(name, size)
    if thumb is None:
        return jsonify({"error": "Subject not found"}), 404

    return Response(thumb, mimetype="image/jpeg")


@app.route("/library/<name>/photo/<photo_id>", methods=["GET"])
def get_photo(name, photo_id):
    """Get a specific photo."""
    photo = library.get_photo(name, photo_id)
    if photo is None:
        return jsonify({"error": "Photo not found"}), 404

    return Response(photo, mimetype="image/jpeg")


@app.route("/library/<name>", methods=["DELETE"])
def delete_subject(name):
    """Delete a subject entirely."""
    import base64
    result = library.delete_subject(name)
    if result["success"]:
        audio_data = tts.synthesize(result["message"])
        if audio_data:
            result["audio"] = base64.b64encode(audio_data).decode("utf-8")
    return jsonify(result)


@app.route("/library/<name>/<photo_id>", methods=["DELETE"])
def delete_photo(name, photo_id):
    """Delete a single photo."""
    result = library.delete_photo(name, photo_id)
    return jsonify(result)


@app.route("/library/clear", methods=["POST"])
def clear_library():
    """Clear all enrolled subjects (danger zone)."""
    result = library.clear_all()
    return jsonify(result)


@app.route("/identify", methods=["POST"])
def identify():
    """Identify subjects in current frame using contact sheet."""
    import base64 as b64
    global current_conversation

    data = request.get_json()

    # Check if we have any enrolled subjects
    if not library.has_subjects():
        message = "I don't know anyone yet! Let's meet some friends first."
        return jsonify({
            "error": message,
            "redirect_to_meet": True
        }), 400

    # Get contact sheet and current frame
    contact_sheet_b64 = library.get_contact_sheet_base64()
    if contact_sheet_b64 is None:
        return jsonify({"error": "Could not generate contact sheet"}), 500

    # Get frame from request (browser camera) or fall back to Pi camera
    if data and "frame" in data:
        frame_b64 = data["frame"]
    else:
        frame_b64 = camera.get_frame_base64()

    if frame_b64 is None:
        return jsonify({"error": "No camera frame available"}), 503

    try:
        response = identify_subjects(contact_sheet_b64, frame_b64)

        # Store conversation state for follow-ups
        current_conversation = {
            "contact_sheet_b64": contact_sheet_b64,
            "frame_b64": frame_b64,
            "history": build_initial_conversation(contact_sheet_b64, frame_b64, response)
        }

        # Generate audio for browser playback
        audio_data = tts.synthesize(response)
        audio_b64 = None
        if audio_data:
            audio_b64 = b64.b64encode(audio_data).decode("utf-8")

        return jsonify({
            "response": response,
            "has_conversation": True,
            "audio": audio_b64
        })

    except VLMError as e:
        return jsonify({"error": str(e)}), 503


@app.route("/chat", methods=["POST"])
def chat():
    """Follow-up question about current scene."""
    import base64
    global current_conversation

    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Message is required"}), 400

    message = data["message"].strip()
    if not message:
        return jsonify({"error": "Message cannot be empty"}), 400

    # Check if we have a conversation context
    if not current_conversation["history"]:
        return jsonify({
            "error": "No active conversation. Try identifying someone first!"
        }), 400

    try:
        response, updated_history = chat_followup(
            current_conversation["contact_sheet_b64"],
            current_conversation["frame_b64"],
            message,
            current_conversation["history"]
        )

        # Update conversation history
        current_conversation["history"] = updated_history

        # Generate audio for browser playback
        audio_data = tts.synthesize(response)
        audio_b64 = None
        if audio_data:
            audio_b64 = base64.b64encode(audio_data).decode("utf-8")

        return jsonify({"response": response, "audio": audio_b64})

    except VLMError as e:
        return jsonify({"error": str(e)}), 503


@app.route("/chat/reset", methods=["POST"])
def reset_chat():
    """Reset the current conversation."""
    global current_conversation
    current_conversation = {
        "contact_sheet_b64": None,
        "frame_b64": None,
        "history": []
    }
    return jsonify({"success": True})


@app.route("/settings", methods=["GET"])
def get_settings():
    """Get current configuration."""
    config = get_runtime_config()
    config["camera_connected"] = camera.is_connected
    config["has_subjects"] = library.has_subjects()
    config["subject_count"] = len(library.list_subjects())
    return jsonify(config)


@app.route("/settings", methods=["POST"])
def update_settings():
    """Update configuration."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    config = update_runtime_config(data)
    return jsonify(config)


@app.route("/tts/volume", methods=["POST"])
def set_volume():
    """Set TTS volume."""
    data = request.get_json()
    if not data or "volume" not in data:
        return jsonify({"error": "Volume is required"}), 400

    volume = float(data["volume"])
    tts.set_volume(volume)
    return jsonify({"volume": volume})


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "camera_connected": camera.is_connected,
        "has_subjects": library.has_subjects()
    })


def cleanup():
    """Cleanup on shutdown."""
    print("[App] Shutting down...")
    camera.stop()
    tts.stop()


if __name__ == "__main__":
    print("[App] Starting Who's That?...")
    print(f"[App] Will serve on http://{HOST}:{PORT}")

    # Register cleanup
    atexit.register(cleanup)

    # Start camera thread (non-blocking, runs in background)
    print("[App] Starting camera thread...")
    camera.start()

    # Start TTS engine
    print("[App] Starting TTS engine...")
    tts.start()

    # Run Flask app with HTTPS (required for browser camera access)
    cert_file = APP_DIR.parent / "cert.pem"
    key_file = APP_DIR.parent / "key.pem"

    if cert_file.exists() and key_file.exists():
        print(f"[App] *** Server starting on https://{HOST}:{PORT} ***")
        print("[App] Using mkcert certificate")
        app.run(host=HOST, port=PORT, debug=DEBUG, threaded=True, use_reloader=False,
                ssl_context=(str(cert_file), str(key_file)))
    else:
        print(f"[App] *** Server starting on https://{HOST}:{PORT} ***")
        print("[App] Warning: Using self-signed cert (browser will warn)")
        app.run(host=HOST, port=PORT, debug=DEBUG, threaded=True, use_reloader=False, ssl_context='adhoc')
