import cv2
import os
from ultralytics import YOLO

def run_test():
    model_path = os.path.abspath(r"D:\Projects\Smart Home\models\classroom_cctv_yolov8n.pt")
    video_path = os.path.abspath(r"D:\Projects\Smart Home\models\Classroom Video\test_demo_clip.mp4")
    output_image = os.path.abspath(r"D:\Projects\Smart Home\test_result.jpg")

    print(f"[TEST] Loading Model: {model_path}")
    model = YOLO(model_path)

    print(f"[TEST] Reading frame from test demo video: {video_path}")
    cap = cv2.VideoCapture(video_path)
    
    # Grab frame around 2 seconds in (frame 50)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 50)
    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        print("[ERROR] Could not read frame from test video!")
        return

    print("[TEST] Running YOLOv8n inference...")
    results = model(frame, conf=0.35)[0]

    # Render detection boxes on frame
    annotated_frame = results.plot()

    cv2.imwrite(output_image, annotated_frame)
    
    boxes = results.boxes
    print("\n" + "="*70)
    print(" 🎯 DETECTION RESULTS ON UNSEEN TEST VIDEO:")
    print("="*70)
    print(f" Total Students Detected: {len(boxes)}")
    for i, b in enumerate(boxes):
        conf = float(b.conf[0]) * 100
        x1, y1, x2, y2 = map(int, b.xyxy[0])
        print(f"  [Student {i+1}] Confidence: {conf:.1f}% | Coordinates: ({x1},{y1}) to ({x2},{y2})")

    print("\n" + "="*70)
    print(f" 🖼️ Visual Result Image Saved At:")
    print(f"    {output_image}")
    print("="*70 + "\n")

if __name__ == "__main__":
    run_test()
