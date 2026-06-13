import base64
import logging
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    import mediapipe as mp

    _ = mp.solutions
    MEDIAPIPE_AVAILABLE = True
except (ImportError, AttributeError):
    MEDIAPIPE_AVAILABLE = False

try:
    import dlib

    DLIB_AVAILABLE = True
except ImportError:
    DLIB_AVAILABLE = False

logger = logging.getLogger(__name__)


class FaceUtils:
    """
    Face utility functions with optional advanced backends (MediaPipe, dlib).
    Falls back to pure OpenCV if advanced libraries are missing.
    """

    def __init__(self):
        """Initialize cascades and optional backends."""
        self.eye_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_eye.xml"
        )

        self.mp_face_detection = None
        self.mp_face_mesh = None
        if MEDIAPIPE_AVAILABLE:
            try:
                self.mp_face_detection = mp.solutions.face_detection.FaceDetection(
                    model_selection=1, min_detection_confidence=0.5
                )
                self.mp_face_mesh = mp.solutions.face_mesh.FaceMesh(
                    static_image_mode=True,
                    max_num_faces=1,
                    min_detection_confidence=0.5,
                )
                logger.info("MediaPipe face detection & mesh loaded")
            except Exception as e:
                logger.warning(f"Failed to init MediaPipe: {e}")

        self.dlib_predictor = None
        if DLIB_AVAILABLE:
            try:
                predictor_path = "models/shape_predictor_68_face_landmarks.dat"
                self.dlib_predictor = dlib.shape_predictor(predictor_path)
                logger.info("dlib landmark predictor loaded")
            except Exception as e:
                logger.warning(f"Failed to load dlib predictor: {e}")

        logger.info("FaceUtils initialized (enhanced)")

    def draw_face_annotations(
        self, image_array: np.ndarray, faces: List[Dict]
    ) -> np.ndarray:
        """Draw bounding boxes and labels on detected faces."""
        try:
            annotated_image = image_array.copy()
            for face in faces:
                method = face.get("method", "unknown")
                bbox = face.get("bbox")
                confidence = face.get("confidence", 0.0)
                if bbox:
                    x, y, w, h = bbox
                    color = self._get_color_for_method(method)
                    cv2.rectangle(annotated_image, (x, y), (x + w, y + h), color, 2)
                    label = f"{method}: {confidence:.2f}"
                    cv2.putText(
                        annotated_image,
                        label,
                        (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        color,
                        2,
                    )
            return annotated_image
        except Exception as e:
            logger.error(f"Annotation drawing error: {str(e)}")
            return image_array

    def _get_color_for_method(self, method: str) -> Tuple[int, int, int]:
        """Return BGR color for different detection/recognition methods."""
        colors = {
            "haar_cascade": (255, 0, 0),
            "opencv_dnn": (0, 255, 0),
            "mediapipe": (0, 255, 255),
            "dlib_hog": (0, 165, 255),
            "dlib_cnn": (255, 0, 255),
            "ensemble": (255, 255, 0),
            "face_recognition": (255, 255, 0),
            "dlib_resnet": (0, 255, 255),
            "knn": (128, 0, 128),
            "lbph": (255, 128, 0),
            "opencv": (255, 0, 0),
            "dlib": (0, 0, 255),
            "unknown": (128, 128, 128),
        }
        return colors.get(method.lower(), colors["unknown"])

    def enhance_image(self, image_array: np.ndarray) -> np.ndarray:
        """Enhance image quality using CLAHE, sharpening, and bilateral filter."""
        try:
            if len(image_array.shape) == 3:
                lab = cv2.cvtColor(image_array, cv2.COLOR_RGB2LAB)
                lightness_channel, a, b = cv2.split(lab)
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
                lightness_channel = clahe.apply(lightness_channel)
                lab = cv2.merge([lightness_channel, a, b])
                enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
            else:
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
                enhanced = clahe.apply(image_array)

            kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
            enhanced = cv2.filter2D(enhanced, -1, kernel)
            enhanced = cv2.bilateralFilter(enhanced, 9, 75, 75)
            return enhanced
        except Exception as e:
            logger.error(f"Image enhancement error: {str(e)}")
            return image_array

    def align_face(
        self, image_array: np.ndarray, face_bbox: Tuple
    ) -> Optional[np.ndarray]:
        """
        Align face using eye positions.
        Uses MediaPipe/dlib landmarks if available, otherwise falls back to Haar eye detection.
        """
        try:
            x, y, w, h = face_bbox
            face_region = image_array[y : y + h, x : x + w]
            if face_region.size == 0:
                return None

            eyes = self._detect_eyes_advanced(image_array, face_bbox)
            if len(eyes) < 2:
                gray_face = cv2.cvtColor(face_region, cv2.COLOR_RGB2GRAY)
                eyes = self._detect_eyes_haar(gray_face)

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

    def _detect_eyes_advanced(
        self, image: np.ndarray, face_bbox: Tuple
    ) -> List[Tuple[int, int]]:
        """
        Use MediaPipe Face Mesh or dlib landmarks to get precise eye centers.
        Returns list of (x, y) eye centers in image coordinates.
        """
        eyes = []
        x, y, w, h = face_bbox
        face_roi = image[y : y + h, x : x + w]

        if self.mp_face_mesh is not None:
            try:
                rgb = cv2.cvtColor(face_roi, cv2.COLOR_RGB2RGB)
                results = self.mp_face_mesh.process(rgb)
                if results.multi_face_landmarks:
                    landmarks = results.multi_face_landmarks[0]
                    h_f, w_f = face_roi.shape[:2]
                    left_eye = landmarks.landmark[33]
                    right_eye = landmarks.landmark[133]
                    left_x = int(left_eye.x * w_f) + x
                    left_y = int(left_eye.y * h_f) + y
                    right_x = int(right_eye.x * w_f) + x
                    right_y = int(right_eye.y * h_f) + y
                    eyes.append((left_x, left_y))
                    eyes.append((right_x, right_y))
                    return eyes
            except Exception as e:
                logger.debug(f"MediaPipe eye detection failed: {e}")

        if self.dlib_predictor is not None and DLIB_AVAILABLE:
            try:
                gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
                rect = dlib.rectangle(x, y, x + w, y + h)
                shape = self.dlib_predictor(gray, rect)
                left_eye_x = (shape.part(36).x + shape.part(39).x) // 2
                left_eye_y = (shape.part(36).y + shape.part(39).y) // 2
                right_eye_x = (shape.part(42).x + shape.part(45).x) // 2
                right_eye_y = (shape.part(42).y + shape.part(45).y) // 2
                eyes.append((left_eye_x, left_eye_y))
                eyes.append((right_eye_x, right_eye_y))
                return eyes
            except Exception as e:
                logger.debug(f"dlib eye detection failed: {e}")

        return eyes

    def _detect_eyes_haar(self, gray_face: np.ndarray) -> List[Tuple[int, int]]:
        """Fallback: OpenCV Haar cascade for eye detection."""
        try:
            eyes = self.eye_cascade.detectMultiScale(
                gray_face, scaleFactor=1.1, minNeighbors=5, minSize=(20, 20)
            )
            eye_centers = []
            for ex, ey, ew, eh in eyes:
                eye_centers.append((ex + ew // 2, ey + eh // 2))
            return eye_centers
        except Exception as e:
            logger.error(f"Haar eye detection error: {str(e)}")
            return []

    def detect_face_landmarks(
        self, image_array: np.ndarray, face_bbox: Optional[Tuple] = None
    ) -> Optional[Dict]:
        """
        Detect facial landmarks using MediaPipe (468 points) or dlib (68 points).
        Returns dict with 'points' (list of (x,y)) and 'method'.
        Returns None if no backend available.
        """
        if self.mp_face_mesh is not None:
            try:
                rgb = cv2.cvtColor(image_array, cv2.COLOR_RGB2RGB)
                results = self.mp_face_mesh.process(rgb)
                if results.multi_face_landmarks:
                    landmarks = results.multi_face_landmarks[0]
                    h, w = image_array.shape[:2]
                    points = [
                        (int(lm.x * w), int(lm.y * h)) for lm in landmarks.landmark
                    ]
                    return {
                        "points": points,
                        "method": "mediapipe",
                        "num_points": len(points),
                    }
            except Exception as e:
                logger.debug(f"MediaPipe landmarks failed: {e}")

        if self.dlib_predictor is not None and face_bbox is not None:
            try:
                x, y, w, h = face_bbox
                gray = cv2.cvtColor(image_array, cv2.COLOR_RGB2GRAY)
                rect = dlib.rectangle(x, y, x + w, y + h)
                shape = self.dlib_predictor(gray, rect)
                points = [
                    (shape.part(i).x, shape.part(i).y) for i in range(shape.num_parts)
                ]
                return {"points": points, "method": "dlib", "num_points": len(points)}
            except Exception as e:
                logger.debug(f"dlib landmarks failed: {e}")

        logger.debug("Landmark detection skipped – no backend available")
        return None

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

    def create_face_thumbnail(
        self,
        image_array: np.ndarray,
        face_bbox: Tuple,
        size: Tuple[int, int] = (100, 100),
    ) -> Optional[Dict]:
        """Create a standardised face thumbnail (aligned, resized, base64)."""
        try:
            x, y, w, h = face_bbox
            face_region = image_array[y : y + h, x : x + w]
            if face_region.size == 0:
                return None

            aligned_face = self.align_face(image_array, face_bbox)
            if aligned_face is not None:
                face_region = aligned_face

            thumbnail = cv2.resize(face_region, size, interpolation=cv2.INTER_AREA)

            _, buffer = cv2.imencode(".jpg", thumbnail)
            thumbnail_base64 = base64.b64encode(buffer).decode("utf-8")

            return {
                "image_array": thumbnail,
                "base64": thumbnail_base64,
                "size": size,
                "original_bbox": face_bbox,
            }
        except Exception as e:
            logger.error(f"Thumbnail creation error: {str(e)}")
            return None

    def get_face_orientation(self, image_array: np.ndarray, face_bbox: Tuple) -> Dict:
        """
        Estimate head pose (yaw, pitch, roll) using landmarks if available.
        Returns dict with angles in degrees, or empty dict if unavailable.
        """
        landmarks = self.detect_face_landmarks(image_array, face_bbox)
        if not landmarks or landmarks["method"] not in ("mediapipe", "dlib"):
            return {}

        points = landmarks["points"]
        try:
            if landmarks["method"] == "mediapipe":
                left_eye = points[33]
                right_eye = points[133]
                nose = points[1]
            else:
                left_eye = points[36]
                right_eye = points[45]
                nose = points[30]

            dx = right_eye[0] - left_eye[0]
            dy = right_eye[1] - left_eye[1]
            roll = np.degrees(np.arctan2(dy, dx))
            eye_center = (
                (left_eye[0] + right_eye[0]) // 2,
                (left_eye[1] + right_eye[1]) // 2,
            )
            pitch = np.degrees(
                np.arctan2(nose[1] - eye_center[1], nose[0] - eye_center[0])
            )
            return {"yaw": 0.0, "pitch": pitch, "roll": roll}
        except Exception:
            return {}


face_utils = FaceUtils()
