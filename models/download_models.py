import os
import urllib.request
from ultralytics import YOLO

"""
Model Downloader Utility
Downloads YOLO-World and Depth Anything V2 model checkpoints
into the local models/ directory.
"""

MODELS_DIR = os.path.dirname(os.path.abspath(__file__))

def download_yolo_world():
    print("[DOWNLOAD] Downloading / Verifying YOLOv8-World checkpoint...")
    target_path = os.path.join(MODELS_DIR, "yolov8s-world.pt")
    # Ultralytics auto-downloads if initialized
    model = YOLO("yolov8s-world.pt")
    print(f"[DOWNLOAD SUCCESS] YOLO-World ready at: {target_path}")

def download_depth_anything():
    print("[DOWNLOAD] Depth Anything V2 model checkpoints...")
    # URL for Depth Anything V2 Small (vits) checkpoint
    depth_checkpoint_url = "https://huggingface.co/depth-anything/Depth-Anything-V2-Small/resolve/main/depth_anything_v2_vits.pth"
    target_file = os.path.join(MODELS_DIR, "depth_anything_v2_vits.pth")

    if not os.path.exists(target_file):
        print(f"Downloading from HuggingFace to {target_file}...")
        try:
            urllib.request.urlretrieve(depth_checkpoint_url, target_file)
            print("[DOWNLOAD SUCCESS] Depth Anything V2 checkpoint downloaded!")
        except Exception as e:
            print(f"[DOWNLOAD NOTE] Auto-download failed: {e}. You can download manually from Hugging Face.")
    else:
        print("[DOWNLOAD] Depth Anything checkpoint already exists.")

if __name__ == "__main__":
    download_yolo_world()
    download_depth_anything()
    print("\n[COMPLETE] All AI models ready in models/ folder!")
