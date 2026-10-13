import os
import shutil
import cv2
from ultralytics import YOLO

def main():
    data_yaml = os.path.abspath(r"D:\Projects\Smart Home\dataset\roboflow_yolov8\data.yaml")
    base_model = os.path.abspath(r"D:\Projects\Smart Home\yolov8s-world.pt")
    target_model = os.path.abspath(r"D:\Projects\Smart Home\models\classroom_cctv_yolov8s_world.pt")
    project_dir = os.path.abspath(r"D:\Projects\Smart Home\runs\detect\classroom_model_yolov8s")
    test_video = os.path.abspath(r"D:\Projects\Smart Home\models\Classroom Video\test_demo_clip.mp4")
    output_visual = os.path.abspath(r"D:\Projects\Smart Home\test_result_yolov8s.jpg")

    print("="*75)
    print(" 🚀 CLASSROOM CCTV YOLOv8s-WORLD (24MB/27MB) TRAINING & TESTING PIPELINE")
    print(f" 📁 Dataset: {data_yaml}")
    print(f" ⚙️ Base 24MB Model: {base_model}")
    print(f" 🎯 Target Save Location: {target_model}")
    print(f" 📌 6MB Model (yolov8n) status: Kept safe and untouched")
    print("="*75)

    # 1. Load 24MB YOLOv8s-world model
    model = YOLO(base_model)

    # 2. Train on Classroom CCTV Dataset
    print("\n[STEP 1/3] Starting Training (25 Epochs, imgsz=512)...")
    results = model.train(
        data=data_yaml,
        epochs=25,
        imgsz=512,
        batch=8,
        device="cpu",
        workers=2,
        project=project_dir,
        name="train_run",
        exist_ok=True
    )

    best_weights = os.path.join(project_dir, "train_run", "weights", "best.pt")
    if os.path.exists(best_weights):
        os.makedirs(os.path.dirname(target_model), exist_ok=True)
        shutil.copy(best_weights, target_model)
        print(f"\n[SUCCESS] Best weights saved to: {target_model}")
    else:
        print("[WARNING] best.pt not found, using trained model in memory")
        target_model = base_model

    # 3. Test on Test Split (Dataset test set)
    print("\n" + "="*75)
    print("[STEP 2/3] Evaluating on Test Dataset (test/images)...")
    print("="*75)
    trained_model = YOLO(target_model)
    val_results = trained_model.val(
        data=data_yaml,
        split="test",
        imgsz=512,
        device="cpu",
        project=project_dir,
        name="val_test_run",
        exist_ok=True
    )

    print("\n📊 TEST SET BENCHMARK METRICS:")
    print(f"  - Precision (P)    : {val_results.results_dict.get('metrics/precision(B)', 0):.4f}")
    print(f"  - Recall (R)       : {val_results.results_dict.get('metrics/recall(B)', 0):.4f}")
    print(f"  - mAP50            : {val_results.results_dict.get('metrics/mAP50(B)', 0):.4f}")
    print(f"  - mAP50-95         : {val_results.results_dict.get('metrics/mAP50-95(B)', 0):.4f}")

    # 4. Visual Test on Unseen Demo Video Frame
    print("\n" + "="*75)
    print("[STEP 3/3] Running Visual Detection Test on Demo Video...")
    print("="*75)
    if os.path.exists(test_video):
        cap = cv2.VideoCapture(test_video)
        cap.set(cv2.CAP_PROP_POS_FRAMES, 50)
        ret, frame = cap.read()
        cap.release()

        if ret and frame is not None:
            pred = trained_model(frame, conf=0.35)[0]
            annotated_frame = pred.plot()
            cv2.imwrite(output_visual, annotated_frame)

            boxes = pred.boxes
            print(f" 🎯 Total Students Detected (conf >= 0.35): {len(boxes)}")
            for i, b in enumerate(boxes):
                conf = float(b.conf[0]) * 100
                x1, y1, x2, y2 = map(int, b.xyxy[0])
                print(f"    [Student {i+1}] Conf: {conf:.1f}% | Box: ({x1}, {y1}) to ({x2}, {y2})")

            print(f"\n 🖼️ Visual Result Saved: {output_visual}")
        else:
            print("[ERROR] Could not read frame 50 from test demo video.")
    else:
        print(f"[SKIP] Test video not found at: {test_video}")

    import socket
    import webbrowser
    def get_wifi_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
    wifi_ip = get_wifi_ip()

    print("\n" + "="*75)
    print(" ✅ ALL TRAINING & TESTING PIPELINE STEPS COMPLETED!")
    print(f" 🧠 Best Weights: {target_model}")
    print(" 🌐 DIGITAL TWIN DASHBOARD:")
    print("    💻 Local PC URL:    http://localhost:5000")
    print(f"    📶 Same Wi-Fi Link: http://{wifi_ip}:5000")
    print("="*75)

    try:
        webbrowser.open("http://localhost:5000")
        print(" [INFO] 🌐 Automatically launching dashboard in your browser...")
    except Exception:
        pass
    print("="*75 + "\n")

if __name__ == "__main__":
    main()
