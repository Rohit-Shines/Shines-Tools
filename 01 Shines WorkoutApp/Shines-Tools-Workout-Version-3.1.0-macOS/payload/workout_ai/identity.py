from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .database import WorkoutDatabase


@dataclass
class IdentityResult:
    name: str
    score: float
    recognized: bool


class FaceIdentity:
    """Local YuNet + SFace identity recognition.

    Identity is established at session start and then locked. Continuous face
    recognition is intentionally avoided during floor exercises where the face
    can be side-on or occluded.
    """

    def __init__(self, model_dir: Path, database: WorkoutDatabase, threshold: float = 0.42):
        self.model_dir = model_dir
        self.database = database
        self.threshold = threshold
        detector_path = model_dir / "face_detection_yunet_2023mar.onnx"
        recognizer_path = model_dir / "face_recognition_sface_2021dec.onnx"
        self.available = detector_path.exists() and recognizer_path.exists()
        self.detector = None
        self.recognizer = None
        if self.available:
            self.detector = cv2.FaceDetectorYN.create(
                str(detector_path), "", (320, 320), 0.88, 0.3, 5000
            )
            self.recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), "")

    def _largest_face(self, frame: np.ndarray):
        if not self.available or self.detector is None:
            return None
        height, width = frame.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(frame)
        if faces is None or len(faces) == 0:
            return None
        return max(faces, key=lambda face: float(face[2] * face[3]))

    def embedding(self, frame: np.ndarray) -> np.ndarray | None:
        face = self._largest_face(frame)
        if face is None or self.recognizer is None:
            return None
        aligned = self.recognizer.alignCrop(frame, face)
        feature = self.recognizer.feature(aligned).reshape(-1).astype(np.float32)
        norm = float(np.linalg.norm(feature))
        return feature / norm if norm > 1e-8 else None

    def recognize(self, frame: np.ndarray, fallback: str = "User") -> IdentityResult:
        query = self.embedding(frame)
        stored = self.database.embeddings()
        if query is None or not stored:
            return IdentityResult(fallback, 0.0, False)
        best_name = fallback
        best_score = -1.0
        for name, values in stored.items():
            reference = np.asarray(values, dtype=np.float32)
            score = float(np.dot(query, reference) / max(np.linalg.norm(reference), 1e-8))
            if score > best_score:
                best_name, best_score = name, score
        return IdentityResult(best_name if best_score >= self.threshold else fallback, best_score, best_score >= self.threshold)

    def enroll(self, camera: cv2.VideoCapture, name: str, samples: int = 18) -> bool:
        if not self.available:
            raise RuntimeError("Face models are missing. Run install.command first.")
        embeddings: list[np.ndarray] = []
        deadline = time.monotonic() + 45.0
        last_capture = 0.0
        while len(embeddings) < samples and time.monotonic() < deadline:
            ok, frame = camera.read()
            if not ok:
                continue
            frame = cv2.flip(frame, 1)
            feature = self.embedding(frame)
            now = time.monotonic()
            if feature is not None and now - last_capture >= 0.22:
                embeddings.append(feature)
                last_capture = now
            cv2.putText(frame, f"Enroll {name}: {len(embeddings)}/{samples}", (30, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255,255,255), 2)
            cv2.putText(frame, "Look at camera and slowly turn left/right. Q cancels.", (30, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (80,230,255), 2)
            cv2.imshow("Profile Enrollment", frame)
            key = cv2.waitKey(80) & 0xFF
            if key in (ord("q"), 27):
                return False
        if len(embeddings) < max(8, samples // 2):
            return False
        mean = np.mean(np.stack(embeddings), axis=0)
        mean /= max(float(np.linalg.norm(mean)), 1e-8)
        self.database.save_embedding(name, mean.astype(float).tolist())
        return True
