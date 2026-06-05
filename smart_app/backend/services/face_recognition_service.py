import cv2
import numpy as np
import pickle
import os
import logging
import time
import base64
import io
from typing import List, Tuple, Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from PIL import Image

logger = logging.getLogger(__name__)

# ============================================
# SIMPLE FACE DETECTION ONLY (NO RECOGNITION)
# ============================================

@dataclass
class FaceRecognitionResult:
    """Unified result structure (recognition is disabled)"""
    is_match: bool
    confidence: float
    voter_id: Optional[str] = None
    method: str = "unknown"
    processing_time: float = 0.0
    details: Dict = None
    quality_score: float = 0.0


class MultiMethodFaceService:
    """Face detection only – recognition requires external libraries."""
    
    def __init__(self):
        # Only OpenCV Haar Cascade is available
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        self.eye_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_eye.xml'
        )
        logger.info("MultiMethodFaceService initialized (detection only)")

    def base64_to_image(self, image_data: str) -> np.ndarray:
        """Convert base64 string to numpy array (RGB)"""
        try:
            if 'base64,' in image_data:
                image_data = image_data.split('base64,')[1]
            image_bytes = base64.b64decode(image_data)
            image = Image.open(io.BytesIO(image_bytes))
            image_array = np.array(image)
            # Convert to RGB if needed
            if len(image_array.shape) == 2:
                image_array = cv2.cvtColor(image_array, cv2.COLOR_GRAY2RGB)
            elif image_array.shape[2] == 4:
                image_array = cv2.cvtColor(image_array, cv2.COLOR_RGBA2RGB)
            return image_array
        except Exception as e:
            logger.error(f"Image conversion error: {str(e)}")
            raise ValueError(f"Invalid image data: {str(e)}")

    def preprocess_image(self, image_array: np.ndarray) -> np.ndarray:
        """Resize and enhance contrast (optional)"""
        try:
            h, w = image_array.shape[:2]
            if max(h, w) > 1000:
                scale = 1000 / max(h, w)
                new_w = int(w * scale)
                new_h = int(h * scale)
                image_array = cv2.resize(image_array, (new_w, new_h))
            # Convert to LAB and apply CLAHE
            lab = cv2.cvtColor(image_array, cv2.COLOR_RGB2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            l = clahe.apply(l)
            lab = cv2.merge([l, a, b])
            return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
        except Exception as e:
            logger.error(f"Preprocessing error: {str(e)}")
            return image_array

    def detect_faces_multi_method(self, image_array: np.ndarray) -> List[Dict]:
        """Detect faces using OpenCV Haar Cascades only."""
        faces = []
        try:
            gray = cv2.cvtColor(image_array, cv2.COLOR_RGB2GRAY)
            detected = self.face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5,
                minSize=(30, 30), flags=cv2.CASCADE_SCALE_IMAGE
            )
            for (x, y, w, h) in detected:
                confidence = min(w * h / (image_array.shape[0] * image_array.shape[1] * 0.1), 1.0)
                faces.append({
                    'method': 'opencv',
                    'bbox': (x, y, w, h),
                    'confidence': float(confidence),
                    'landmarks': None
                })
        except Exception as e:
            logger.error(f"Face detection error: {str(e)}")
        return faces

    def extract_face_encoding_multi_method(self, image_array: np.ndarray, face_bbox: Tuple) -> Dict[str, Any]:
        """
        Face encoding is disabled because no recognition library is available.
        Returns an empty dict – recognition will gracefully fail.
        """
        logger.warning("Face encoding requested but no recognition backend is installed.")
        return {}

    def validate_face_image(self, image_array: np.ndarray) -> Tuple[bool, str]:
        """Basic validation: presence of at least one face, reasonable size/brightness."""
        try:
            h, w = image_array.shape[:2]
            if h < 100 or w < 100:
                return False, "Image too small (minimum 100x100 pixels)"

            faces = self.detect_faces_multi_method(image_array)
            if len(faces) == 0:
                return False, "No face detected"
            if len(faces) > 1:
                return False, "Multiple faces detected"

            x, y, w_box, h_box = faces[0]['bbox']
            face_region = image_array[y:y+h_box, x:x+w_box]
            gray_face = cv2.cvtColor(face_region, cv2.COLOR_RGB2GRAY)
            brightness = np.mean(gray_face)
            if brightness < 30:
                return False, "Image too dark"
            if brightness > 220:
                return False, "Image too bright"

            blur_value = cv2.Laplacian(gray_face, cv2.CV_64F).var()
            if blur_value < 50:
                return False, "Image is blurry"

            return True, "Face validation passed"
        except Exception as e:
            logger.error(f"Validation error: {str(e)}")
            return False, f"Validation error: {str(e)}"

    def calculate_face_quality_score(self, image_array: np.ndarray, face_bbox: Tuple) -> float:
        """Simple quality score based on brightness, contrast, sharpness."""
        try:
            x, y, w, h = face_bbox
            face_region = image_array[y:y+h, x:x+w]
            if face_region.size == 0:
                return 0.0
            gray_face = cv2.cvtColor(face_region, cv2.COLOR_RGB2GRAY)
            brightness = np.mean(gray_face)
            brightness_score = 1.0 - abs(brightness - 127) / 127
            contrast = np.std(gray_face)
            contrast_score = min(contrast / 50, 1.0)
            sharpness = cv2.Laplacian(gray_face, cv2.CV_64F).var()
            sharpness_score = min(sharpness / 100, 1.0)
            # weighted average
            quality = brightness_score * 0.3 + contrast_score * 0.3 + sharpness_score * 0.4
            return max(0.0, min(quality, 1.0))
        except Exception as e:
            logger.error(f"Quality score error: {str(e)}")
            return 0.0


class KNNFaceService:
    """
    KNN similarity service – requires pre‑computed face encodings.
    Without a proper face recognition backend, this service cannot work.
    """
    def __init__(self, model_path='data/face_knn_model.pkl'):
        self.model_path = model_path
        self.knn_model = None
        self.face_encodings = []
        self.voter_ids = []
        self.threshold = 0.65
        logger.warning("KNNFaceService initialized but no face encodings can be generated.")

    def find_duplicate(self, query_encoding):
        return {'is_duplicate': False, 'similarity': 0, 'error': 'Face recognition not available'}

    def verify_face(self, query_encoding, claimed_voter_id):
        return {'verified': False, 'confidence': 0, 'error': 'Face recognition not available'}

    def add_face_encoding(self, encoding, voter_id):
        logger.error("Cannot add face encoding – no recognition backend.")
        return False

    def find_similar_faces(self, query_encoding, k=None):
        return []

    def get_statistics(self):
        return {'error': 'Face recognition is disabled', 'total_encodings': 0}


class HybridFaceRecognitionService:
    """Hybrid service that returns failure because recognition is unavailable."""
    def __init__(self, knn_model_path='data/face_knn_model.pkl'):
        self.face_service = MultiMethodFaceService()
        self.knn_service = KNNFaceService(knn_model_path)
        logger.warning("HybridFaceRecognitionService: face recognition is DISABLED (missing dependencies)")

    def register_face(self, voter_id: str, image_data: str) -> FaceRecognitionResult:
        start = time.time()
        return FaceRecognitionResult(
            is_match=False,
            confidence=0.0,
            method="disabled",
            processing_time=time.time() - start,
            details={'error': 'Face recognition is not available. Please install required libraries (face_recognition, dlib, etc.) or use a different verification method.'},
            quality_score=0.0
        )

    def verify_face(self, voter_id: str, image_data: str) -> FaceRecognitionResult:
        start = time.time()
        return FaceRecognitionResult(
            is_match=False,
            confidence=0.0,
            method="disabled",
            processing_time=time.time() - start,
            details={'error': 'Face recognition is not available.'},
            quality_score=0.0
        )

    def find_similar_faces(self, image_data: str, k: int = 5) -> List[Dict]:
        return []

    def get_system_stats(self) -> Dict:
        return {
            'status': 'face_recognition_disabled',
            'reason': 'Missing dependencies (mediapipe, dlib, face_recognition, deepface)'
        }

    def reindex_knn_from_database(self, face_encodings_data: List[Dict]) -> int:
        return 0


# Global instances
multi_face_service = MultiMethodFaceService()
knn_face_service = KNNFaceService()
hybrid_face_service = HybridFaceRecognitionService()
face_service = multi_face_service