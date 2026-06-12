# smart_app/backend/services/face_recognition_service.py

import base64
import io
import logging
import os
import pickle
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

# Optional libraries with graceful fallbacks
try:
    import mediapipe as mp

    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    logging.warning("MediaPipe not installed. Install: pip install mediapipe")

try:
    import dlib

    DLIB_AVAILABLE = True
except ImportError:
    DLIB_AVAILABLE = False
    logging.warning("dlib not installed. Install: pip install dlib")

try:
    import face_recognition

    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False
    logging.warning(
        "face_recognition not installed. Install: pip install face_recognition"
    )

# Import our face utilities (enhancement, alignment, etc.)
from .face_utils import face_utils

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Data structures
# ----------------------------------------------------------------------
@dataclass
class FaceRecognitionResult:
    """Unified result structure for face verification/registration."""

    is_match: bool
    confidence: float
    voter_id: Optional[str] = None
    method: str = "unknown"
    processing_time: float = 0.0
    details: Dict = None
    quality_score: float = 0.0


@dataclass
class DetectedFace:
    """Internal representation of a detected face."""

    bbox: Tuple[int, int, int, int]  # x, y, w, h
    confidence: float
    detection_method: str
    landmarks: Optional[Any] = None
    encoding: Optional[np.ndarray] = None
    alignment_score: float = 0.0
    thumbnail: Optional[Dict] = None
    all_detections: List[Dict] = field(default_factory=list)


# ----------------------------------------------------------------------
# MultiMethodFaceService – Detection‑only (now upgraded)
# ----------------------------------------------------------------------
class MultiMethodFaceService:
    """
    Face detection service using multiple methods (Haar, OpenCV DNN, MediaPipe, dlib).
    Also provides preprocessing, validation, quality scoring.
    """

    def __init__(self, enable_ensemble: bool = True, fast_mode: bool = False):
        """
        Args:
            enable_ensemble: If True, uses all available detectors and merges results.
            fast_mode: If True, uses only Haar cascade (fastest) and minimal preprocessing.
        """
        self.enable_ensemble = enable_ensemble and not fast_mode
        self.fast_mode = fast_mode

        # Always load Haar cascade (fastest)
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self.eye_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_eye.xml"
        )

        # Optional detectors
        self.detectors = {}
        self._init_optional_detectors()

        logger.info(
            f"MultiMethodFaceService initialized (ensemble={self.enable_ensemble}, fast={fast_mode})"
        )

    def _init_optional_detectors(self):
        """Load additional detectors if libraries are available and ensemble enabled."""
        if not self.enable_ensemble:
            return

        # OpenCV DNN (ResNet SSD) – requires model files
        try:
            proto = "models/deploy.prototxt"
            model = "models/res10_300x300_ssd_iter_140000.caffemodel"
            if os.path.exists(proto) and os.path.exists(model):
                net = cv2.dnn.readNetFromCaffe(proto, model)
                self.detectors["opencv_dnn"] = {
                    "model": net,
                    "method": "opencv_dnn",
                    "conf_thresh": 0.5,
                }
                logger.debug("OpenCV DNN detector loaded")
        except Exception as e:
            logger.warning(f"Failed to load OpenCV DNN: {e}")

        # MediaPipe
        if MEDIAPIPE_AVAILABLE:
            try:
                mp_face_detection = mp.solutions.face_detection
                self.detectors["mediapipe"] = {
                    "model": mp_face_detection.FaceDetection(
                        model_selection=1, min_detection_confidence=0.5
                    ),
                    "method": "mediapipe",
                    "conf_thresh": 0.5,
                }
                logger.debug("MediaPipe detector loaded")
            except Exception as e:
                logger.warning(f"Failed to load MediaPipe: {e}")

        # dlib HOG
        if DLIB_AVAILABLE:
            try:
                self.detectors["dlib_hog"] = {
                    "model": dlib.get_frontal_face_detector(),
                    "method": "dlib_hog",
                    "conf_thresh": 0.0,  # no confidence from HOG
                }
                logger.debug("dlib HOG detector loaded")
            except Exception as e:
                logger.warning(f"Failed to load dlib HOG: {e}")

        # dlib CNN (requires model file)
        if DLIB_AVAILABLE:
            try:
                cnn_model = "models/mmod_human_face_detector.dat"
                if os.path.exists(cnn_model):
                    self.detectors["dlib_cnn"] = {
                        "model": dlib.cnn_face_detection_model_v1(cnn_model),
                        "method": "dlib_cnn",
                        "conf_thresh": 0.5,
                    }
                    logger.debug("dlib CNN detector loaded")
            except Exception as e:
                logger.warning(f"Failed to load dlib CNN: {e}")

    def base64_to_image(self, image_data: str) -> np.ndarray:
        """Convert base64 string to numpy array (RGB)."""
        try:
            if "base64," in image_data:
                image_data = image_data.split("base64,")[1]
            image_bytes = base64.b64decode(image_data)
            image = Image.open(io.BytesIO(image_bytes))
            image_array = np.array(image)
            if len(image_array.shape) == 2:
                image_array = cv2.cvtColor(image_array, cv2.COLOR_GRAY2RGB)
            elif image_array.shape[2] == 4:
                image_array = cv2.cvtColor(image_array, cv2.COLOR_RGBA2RGB)
            return image_array
        except Exception as e:
            logger.error(f"Image conversion error: {str(e)}")
            raise ValueError(f"Invalid image data: {str(e)}")

    def preprocess_image(self, image_array: np.ndarray) -> np.ndarray:
        """Resize and enhance contrast using face_utils if available."""
        try:
            if self.fast_mode:
                # Only resize if too large
                h, w = image_array.shape[:2]
                if max(h, w) > 1000:
                    scale = 1000 / max(h, w)
                    new_w = int(w * scale)
                    new_h = int(h * scale)
                    image_array = cv2.resize(image_array, (new_w, new_h))
                return image_array
            else:
                # Use full enhancement from face_utils
                return face_utils.enhance_image(image_array)
        except Exception as e:
            logger.error(f"Preprocessing error: {str(e)}")
            return image_array

    def detect_faces_multi_method(self, image_array: np.ndarray) -> List[Dict]:
        """
        Detect faces using all enabled detectors (or just Haar).
        Returns list of dicts with keys: method, bbox, confidence, landmarks.
        """
        if self.fast_mode or not self.enable_ensemble:
            # Use only Haar cascade
            return self._detect_haar(image_array)
        else:
            # Run all detectors and ensemble
            all_detections = []
            for name, det_info in self.detectors.items():
                try:
                    if name == "opencv_dnn":
                        dets = self._detect_opencv_dnn(image_array, det_info)
                    elif name == "mediapipe":
                        dets = self._detect_mediapipe(image_array, det_info)
                    elif name == "dlib_hog":
                        dets = self._detect_dlib_hog(image_array, det_info)
                    elif name == "dlib_cnn":
                        dets = self._detect_dlib_cnn(image_array, det_info)
                    else:
                        continue
                    all_detections.extend(dets)
                except Exception as e:
                    logger.error(f"Error in detector {name}: {e}")
            # Also add Haar detections for completeness
            all_detections.extend(self._detect_haar(image_array))
            # Ensemble overlapping detections
            return self._ensemble_detections(all_detections)

    def _detect_haar(self, image_array: np.ndarray) -> List[Dict]:
        """Haar cascade detection."""
        gray = cv2.cvtColor(image_array, cv2.COLOR_RGB2GRAY)
        faces = self.face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
        )
        results = []
        for x, y, w, h in faces:
            # Heuristic confidence based on face size
            img_area = image_array.shape[0] * image_array.shape[1]
            face_area = w * h
            conf = min(face_area / (img_area * 0.1), 0.95)
            results.append(
                {
                    "method": "haar_cascade",
                    "bbox": (x, y, w, h),
                    "confidence": float(conf),
                    "landmarks": None,
                }
            )
        return results

    def _detect_opencv_dnn(self, image: np.ndarray, det_info: Dict) -> List[Dict]:
        net = det_info["model"]
        h, w = image.shape[:2]
        blob = cv2.dnn.blobFromImage(image, 1.0, (300, 300), (104.0, 177.0, 123.0))
        net.setInput(blob)
        detections = net.forward()
        faces = []
        for i in range(detections.shape[2]):
            conf = detections[0, 0, i, 2]
            if conf > det_info["conf_thresh"]:
                box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                x1, y1, x2, y2 = box.astype("int")
                x, y, w_, h_ = x1, y1, x2 - x1, y2 - y1
                faces.append(
                    {
                        "method": "opencv_dnn",
                        "bbox": (x, y, w_, h_),
                        "confidence": float(conf),
                        "landmarks": None,
                    }
                )
        return faces

    def _detect_mediapipe(self, image: np.ndarray, det_info: Dict) -> List[Dict]:
        mp_detection = det_info["model"]
        rgb = cv2.cvtColor(image, cv2.COLOR_RGB2RGB)
        results = mp_detection.process(rgb)
        faces = []
        if results.detections:
            h, w = image.shape[:2]
            for detection in results.detections:
                bbox = detection.location_data.relative_bounding_box
                x = int(bbox.xmin * w)
                y = int(bbox.ymin * h)
                w_ = int(bbox.width * w)
                h_ = int(bbox.height * h)
                conf = detection.score[0]
                faces.append(
                    {
                        "method": "mediapipe",
                        "bbox": (x, y, w_, h_),
                        "confidence": float(conf),
                        "landmarks": None,
                    }
                )
        return faces

    def _detect_dlib_hog(self, image: np.ndarray, det_info: Dict) -> List[Dict]:
        detector = det_info["model"]
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        rects = detector(gray, 1)
        faces = []
        for rect in rects:
            x = rect.left()
            y = rect.top()
            w = rect.right() - x
            h = rect.bottom() - y
            faces.append(
                {
                    "method": "dlib_hog",
                    "bbox": (x, y, w, h),
                    "confidence": 0.85,
                    "landmarks": None,
                }
            )
        return faces

    def _detect_dlib_cnn(self, image: np.ndarray, det_info: Dict) -> List[Dict]:
        detector = det_info["model"]
        rgb = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        dets = detector(rgb, 1)
        faces = []
        for det in dets:
            rect = det.rect
            x = rect.left()
            y = rect.top()
            w = rect.right() - x
            h = rect.bottom() - y
            faces.append(
                {
                    "method": "dlib_cnn",
                    "bbox": (x, y, w, h),
                    "confidence": float(det.confidence),
                    "landmarks": None,
                }
            )
        return faces

    def _ensemble_detections(
        self, detections: List[Dict], iou_threshold: float = 0.5
    ) -> List[Dict]:
        """Group overlapping detections and average confidence (weighted by method)."""
        if not detections:
            return []

        method_weights = {
            "haar_cascade": 0.6,
            "opencv_dnn": 0.8,
            "mediapipe": 0.85,
            "dlib_hog": 0.7,
            "dlib_cnn": 0.9,
        }

        # Group by IoU
        groups = []
        used = [False] * len(detections)

        def iou(bbox1, bbox2):
            x1, y1, w1, h1 = bbox1
            x2, y2, w2, h2 = bbox2
            xi1 = max(x1, x2)
            yi1 = max(y1, y2)
            xi2 = min(x1 + w1, x2 + w2)
            yi2 = min(y1 + h1, y2 + h2)
            inter = max(0, xi2 - xi1) * max(0, yi2 - yi1)
            area1 = w1 * h1
            area2 = w2 * h2
            union = area1 + area2 - inter
            return inter / union if union > 0 else 0

        for i, det_i in enumerate(detections):
            if used[i]:
                continue
            group = [det_i]
            used[i] = True
            for j, det_j in enumerate(detections):
                if used[j]:
                    continue
                if iou(det_i["bbox"], det_j["bbox"]) > iou_threshold:
                    group.append(det_j)
                    used[j] = True
            groups.append(group)

        # Merge each group
        merged = []
        for group in groups:
            total_weight = 0.0
            weighted_conf = 0.0
            best_bbox = group[0]["bbox"]
            best_conf = group[0]["confidence"]
            for det in group:
                w = method_weights.get(det["method"], 0.5)
                weighted_conf += det["confidence"] * w
                total_weight += w
                if det["confidence"] > best_conf:
                    best_conf = det["confidence"]
                    best_bbox = det["bbox"]
            avg_conf = weighted_conf / total_weight if total_weight > 0 else best_conf
            merged.append(
                {
                    "method": "ensemble",
                    "bbox": best_bbox,
                    "confidence": avg_conf,
                    "landmarks": None,
                    "all_detections": group,
                }
            )
        return merged

    def validate_face_image(self, image_array: np.ndarray) -> Tuple[bool, str]:
        """Basic validation: at least one face, reasonable size, brightness, sharpness."""
        try:
            h, w = image_array.shape[:2]
            if h < 100 or w < 100:
                return False, "Image too small (minimum 100x100 pixels)"

            faces = self.detect_faces_multi_method(image_array)
            if len(faces) == 0:
                return False, "No face detected"
            if len(faces) > 1:
                return False, "Multiple faces detected – please provide a single face"

            x, y, w_box, h_box = faces[0]["bbox"]
            face_region = image_array[y : y + h_box, x : x + w_box]
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

    def calculate_face_quality_score(
        self, image_array: np.ndarray, face_bbox: Tuple
    ) -> float:
        """Quality score based on brightness, contrast, sharpness, and alignment."""
        try:
            x, y, w, h = face_bbox
            face_region = image_array[y : y + h, x : x + w]
            if face_region.size == 0:
                return 0.0
            gray_face = cv2.cvtColor(face_region, cv2.COLOR_RGB2GRAY)

            brightness = np.mean(gray_face)
            brightness_score = 1.0 - abs(brightness - 127) / 127
            contrast = np.std(gray_face)
            contrast_score = min(contrast / 50, 1.0)
            sharpness = cv2.Laplacian(gray_face, cv2.CV_64F).var()
            sharpness_score = min(sharpness / 100, 1.0)

            # Use face_utils to get alignment score (if possible)
            alignment_score = 0.5
            try:
                aligned = face_utils.align_face(image_array, face_bbox)
                if aligned is not None:
                    alignment_score = 0.9  # placeholder
            except Exception:
                pass

            quality = (
                brightness_score * 0.2
                + contrast_score * 0.2
                + sharpness_score * 0.3
                + alignment_score * 0.3
            )
            return max(0.0, min(quality, 1.0))
        except Exception as e:
            logger.error(f"Quality score error: {str(e)}")
            return 0.0

    def extract_face_encoding_multi_method(
        self, image_array: np.ndarray, face_bbox: Tuple
    ) -> Dict[str, Any]:
        """
        Extract face encoding using the best available method (face_recognition, dlib, or None).
        Returns dict with 'encoding' (numpy array) and 'method'.
        """
        x, y, w, h = face_bbox
        face_img = image_array[y : y + h, x : x + w]
        if face_img.size == 0:
            return {"encoding": None, "method": "none"}

        # Try face_recognition first (highest quality)
        if FACE_RECOGNITION_AVAILABLE:
            try:
                rgb_face = cv2.cvtColor(face_img, cv2.COLOR_RGB2RGB)
                encodings = face_recognition.face_encodings(rgb_face)
                if encodings:
                    return {"encoding": encodings[0], "method": "face_recognition"}
            except Exception as e:
                logger.warning(f"face_recognition encoding failed: {e}")

        # Fallback to dlib ResNet if available
        if DLIB_AVAILABLE:
            try:
                # Need shape predictor and recognition model
                sp_path = "models/shape_predictor_68_face_landmarks.dat"
                rec_model_path = "models/dlib_face_recognition_resnet_model_v1.dat"
                if os.path.exists(sp_path) and os.path.exists(rec_model_path):
                    sp = dlib.shape_predictor(sp_path)
                    facerec = dlib.face_recognition_model_v1(rec_model_path)
                    # Convert bbox to dlib rectangle
                    rect = dlib.rectangle(x, y, x + w, y + h)
                    shape = sp(image_array, rect)
                    encoding = np.array(
                        facerec.compute_face_descriptor(image_array, shape)
                    )
                    return {"encoding": encoding, "method": "dlib_resnet"}
            except Exception as e:
                logger.warning(f"dlib encoding failed: {e}")

        return {"encoding": None, "method": "none"}


# ----------------------------------------------------------------------
# KNNFaceService – K‑Nearest Neighbors for face similarity
# ----------------------------------------------------------------------
class KNNFaceService:
    """
    KNN similarity service that works with any face encodings.
    Requires pre‑computed encodings (supplied via add_face_encoding or loaded from disk).
    """

    def __init__(self, model_path: str = "data/face_knn_model.pkl", k: int = 3):
        self.model_path = model_path
        self.k = k
        self.face_encodings: List[np.ndarray] = []
        self.voter_ids: List[str] = []
        self.threshold = 0.65  # similarity threshold (cosine or euclidean)
        self._load_model()
        logger.info(
            f"KNNFaceService initialized (k={k}, encodings={len(self.face_encodings)})"
        )

    def _load_model(self):
        """Load previously saved KNN model if exists."""
        if os.path.exists(self.model_path):
            try:
                with open(self.model_path, "rb") as f:
                    data = pickle.load(f)
                self.face_encodings = data.get("encodings", [])
                self.voter_ids = data.get("voter_ids", [])
                logger.info(
                    f"Loaded KNN model with {len(self.face_encodings)} encodings"
                )
            except Exception as e:
                logger.error(f"Failed to load KNN model: {e}")

    def _save_model(self):
        """Persist KNN model to disk."""
        try:
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            with open(self.model_path, "wb") as f:
                pickle.dump(
                    {"encodings": self.face_encodings, "voter_ids": self.voter_ids}, f
                )
            logger.debug("KNN model saved")
        except Exception as e:
            logger.error(f"Failed to save KNN model: {e}")

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity between two vectors."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return np.dot(a, b) / (norm_a * norm_b)

    def add_face_encoding(self, encoding: np.ndarray, voter_id: str) -> bool:
        """Add a face encoding to the KNN model."""
        if encoding is None:
            return False
        self.face_encodings.append(encoding)
        self.voter_ids.append(voter_id)
        self._save_model()
        return True

    def find_similar_faces(
        self, query_encoding: np.ndarray, k: Optional[int] = None
    ) -> List[Dict]:
        """Return top‑k most similar faces with similarity scores."""
        if query_encoding is None or len(self.face_encodings) == 0:
            return []
        k = k or self.k
        k = min(k, len(self.face_encodings))

        similarities = []
        for enc, vid in zip(self.face_encodings, self.voter_ids):
            sim = self._cosine_similarity(query_encoding, enc)
            similarities.append((vid, sim))
        similarities.sort(key=lambda x: x[1], reverse=True)
        return [
            {"voter_id": vid, "similarity": float(sim)} for vid, sim in similarities[:k]
        ]

    def find_duplicate(
        self, query_encoding: np.ndarray, threshold: Optional[float] = None
    ) -> Dict:
        """Check if query encoding matches any existing face above threshold."""
        if query_encoding is None or len(self.face_encodings) == 0:
            return {"is_duplicate": False, "similarity": 0.0, "voter_id": None}
        thresh = threshold or self.threshold
        best_vid = None
        best_sim = 0.0
        for enc, vid in zip(self.face_encodings, self.voter_ids):
            sim = self._cosine_similarity(query_encoding, enc)
            if sim > best_sim:
                best_sim = sim
                best_vid = vid
        is_dup = best_sim >= thresh
        return {
            "is_duplicate": is_dup,
            "similarity": best_sim,
            "voter_id": best_vid if is_dup else None,
        }

    def verify_face(self, query_encoding: np.ndarray, claimed_voter_id: str) -> Dict:
        """Verify if query encoding matches a specific claimed voter."""
        if query_encoding is None:
            return {"verified": False, "confidence": 0.0}
        # Find index of claimed voter
        try:
            idx = self.voter_ids.index(claimed_voter_id)
            encoding = self.face_encodings[idx]
            sim = self._cosine_similarity(query_encoding, encoding)
            verified = sim >= self.threshold
            return {"verified": verified, "confidence": float(sim)}
        except ValueError:
            return {"verified": False, "confidence": 0.0, "error": "Voter not found"}

    def get_statistics(self) -> Dict:
        return {
            "total_encodings": len(self.face_encodings),
            "unique_voters": len(set(self.voter_ids)),
            "model_path": self.model_path,
            "threshold": self.threshold,
            "k": self.k,
        }


# ----------------------------------------------------------------------
# HybridFaceRecognitionService – Main entry point for registration/verification
# ----------------------------------------------------------------------
class HybridFaceRecognitionService:
    """
    Full hybrid service: detection + encoding + KNN matching.
    Uses MultiMethodFaceService for detection and quality, KNNFaceService for matching.
    """

    def __init__(
        self, knn_model_path: str = "data/face_knn_model.pkl", fast_mode: bool = False
    ):
        self.detection_service = MultiMethodFaceService(
            enable_ensemble=not fast_mode, fast_mode=fast_mode
        )
        self.knn_service = KNNFaceService(knn_model_path)
        self.fast_mode = fast_mode
        logger.info("HybridFaceRecognitionService initialized (full hybrid mode)")

    def _image_to_encoding(
        self, image_data: str
    ) -> Tuple[Optional[np.ndarray], Optional[Dict], Dict]:
        """
        Convert base64 image -> detect face -> extract encoding + quality info.
        Returns (encoding, face_info, quality_details)
        """
        try:
            # Convert to numpy
            img_array = self.detection_service.base64_to_image(image_data)
            # Preprocess
            img_array = self.detection_service.preprocess_image(img_array)
            # Detect faces
            faces = self.detection_service.detect_faces_multi_method(img_array)
            if not faces:
                return None, None, {"error": "No face detected"}
            # Use highest confidence face
            best_face = max(faces, key=lambda f: f["confidence"])
            bbox = best_face["bbox"]
            # Validate and compute quality
            quality_score = self.detection_service.calculate_face_quality_score(
                img_array, bbox
            )
            # Extract encoding
            encoding_result = self.detection_service.extract_face_encoding_multi_method(
                img_array, bbox
            )
            encoding = encoding_result["encoding"]
            if encoding is None:
                return (
                    None,
                    best_face,
                    {
                        "error": "Could not extract face encoding (recognition backend missing?)",
                        "quality": quality_score,
                    },
                )
            return (
                encoding,
                best_face,
                {
                    "quality": quality_score,
                    "encoding_method": encoding_result["method"],
                },
            )
        except Exception as e:
            logger.error(f"Image to encoding error: {str(e)}")
            return None, None, {"error": str(e)}

    def register_face(self, voter_id: str, image_data: str) -> FaceRecognitionResult:
        """
        Register a new face for a voter.
        Returns FaceRecognitionResult indicating success/failure.
        """
        start_time = time.time()
        try:
            encoding, face_info, quality_info = self._image_to_encoding(image_data)
            if encoding is None:
                return FaceRecognitionResult(
                    is_match=False,
                    confidence=0.0,
                    method="register_fail",
                    processing_time=time.time() - start_time,
                    details={
                        "error": quality_info.get("error", "Encoding extraction failed")
                    },
                    quality_score=quality_info.get("quality", 0.0),
                )
            # Add to KNN
            success = self.knn_service.add_face_encoding(encoding, voter_id)
            if success:
                return FaceRecognitionResult(
                    is_match=True,
                    confidence=1.0,
                    voter_id=voter_id,
                    method="knn_register",
                    processing_time=time.time() - start_time,
                    details={"encoding_method": quality_info.get("encoding_method")},
                    quality_score=quality_info.get("quality", 0.0),
                )
            else:
                return FaceRecognitionResult(
                    is_match=False,
                    confidence=0.0,
                    method="register_fail",
                    processing_time=time.time() - start_time,
                    details={"error": "Failed to store encoding"},
                    quality_score=quality_info.get("quality", 0.0),
                )
        except Exception as e:
            logger.error(f"Registration error: {str(e)}")
            return FaceRecognitionResult(
                is_match=False,
                confidence=0.0,
                method="error",
                processing_time=time.time() - start_time,
                details={"error": str(e)},
                quality_score=0.0,
            )

    def verify_face(self, voter_id: str, image_data: str) -> FaceRecognitionResult:
        """
        Verify if the provided image matches the stored face for voter_id.
        """
        start_time = time.time()
        try:
            encoding, face_info, quality_info = self._image_to_encoding(image_data)
            if encoding is None:
                return FaceRecognitionResult(
                    is_match=False,
                    confidence=0.0,
                    method="verify_fail",
                    processing_time=time.time() - start_time,
                    details={
                        "error": quality_info.get("error", "Encoding extraction failed")
                    },
                    quality_score=quality_info.get("quality", 0.0),
                )
            verification = self.knn_service.verify_face(encoding, voter_id)
            return FaceRecognitionResult(
                is_match=verification.get("verified", False),
                confidence=verification.get("confidence", 0.0),
                voter_id=voter_id,
                method="knn_verify",
                processing_time=time.time() - start_time,
                details={"verification": verification, "quality": quality_info},
                quality_score=quality_info.get("quality", 0.0),
            )
        except Exception as e:
            logger.error(f"Verification error: {str(e)}")
            return FaceRecognitionResult(
                is_match=False,
                confidence=0.0,
                method="error",
                processing_time=time.time() - start_time,
                details={"error": str(e)},
                quality_score=0.0,
            )

    def find_similar_faces(self, image_data: str, k: int = 5) -> List[Dict]:
        """Find top‑k similar faces in the database to the query image."""
        try:
            encoding, _, _ = self._image_to_encoding(image_data)
            if encoding is None:
                return []
            return self.knn_service.find_similar_faces(encoding, k)
        except Exception as e:
            logger.error(f"Similar faces error: {str(e)}")
            return []

    def get_system_stats(self) -> Dict:
        """Return diagnostic information about the service."""
        stats = {
            "status": (
                "operational"
                if (FACE_RECOGNITION_AVAILABLE or DLIB_AVAILABLE)
                else "limited"
            ),
            "detection_ensemble": self.detection_service.enable_ensemble,
            "fast_mode": self.fast_mode,
            "available_libraries": {
                "mediapipe": MEDIAPIPE_AVAILABLE,
                "dlib": DLIB_AVAILABLE,
                "face_recognition": FACE_RECOGNITION_AVAILABLE,
            },
            "knn": self.knn_service.get_statistics(),
        }
        return stats

    def reindex_knn_from_database(self, face_encodings_data: List[Dict]) -> int:
        """
        Bulk load face encodings from database (list of {voter_id, encoding}).
        Returns number of added entries.
        """
        count = 0
        for entry in face_encodings_data:
            voter_id = entry.get("voter_id")
            encoding = entry.get("encoding")
            if voter_id and encoding is not None:
                self.knn_service.add_face_encoding(encoding, voter_id)
                count += 1
        return count


# ----------------------------------------------------------------------
# Global instances (backward‑compatible with your existing code)
# ----------------------------------------------------------------------
multi_face_service = MultiMethodFaceService()  # detection only
knn_face_service = KNNFaceService()  # KNN matcher (requires external encodings)
hybrid_face_service = HybridFaceRecognitionService()  # full hybrid service
face_service = multi_face_service  # alias for detection
