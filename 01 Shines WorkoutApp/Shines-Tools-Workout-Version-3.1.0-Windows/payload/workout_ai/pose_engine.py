from __future__ import annotations

from pathlib import Path

import cv2
import mediapipe as mp

from .geometry import Landmark, PoseFrame


class PoseEngine:
    def __init__(
        self,
        model_path: Path,
        min_pose_detection_confidence: float = 0.68,
        min_pose_presence_confidence: float = 0.68,
        min_tracking_confidence: float = 0.72,
    ):
        if not model_path.exists():
            raise FileNotFoundError(
                f"Pose model missing: {model_path}. Run install.command to download it."
            )
        base_options = mp.tasks.BaseOptions(model_asset_path=str(model_path))
        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=float(min_pose_detection_confidence),
            min_pose_presence_confidence=float(min_pose_presence_confidence),
            min_tracking_confidence=float(min_tracking_confidence),
            output_segmentation_masks=False,
        )
        self.landmarker = mp.tasks.vision.PoseLandmarker.create_from_options(options)
        self.connections = mp.tasks.vision.PoseLandmarksConnections.POSE_LANDMARKS
        self.last_timestamp_ms = -1

    def close(self) -> None:
        self.landmarker.close()

    def process(self, frame_bgr, timestamp_seconds: float) -> PoseFrame | None:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        timestamp_ms = max(self.last_timestamp_ms + 1, int(timestamp_seconds * 1000))
        self.last_timestamp_ms = timestamp_ms
        result = self.landmarker.detect_for_video(image, timestamp_ms)
        if not result.pose_landmarks:
            return None
        normalized = [
            Landmark(
                x=float(item.x), y=float(item.y), z=float(item.z),
                visibility=float(getattr(item, "visibility", 1.0) or 0.0),
                presence=float(getattr(item, "presence", 1.0) or 0.0),
            )
            for item in result.pose_landmarks[0]
        ]
        world_source = result.pose_world_landmarks[0] if result.pose_world_landmarks else result.pose_landmarks[0]
        world = [
            Landmark(
                x=float(item.x), y=float(item.y), z=float(item.z),
                visibility=float(getattr(item, "visibility", 1.0) or 0.0),
                presence=float(getattr(item, "presence", 1.0) or 0.0),
            )
            for item in world_source
        ]
        return PoseFrame(normalized, world, timestamp_seconds)
