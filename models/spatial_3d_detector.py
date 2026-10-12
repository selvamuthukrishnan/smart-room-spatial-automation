import os
import torch
import cv2
import numpy as np
from ultralytics import YOLO

class Spatial3DDetector:
    """
    Spatial 3D Object & Human Detector
    Combines YOLO-World (Open-Vocabulary 2D Bounding Boxes) with
    Depth Anything V2 (Metric Monocular Depth Map) to compute real-world
    (X, Y, Z) 3D coordinates of humans and appliances.
    """
    def __init__(self, yolo_model_name="yolov8s-world.pt", device=None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        print(f"[3D DETECTOR] Using hardware device: {self.device}")

        # 1. Initialize YOLO-World
        print(f"[3D DETECTOR] Loading YOLO-World model: {yolo_model_name}...")
        self.yolo = YOLO(yolo_model_name)
        
        # Configure target classes for smart room
        self.target_classes = ["person", "ceiling fan", "light", "air conditioner", "laptop", "television"]
        self.yolo.set_classes(self.target_classes)

        # 2. Camera Intrinsics Parameters (Approximation for standard 720p/1080p webcam)
        # Default focal lengths and optical centers for 640x480 resolution
        self.fx = 500.0  # Focal length X
        self.fy = 500.0  # Focal length Y
        self.cx = 320.0  # Optical center X
        self.cy = 240.0  # Optical center Y

    def estimate_3d_coordinates(self, u, v, depth_z):
        """
        Projects 2D image coordinates (u, v) and depth (Z) into 3D camera frame coordinates (X, Y, Z)
        Formula:
            X = (u - cx) * Z / fx
            Y = (v - cy) * Z / fy
            Z = depth_z
        """
        X = ((u - self.cx) * depth_z) / self.fx
        Y = ((v - self.cy) * depth_z) / self.fy
        Z = depth_z
        return round(float(X), 2), round(float(Y), 2), round(float(Z), 2)

    def detect_and_locate_3d(self, frame, depth_map=None):
        """
        Processes a single frame:
        - Detects humans and electrical appliances
        - Samples depth map to calculate 3D centroid
        Returns structured list of detected entities with 3D positions
        """
        h, w = frame.shape[:2]
        self.cx = w / 2.0
        self.cy = h / 2.0

        # Run YOLO-World detection
        results = self.yolo(frame, verbose=False)[0]
        detected_entities = []

        for box in results.boxes:
            cls_id = int(box.cls[0])
            label = results.names[cls_id]
            conf = float(box.conf[0])
            
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            u_center = int((x1 + x2) / 2)
            v_center = int((y1 + y2) / 2)

            # Retrieve depth if depth map is supplied, otherwise fallback to bounding-box height heuristic
            if depth_map is not None:
                # Sample depth at object center
                depth_val = float(depth_map[v_center, u_center])
            else:
                # Approximation heuristic: inverse of bbox pixel height scaled to room meters
                bbox_h = max(y2 - y1, 1)
                depth_val = max(1.0, round(500.0 / bbox_h, 2))

            X, Y, Z = self.estimate_3d_coordinates(u_center, v_center, depth_val)

            detected_entities.append({
                "label": label,
                "confidence": round(conf, 2),
                "bbox_2d": [x1, y1, x2, y2],
                "pixel_centroid": (u_center, v_center),
                "position_3d": {"X_meters": X, "Y_meters": Y, "Z_meters": Z}
            })

        return detected_entities

if __name__ == "__main__":
    print("[TEST] Running Spatial 3D Detector self-test on simulated frame...")
    detector = Spatial3DDetector()
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    entities = detector.detect_and_locate_3d(dummy_frame)
    print(f"[TEST SUCCESS] Detector initialized successfully. Entities detected: {len(entities)}")
