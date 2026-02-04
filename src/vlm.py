"""Vision Language Model client for Who's That?"""

import requests
from typing import Optional, List, Dict, Any

from config import VLM_URL, VLM_MODEL, VLM_TIMEOUT, DESCRIBE_PROMPT, IDENTIFY_PROMPT


class VLMError(Exception):
    """Exception raised when VLM request fails."""
    pass


def _make_image_content(b64_image: str) -> Dict[str, Any]:
    """Create image content block for VLM request."""
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:image/jpeg;base64,{b64_image}"
        }
    }


def _make_text_content(text: str) -> Dict[str, Any]:
    """Create text content block for VLM request."""
    return {"type": "text", "text": text}


def ask_model(
    images: List[str],
    prompt: str,
    max_tokens: int = 200,
    conversation: Optional[List[Dict]] = None
) -> str:
    """
    Send images and prompt to the VLM.

    Args:
        images: List of base64-encoded JPEG images
        prompt: Text prompt to send with images
        max_tokens: Maximum response tokens
        conversation: Optional previous conversation history

    Returns:
        Model's text response

    Raises:
        VLMError: If request fails
    """
    # Build content list: images first, then prompt
    content = []
    for img in images:
        content.append(_make_image_content(img))
    content.append(_make_text_content(prompt))

    # Build messages list
    messages = []
    if conversation:
        messages.extend(conversation)
    messages.append({"role": "user", "content": content})

    try:
        resp = requests.post(
            VLM_URL,
            json={
                "model": VLM_MODEL,
                "max_tokens": max_tokens,
                "messages": messages,
            },
            timeout=VLM_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except requests.Timeout:
        raise VLMError("My brain is still waking up! Try again in a moment.")
    except requests.ConnectionError:
        raise VLMError("I can't reach my brain right now. Is the VLM server running?")
    except requests.RequestException as e:
        raise VLMError(f"Something went wrong: {e}")
    except (KeyError, IndexError):
        raise VLMError("Got a weird response from my brain. Try again?")


def describe_scene(frame_b64: str) -> str:
    """
    Get a scene description for a single frame.

    Args:
        frame_b64: Base64-encoded JPEG of the current frame

    Returns:
        Friendly scene description
    """
    return ask_model([frame_b64], DESCRIBE_PROMPT, max_tokens=300)


def identify_subjects(
    contact_sheet_b64: str,
    frame_b64: str,
    conversation: Optional[List[Dict]] = None
) -> str:
    """
    Identify subjects in a frame using the contact sheet as reference.

    Args:
        contact_sheet_b64: Base64-encoded contact sheet image
        frame_b64: Base64-encoded JPEG of the current frame
        conversation: Optional previous conversation for follow-ups

    Returns:
        Identification and description response
    """
    return ask_model(
        [contact_sheet_b64, frame_b64],
        IDENTIFY_PROMPT,
        max_tokens=400,
        conversation=conversation
    )


def chat_followup(
    contact_sheet_b64: str,
    frame_b64: str,
    user_message: str,
    conversation: List[Dict]
) -> tuple[str, List[Dict]]:
    """
    Handle a follow-up chat message about the current scene.

    Args:
        contact_sheet_b64: Base64-encoded contact sheet image
        frame_b64: Base64-encoded JPEG of the current frame
        user_message: User's follow-up question
        conversation: Previous conversation history

    Returns:
        Tuple of (response text, updated conversation history)
    """
    # The conversation already contains the images in the first user message,
    # so we just need to add the new text-only message
    updated_conversation = conversation.copy()
    updated_conversation.append({
        "role": "user",
        "content": user_message
    })

    try:
        resp = requests.post(
            VLM_URL,
            json={
                "model": VLM_MODEL,
                "max_tokens": 300,
                "messages": updated_conversation,
            },
            timeout=VLM_TIMEOUT,
        )
        resp.raise_for_status()
        response_text = resp.json()["choices"][0]["message"]["content"]

        # Add assistant response to conversation
        updated_conversation.append({
            "role": "assistant",
            "content": response_text
        })

        return response_text, updated_conversation

    except requests.Timeout:
        raise VLMError("Hmm, let me think... try asking again!")
    except requests.ConnectionError:
        raise VLMError("Lost connection to my brain! Try again?")
    except requests.RequestException as e:
        raise VLMError(f"Something went wrong: {e}")
    except (KeyError, IndexError):
        raise VLMError("Got confused there. Ask me again?")


def build_initial_conversation(
    contact_sheet_b64: str,
    frame_b64: str,
    initial_response: str
) -> List[Dict]:
    """
    Build the initial conversation history after identification.

    This is used to set up the context for follow-up questions.

    Args:
        contact_sheet_b64: Base64-encoded contact sheet
        frame_b64: Base64-encoded frame
        initial_response: The initial identification response

    Returns:
        Conversation history list
    """
    return [
        {
            "role": "user",
            "content": [
                _make_image_content(contact_sheet_b64),
                _make_image_content(frame_b64),
                _make_text_content(IDENTIFY_PROMPT)
            ]
        },
        {
            "role": "assistant",
            "content": initial_response
        }
    ]
