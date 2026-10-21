import os
import shutil
from ultralytics import YOLO

def train():
    data_yaml = os.path.abspath(r"D:\Projects\Smart Home\dataset\roboflow_yolov8\data.yaml")
    base_model = os.path.abspath(r"D:\Projects\Smart Home\yolov8n.pt")
    target_model = os.path.abspath(r"D:\Projects\Smart Home\models\classroom_cctv_yolov8n.pt")
    project_dir = os.path.abspath(r"D:\Projects\Smart Home\runs\detect\classroom_model")

    print("="*70)
    print(" 🚀 STARTING CLASSROOM CCTV YOLOv8n TRAINING (25 EPOCHS)")
    print(f" 📁 Dataset: {data_yaml}")
    print(f" ⚙️ Base Model: {base_model}")
    print(f" 🎯 Target Save Location: {target_model}")
    print("="*70)

    model = YOLO(base_model)
    results = model.train(
        data=data_yaml,
        epochs=25,
        imgsz=512,
        batch=16,
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

        print("\n" + "="*70)
        print(" [SUCCESS] Training Completed Successfully!")
        print(f" [SAVED] Model ready at: {target_model}")
        print(" 🌐 DIGITAL TWIN DASHBOARD:")
        print("    💻 Local PC URL:    http://localhost:5000")
        print(f"    📶 Same Wi-Fi Link: http://{wifi_ip}:5000")
        print("="*70 + "\n")

        try:
            webbrowser.open("http://localhost:5000")
            print(" [INFO] 🌐 Automatically launching dashboard in your browser...")
        except Exception:
            pass
    else:
        print("[WARNING] best.pt not found at:", best_weights)

if __name__ == "__main__":
    train()
