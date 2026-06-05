# smart_app/backend/services/face_utils.py
import cv2
import numpy as np
import logging
import base64
from typing import List, Tuple, Optional, Dict

logger = logging.getLogger(__name__)


class FaceUtils:
    """Face utility functions using only OpenCV (no MediaPipe, dlib, etc.)."""

    def __init__(self):
        # MediaPipe is completely removed – all drawing and landmark functions will fall back safely.
        logger.info("FaceUtils initialized (OpenCV only)")

    def draw_face_annotations(self, image_array: np.ndarray, faces: List[Dict]) -> np.ndarray:
        """Draw bounding boxes and labels on detected faces."""
        try:
            annotated_image = image_array.copy()

            for face in faces:
                method = face.get('method', 'unknown')
                bbox = face.get('bbox')
                confidence = face.get('confidence', 0.0)

                if bbox:
                    x, y, w, h = bbox
                    color = self._get_color_for_method(method)
                    cv2.rectangle(annotated_image, (x, y), (x + w, y + h), color, 2)
                    label = f"{method}: {confidence:.2f}"
                    cv2.putText(annotated_image, label, (x, y - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            return annotated_image
        except Exception as e:
            logger.error(f"Annotation drawing error: {str(e)}")
            return image_array

    def _get_color_for_method(self, method: str) -> Tuple[int, int, int]:
        """Return BGR color for different detection methods."""
        colors = {
            'mediapipe': (0, 255, 0),      # Green
            'opencv': (255, 0, 0),         # Blue
            'dlib': (0, 0, 255),           # Red
            'face_recognition': (255, 255, 0),  # Cyan
            'ensemble': (255, 0, 255),     # Magenta
            'unknown': (128, 128, 128)     # Gray
        }
        return colors.get(method.lower(), colors['unknown'])

    def enhance_image(self, image_array: np.ndarray) -> np.ndarray:
        """Enhance image quality using CLAHE, sharpening, and bilateral filter."""
        try:
            # Apply CLAHE for contrast enhancement
            if len(image_array.shape) == 3:
                lab = cv2.cvtColor(image_array, cv2.COLOR_RGB2LAB)
                l, a, b = cv2.split(lab)
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
                l = clahe.apply(l)
                lab = cv2.merge([l, a, b])
                enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
            else:
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
                enhanced = clahe.apply(image_array)

            # Slight sharpening
            kernel = np.array([[0, -1, 0],
                               [-1, 5, -1],
                               [0, -1, 0]])
            enhanced = cv2.filter2D(enhanced, -1, kernel)

            # Bilateral filter for noise reduction
            enhanced = cv2.bilateralFilter(enhanced, 9, 75, 75)

            return enhanced
        except Exception as e:
            logger.error(f"Image enhancement error: {str(e)}")
            return image_array

    def align_face(self, image_array: np.ndarray, face_bbox: Tuple) -> Optional[np.ndarray]:
        """Align face based on eye positions (OpenCV eye detection)."""
        try:
            x, y, w, h = face_bbox
            face_region = image_array[y:y + h, x:x + w]

            if face_region.size == 0:
                return None

            gray_face = cv2.cvtColor(face_region, cv2.COLOR_RGB2GRAY)
            eyes = self._detect_eyes(gray_face)

            if len(eyes) >= 2:
                eye1, eye2 = eyes[:2]
                dx = eye2[0] - eye1[0]
                dy = eye2[1] - eye1[1]
                angle = np.degrees(np.arctan2(dy, dx))
                center = (w // 2, h // 2)
                rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
                aligned = cv2.warpAffine(face_region, rotation_matrix, (w, h))
                return aligned

            return face_region
        except Exception as e:
            logger.error(f"Face alignment error: {str(e)}")
            return None

    def _detect_eyes(self, gray_face: np.ndarray) -> List[Tuple[int, int]]:
        """Detect eyes in a face region (grayscale). Returns centers."""
        try:
            eye_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_eye.xml'
            )
            eyes = eye_cascade.detectMultiScale(
                gray_face,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(20, 20)
            )
            eye_centers = []
            for (ex, ey, ew, eh) in eyes:
                center_x = ex + ew // 2
                center_y = ey + eh // 2
                eye_centers.append((center_x, center_y))
            return eye_centers
        except Exception as e:
            logger.error(f"Eye detection error: {str(e)}")
            return []

    def calculate_blur_score(self, image_array: np.ndarray) -> float:
        """Calculate blur score (0-1, higher = sharper)."""
        try:
            if len(image_array.shape) == 3:
                gray = cv2.cvtColor(image_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = image_array

            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            blur_score = min(laplacian_var / 500.0, 1.0)
            return blur_score
        except Exception as e:
            logger.error(f"Blur score calculation error: {str(e)}")
            return 0.0

    def detect_face_landmarks(self, image_array: np.ndarray) -> Optional[Dict]:
        """
        Facial landmark detection – not available without MediaPipe/dlib.
        Returns None to indicate the feature is disabled.
        """
        logger.debug("Landmark detection skipped – no backend available")
        return None

    def create_face_thumbnail(self, image_array: np.ndarray, face_bbox: Tuple,
                              size: Tuple[int, int] = (100, 100)) -> Optional[Dict]:
        """Create a standardised face thumbnail (aligned, resized, base64)."""
        try:
            x, y, w, h = face_bbox
            face_region = image_array[y:y + h, x:x + w]

            if face_region.size == 0:
                return None

            # Try to align the face
            aligned_face = self.align_face(image_array, face_bbox)
            if aligned_face is not None:
                face_region = aligned_face

            # Resize
            thumbnail = cv2.resize(face_region, size, interpolation=cv2.INTER_AREA)

            # Convert to base64
            _, buffer = cv2.imencode('.jpg', thumbnail)
            thumbnail_base64 = base64.b64encode(buffer).decode('utf-8')

            return {
                'image_array': thumbnail,
                'base64': thumbnail_base64,
                'size': size,
                'original_bbox': face_bbox
            }
        except Exception as e:
            logger.error(f"Thumbnail creation error: {str(e)}")
            return None


# Global instance
face_utils = FaceUtils()