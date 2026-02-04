"""Photo library management and contact sheet generation for Who's That?"""

import base64
import shutil
from pathlib import Path
from typing import List, Dict, Optional
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from config import (
    PHOTOS_DIR, CONTACT_SHEET_PATH,
    THUMBNAIL_SIZE, CONTACT_SHEET_MAX_WIDTH, LABEL_FONT_SIZE
)


class PhotoLibrary:
    """Manages the photo library of enrolled subjects."""

    def __init__(self):
        self._photos_dir = PHOTOS_DIR
        self._contact_sheet_path = CONTACT_SHEET_PATH
        self._library_hash: Optional[str] = None

    def _ensure_dirs(self):
        """Ensure the photos directory exists."""
        self._photos_dir.mkdir(parents=True, exist_ok=True)

    def _get_subject_dir(self, name: str) -> Path:
        """Get the directory for a subject."""
        # Normalize name to lowercase, replace spaces with underscores
        normalized = name.lower().strip().replace(" ", "_")
        # Remove any characters that aren't alphanumeric or underscore
        normalized = "".join(c for c in normalized if c.isalnum() or c == "_")
        return self._photos_dir / normalized

    def _compute_library_hash(self) -> str:
        """Compute a hash of the library state for cache invalidation."""
        self._ensure_dirs()
        subjects = []
        for subject_dir in sorted(self._photos_dir.iterdir()):
            if subject_dir.is_dir() and not subject_dir.name.startswith("."):
                photos = sorted(subject_dir.glob("*.jpg"))
                subjects.append(f"{subject_dir.name}:{len(photos)}")
        return "|".join(subjects)

    def enroll(self, name: str, frame: np.ndarray) -> Dict:
        """
        Enroll a new photo for a subject.

        Args:
            name: Subject's name
            frame: OpenCV frame (BGR numpy array)

        Returns:
            Dict with enrollment result
        """
        self._ensure_dirs()
        subject_dir = self._get_subject_dir(name)
        subject_dir.mkdir(exist_ok=True)

        # Find next photo number
        existing = list(subject_dir.glob("*.jpg"))
        next_num = len(existing) + 1
        photo_path = subject_dir / f"{next_num:03d}.jpg"

        # Save the full-resolution frame
        cv2.imwrite(str(photo_path), frame)

        # Invalidate contact sheet cache
        self._library_hash = None
        self._regenerate_contact_sheet()

        return {
            "success": True,
            "name": name,
            "normalized_name": subject_dir.name,
            "photo_count": next_num,
            "message": f"Got it! I'll remember {name}."
        }

    def list_subjects(self) -> List[Dict]:
        """
        List all enrolled subjects.

        Returns:
            List of subject info dicts
        """
        self._ensure_dirs()
        subjects = []

        for subject_dir in sorted(self._photos_dir.iterdir()):
            if subject_dir.is_dir() and not subject_dir.name.startswith("."):
                photos = sorted(subject_dir.glob("*.jpg"))
                if photos:
                    subjects.append({
                        "name": subject_dir.name,
                        "display_name": subject_dir.name.replace("_", " ").title(),
                        "photo_count": len(photos),
                        "photos": [p.name for p in photos]
                    })

        return subjects

    def get_subject_thumbnail(self, name: str, size: int = 150) -> Optional[bytes]:
        """
        Get a thumbnail for a subject.

        Args:
            name: Subject's normalized name
            size: Thumbnail size in pixels

        Returns:
            JPEG bytes or None if not found
        """
        subject_dir = self._photos_dir / name
        if not subject_dir.exists():
            return None

        photos = sorted(subject_dir.glob("*.jpg"))
        if not photos:
            return None

        # Use first photo
        img = cv2.imread(str(photos[0]))
        if img is None:
            return None

        # Resize to square thumbnail
        h, w = img.shape[:2]
        min_dim = min(h, w)
        # Center crop to square
        start_x = (w - min_dim) // 2
        start_y = (h - min_dim) // 2
        cropped = img[start_y:start_y + min_dim, start_x:start_x + min_dim]
        # Resize
        thumb = cv2.resize(cropped, (size, size))

        _, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes()

    def get_photo(self, name: str, photo_id: str) -> Optional[bytes]:
        """
        Get a specific photo.

        Args:
            name: Subject's normalized name
            photo_id: Photo filename (e.g., "001.jpg")

        Returns:
            JPEG bytes or None if not found
        """
        photo_path = self._photos_dir / name / photo_id
        if not photo_path.exists():
            return None

        with open(photo_path, "rb") as f:
            return f.read()

    def delete_subject(self, name: str) -> Dict:
        """
        Delete a subject and all their photos.

        Args:
            name: Subject's normalized name

        Returns:
            Result dict
        """
        subject_dir = self._photos_dir / name
        if not subject_dir.exists():
            return {"success": False, "message": f"I don't know anyone named {name}"}

        shutil.rmtree(subject_dir)
        self._library_hash = None
        self._regenerate_contact_sheet()

        return {
            "success": True,
            "message": f"Okay, I've forgotten {name.replace('_', ' ').title()}."
        }

    def delete_photo(self, name: str, photo_id: str) -> Dict:
        """
        Delete a specific photo.

        Args:
            name: Subject's normalized name
            photo_id: Photo filename

        Returns:
            Result dict
        """
        photo_path = self._photos_dir / name / photo_id
        if not photo_path.exists():
            return {"success": False, "message": "Photo not found"}

        photo_path.unlink()

        # Check if subject has no more photos
        subject_dir = self._photos_dir / name
        remaining = list(subject_dir.glob("*.jpg"))
        if not remaining:
            subject_dir.rmdir()

        self._library_hash = None
        self._regenerate_contact_sheet()

        return {"success": True, "message": "Photo deleted"}

    def clear_all(self) -> Dict:
        """Delete all enrolled subjects."""
        self._ensure_dirs()
        count = 0
        for subject_dir in self._photos_dir.iterdir():
            if subject_dir.is_dir() and not subject_dir.name.startswith("."):
                shutil.rmtree(subject_dir)
                count += 1

        self._library_hash = None
        if self._contact_sheet_path.exists():
            self._contact_sheet_path.unlink()

        return {
            "success": True,
            "message": f"Cleared {count} subjects from memory."
        }

    def get_contact_sheet_base64(self) -> Optional[str]:
        """
        Get the contact sheet as base64-encoded JPEG.

        Returns:
            Base64 string or None if library is empty
        """
        current_hash = self._compute_library_hash()

        # Check if we need to regenerate
        if not self._contact_sheet_path.exists() or self._library_hash != current_hash:
            self._regenerate_contact_sheet()
            self._library_hash = current_hash

        if not self._contact_sheet_path.exists():
            return None

        with open(self._contact_sheet_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def has_subjects(self) -> bool:
        """Check if there are any enrolled subjects."""
        return bool(self.list_subjects())

    def _regenerate_contact_sheet(self):
        """Regenerate the contact sheet image."""
        subjects = self.list_subjects()
        if not subjects:
            if self._contact_sheet_path.exists():
                self._contact_sheet_path.unlink()
            return

        thumb_size = THUMBNAIL_SIZE
        label_height = 40
        cell_height = thumb_size + label_height
        padding = 10

        # Calculate grid dimensions
        max_cols = CONTACT_SHEET_MAX_WIDTH // (thumb_size + padding)
        max_cols = max(1, min(max_cols, len(subjects)))
        num_rows = (len(subjects) + max_cols - 1) // max_cols

        # Create the contact sheet image
        sheet_width = max_cols * (thumb_size + padding) + padding
        sheet_height = num_rows * (cell_height + padding) + padding

        # Use PIL for better text rendering
        sheet = Image.new("RGB", (sheet_width, sheet_height), (255, 255, 255))
        draw = ImageDraw.Draw(sheet)

        # Try to load a nice font, fall back to default
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", LABEL_FONT_SIZE)
        except OSError:
            try:
                font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", LABEL_FONT_SIZE)
            except OSError:
                font = ImageFont.load_default()

        for idx, subject in enumerate(subjects):
            row = idx // max_cols
            col = idx % max_cols

            x = padding + col * (thumb_size + padding)
            y = padding + row * (cell_height + padding)

            # Load and resize the first photo
            subject_dir = self._photos_dir / subject["name"]
            photos = sorted(subject_dir.glob("*.jpg"))
            if photos:
                img = Image.open(photos[0])
                # Center crop to square
                w, h = img.size
                min_dim = min(w, h)
                left = (w - min_dim) // 2
                top = (h - min_dim) // 2
                img = img.crop((left, top, left + min_dim, top + min_dim))
                img = img.resize((thumb_size, thumb_size), Image.Resampling.LANCZOS)

                # Paste onto sheet
                sheet.paste(img, (x, y))

            # Draw border
            draw.rectangle(
                [x, y, x + thumb_size, y + thumb_size],
                outline=(200, 200, 200),
                width=2
            )

            # Draw label
            label = subject["display_name"]
            # Get text bounding box
            bbox = draw.textbbox((0, 0), label, font=font)
            text_width = bbox[2] - bbox[0]
            text_x = x + (thumb_size - text_width) // 2
            text_y = y + thumb_size + 5

            draw.text((text_x, text_y), label, fill=(0, 0, 0), font=font)

        # Save the contact sheet
        sheet.save(self._contact_sheet_path, "JPEG", quality=90)
        print(f"[Library] Contact sheet regenerated with {len(subjects)} subjects")


# Global library instance
library = PhotoLibrary()
