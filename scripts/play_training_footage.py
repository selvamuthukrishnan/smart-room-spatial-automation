import os
import cv2
import time
import argparse
from ultralytics import YOLO

def main():
    parser = argparse.ArgumentParser(description="Play Classroom Training Footage with Fine-Tuned 24MB YOLO Model")
    parser.add_argument("--video", type=str, default=r"models\Classroom Video\EEE1_classroom.mp4", help="Path to video file")
    parser.add_argument("--model", type=str, default=r"models\classroom_cctv_yolov8s_world.pt", help="Path to YOLO model")
    parser.add_argument("--conf", type=float, default=0.35, help="Detection confidence threshold")
    parser.add_argument("--imgsz", type=int, default=512, help="Inference image size")
    parser.add_argument("--skip", type=int, default=1, help="Run YOLO inference every N frames (1 = every frame)")
    args = parser.parse_args()

    video_path = os.path.abspath(args.video)
    model_path = os.path.abspath(args.model)

    if not os.path.exists(video_path):
        print(f"[ERROR] Video file not found at: {video_path}")
        return

    if not os.path.exists(model_path):
        print(f"[WARNING] 24MB model not found at {model_path}, checking 6MB model...")
        fallback = os.path.abspath(r"models\classroom_cctv_yolov8n.pt")
        if os.path.exists(fallback):
            model_path = fallback
        else:
            model_path = os.path.abspath("yolov8s-world.pt")

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

    print("="*75)
    print(" 🎬 CLASSROOM TRAINING FOOTAGE LIVE DETECTION PLAYER")
    print(f" 📹 Video: {video_path}")
    print(f" 🧠 Model: {model_path} ({os.path.getsize(model_path) / (1024*1024):.1f} MB)")
    print(f" ⚙️ Conf: {args.conf} | ImgSz: {args.imgsz}")
    print("="*75)
    print(" 🌐 DIGITAL TWIN DASHBOARD:")
    print("    💻 Local URL:      http://localhost:5000")
    print(f"    📶 Same Wi-Fi Link: http://{wifi_ip}:5000")
    print("="*75)
    print(" ⌨️  KEYBOARD CONTROLS:")
    print("    [SPACE] : Pause / Resume")
    print("    [F]     : Fast-forward 5 seconds")
    print("    [R]     : Rewind 5 seconds")
    print("    [S]     : Save Screenshot with detections")
    print("    [Q/ESC] : Quit / Exit player")
    print("="*75)

    # Automatically launch dashboard in browser
    try:
        webbrowser.open("http://localhost:5000")
        print("\n[INFO] 🌐 Automatically launching dashboard in browser: http://localhost:5000")
    except Exception:
        pass

    print("\n[INFO] Loading YOLO model into memory...")
    model = YOLO(model_path)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[ERROR] Could not open video file: {video_path}")
        return

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    duration_sec = total_frames / video_fps
    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    window_name = "Classroom Training Footage - 24MB YOLO Detection Player"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 720)

    try:
        cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
    except Exception:
        pass

    paused = False
    last_boxes = []
    prev_time = time.time()
    fps_display = 0.0
    frame_count = 0

    while True:
        if not paused:
            ret, frame = cap.read()
            if not ret:
                print("\n[INFO] Reached end of video, looping back to start...")
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            current_frame_idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            current_sec = current_frame_idx / video_fps

            # Run detection every args.skip frames (default: 1 = every frame)
            if frame_count % args.skip == 0:
                results = model(frame, conf=args.conf, imgsz=args.imgsz, verbose=False)[0]
                last_boxes = results.boxes

            frame_count += 1

            # Calculate FPS
            curr_time = time.time()
            fps_display = 1.0 / max(curr_time - prev_time, 0.001)
            prev_time = curr_time

            # Draw detection bounding boxes
            display_frame = frame.copy()
            num_detected = len(last_boxes)

            for idx, box in enumerate(last_boxes):
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0]) * 100

                # Bounding box
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 255, 120), 2)

                # Label badge
                label = f"Student {idx+1}: {conf:.0f}%"
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.rectangle(display_frame, (x1, max(0, y1 - 22)), (x1 + tw + 8, max(0, y1)), (0, 200, 100), -1)
                cv2.putText(display_frame, label, (x1 + 4, max(16, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)

            # Draw HUD Overlay Banner
            overlay = display_frame.copy()
            cv2.rectangle(overlay, (0, 0), (orig_w, 65), (15, 20, 25), -1)
            cv2.addWeighted(overlay, 0.75, display_frame, 0.25, 0, display_frame)

            # HUD Info
            status_text = f"MODEL: 24MB Fine-Tuned (YOLOv8s-World)  |  STUDENTS DETECTED: {num_detected}"
            time_text = f"{int(current_sec//60):02d}:{int(current_sec%60):02d} / {int(duration_sec//60):02d}:{int(duration_sec%60):02d}  |  FPS: {fps_display:.1f}  |  Frame: {current_frame_idx}/{total_frames}"
            help_text = "[SPACE] Pause | [F] +5s | [R] -5s | [S] Screenshot | [Q] Quit"

            cv2.putText(display_frame, status_text, (20, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (50, 255, 120), 2, cv2.LINE_AA)
            cv2.putText(display_frame, time_text, (20, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1, cv2.LINE_AA)
            (hw, _), _ = cv2.getTextSize(help_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.putText(display_frame, help_text, (orig_w - hw - 20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 200, 255), 1, cv2.LINE_AA)

        cv2.imshow(window_name, display_frame)

        # Handle keyboard input
        key = cv2.waitKey(1 if not paused else 50) & 0xFF
        if key in [ord('q'), ord('Q'), 27]: # Q or ESC
            print("\n[INFO] Player closed by user.")
            break
        elif key == ord(' '): # Space to pause
            paused = not paused
            print(f"[CONTROL] {'PAUSED' if paused else 'RESUMED'}")
        elif key in [ord('f'), ord('F')]: # Fast forward 5s
            cur_f = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(total_frames - 1, cur_f + int(video_fps * 5)))
            print(f"[CONTROL] Jumped forward +5 seconds")
        elif key in [ord('r'), ord('R')]: # Rewind 5s
            cur_f = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, cur_f - int(video_fps * 5)))
            print(f"[CONTROL] Jumped backward -5 seconds")
        elif key in [ord('s'), ord('S')]: # Screenshot
            shot_name = f"detected_training_frame_{int(cap.get(cv2.CAP_PROP_POS_FRAMES))}.jpg"
            cv2.imwrite(shot_name, display_frame)
            print(f"[SAVED] Screenshot saved to: {shot_name}")

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
