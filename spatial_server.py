import cv2
import sys
import time
import math
import requests
from ultralytics import YOLO

# =================================================================================
# PROJECT: Spatial AI Power Automation (Mobile Camera + 10s ECO Scanner)
# =================================================================================

# --- 📷 DUAL CAMERA CONFIGURATION (Phone Link / Webcam & Wi-Fi IP Stream) ---
# Supports:
#   1. Windows Phone Link / Local Webcam: 0 (or 1)
#   2. Wi-Fi IP Camera streams: "http://<PHONE_IP>:8080/video"
#   3. Automatic fallback: If IP stream is unreachable, automatically falls back to Phone Link / Webcam
CAMERA_SOURCE = 0  # Default: 0 for Phone Link (Connected Phone Camera) or Laptop Webcam
IP_CAMERA_URL = "http://10.105.4.198:8080/video"  # Optional Wi-Fi IP stream (e.g. IP Webcam app)

# Allow command-line override (e.g., python spatial_server.py http://192.168.43.1:8080/video)
if len(sys.argv) > 1:
    CAMERA_SOURCE = sys.argv[1]

# --- 🌐 ESP32 WI-FI CONFIGURATION ---
ESP32_IP = "http://192.168.43.125"  # Put your ESP32's IP address (printed on Serial Monitor)

# --- ⏱️ TIMING & DETECTION SETTINGS ---
SCAN_INTERVAL_SEC = 10.0   # Scans 1 frame every 10 seconds for power efficiency
PROXIMITY_RADIUS = 280     # Proximity radius in pixels around each appliance

print("[AI SERVER] Initializing YOLO-World Model...")
model = YOLO("yolov8s-world.pt")
model.set_classes(["person", "ceiling fan", "tube light"])

# Predefined Ceiling Appliance Zones (Mapped from your camera view)
APPLIANCE_ZONES = {
    "fan_1": {"pos": (330, 250), "name": "FAN 1 (LEFT)",   "active": False},
    "fan_2": {"pos": (640, 230), "name": "FAN 2 (CENTER)", "active": False},
    "light": {"pos": (740, 260), "name": "TUBE LIGHT",     "active": False}
}

def connect_camera(source=0):
    """
    Connects to camera. Supports both:
      - Windows Phone Link / Built-in Webcam (device 0 or 1)
      - Wi-Fi IP Camera streams (HTTP / RTSP)
    With automatic fallback if an IP stream is unreachable!
    """
    is_device_index = isinstance(source, int) or (isinstance(source, str) and str(source).isdigit())

    if is_device_index:
        idx = int(source)
        print(f"[CAMERA] Connecting to Device {idx} (Phone Link / Local Webcam)...")
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(idx)

        if cap.isOpened():
            print(f"[CAMERA SUCCESS] Connected to Device {idx} (Phone Link / Local Webcam)!")
            return cap
        else:
            print(f"[CAMERA WARNING] Unable to open Device {idx}!")
            return None

    # If source is an IP stream URL
    print(f"[CAMERA] Connecting to IP stream: {source}...")
    cap = cv2.VideoCapture(source)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        print(f"[CAMERA WARNING] Unable to reach IP stream at {source}!")
        print("[CAMERA FALLBACK] Automatically switching to Phone Link / Local Webcam (Device 0)...")
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(0)

        if cap.isOpened():
            print("[CAMERA SUCCESS] Fallback connected to Device 0 (Phone Link / Webcam)!")
            return cap
        else:
            print("[CAMERA ERROR] Both IP stream and local camera failed to open.")
            return None

    print("[CAMERA SUCCESS] Connected to Wi-Fi IP stream successfully!")
    return cap

cap = connect_camera(CAMERA_SOURCE)
window_name = "Spatial AI Power Automation Monitor"
cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

last_scan_time = 0
last_detected_humans = []
last_detected_appliances = []

def send_esp32_command(appliance_states):
    query = "&".join([f"{k}={'on' if v['active'] else 'off'}" for k, v in appliance_states.items()])
    url = f"{ESP32_IP}/control?{query}"
    try:
        requests.get(url, timeout=1)
    except Exception:
        pass  # ESP32 offline during local simulation

print("[AI SERVER] Started! Press 'q', 'Q', 'ESC', or close window to exit.")

while True:
    ret, frame = cap.read() if cap is not None else (False, None)
    if not ret or frame is None:
        print("[CAMERA] Stream paused or reconnecting... Retrying in 1s")
        time.sleep(1)
        if cap is not None:
            cap.release()
        cap = connect_camera(CAMERA_SOURCE)
        continue

    current_time = time.time()
    time_since_last_scan = current_time - last_scan_time
    remaining_time = max(0.0, SCAN_INTERVAL_SEC - time_since_last_scan)

    # =========================================================================
    # ⚡ 10-SECOND AI SCAN TRIGGER (Runs ONLY once every 10 seconds)
    # =========================================================================
    if time_since_last_scan >= SCAN_INTERVAL_SEC:
        print(f"\n[AI SCAN TRIGGER] Scanning frame from Mobile Camera at {time.strftime('%H:%M:%S')}...")
        last_scan_time = current_time

        # Run AI Model
        results = model(frame, verbose=False)[0]

        last_detected_humans = []
        last_detected_appliances = []

        for box in results.boxes:
            label = results.names[int(box.cls[0])].lower()
            conf = float(box.conf[0])
            x1, y1, x2, y2 = map(int, box.xyxy[0])

            if conf < 0.25:
                continue

            if "person" in label:
                hx = int((x1 + x2) / 2)
                hy = int(y2)
                last_detected_humans.append((hx, hy, (x1, y1, x2, y2), conf))
            else:
                last_detected_appliances.append((label, (x1, y1, x2, y2), conf))

        # Check occupancy for each zone
        for key, data in APPLIANCE_ZONES.items():
            zx, zy = data["pos"]
            is_occupied = False

            for (hx, hy, _, _) in last_detected_humans:
                if math.hypot(hx - zx, hy - zy) < PROXIMITY_RADIUS:
                    is_occupied = True
                    break

            data["active"] = is_occupied

        # Sync states to ESP32
        send_esp32_command(APPLIANCE_ZONES)
        print(f"[STATUS] Scan complete. Sleeping AI for {int(SCAN_INTERVAL_SEC)}s...")

    # =========================================================================
    # 🎨 RENDER VISUALS (Cached detections during 10-sec sleep)
    # =========================================================================
    # 1. Draw Humans
    for (hx, hy, (x1, y1, x2, y2), conf) in last_detected_humans:
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
        cv2.circle(frame, (hx, hy), 6, (0, 0, 255), -1)
        cv2.putText(frame, f"Human {conf:.2f}", (x1, y1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)

    # 2. Draw Appliances
    for (label, (x1, y1, x2, y2), conf) in last_detected_appliances:
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
        cv2.putText(frame, f"{label.upper()} {conf:.2f}", (x1, y1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

    # 3. Draw Appliance Zones
    for key, data in APPLIANCE_ZONES.items():
        zx, zy = data["pos"]
        color = (0, 255, 0) if data["active"] else (128, 128, 128)
        cv2.circle(frame, (zx, zy), 40, color, 2)
        status_txt = f"{data['name']}: {'ON' if data['active'] else 'OFF'}"
        cv2.putText(frame, status_txt, (zx - 60, zy - 45),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    # 4. Display Status Banners
    banner_bg = (30, 30, 30)
    cv2.rectangle(frame, (10, 10), (480, 50), banner_bg, -1)
    status_msg = f"Mobile Cam | Next Scan: {remaining_time:.1f}s"
    cv2.putText(frame, status_msg, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)

    cv2.imshow(window_name, frame)

    # =========================================================================
    # 🚪 SOLID QUIT LOGIC
    # =========================================================================
    key = cv2.waitKey(20) & 0xFF
    if key in [ord('q'), ord('Q'), 27]: # 27 = ESC key
        print("\n[USER EXIT] Quit requested via keyboard.")
        break

    if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
        print("\n[USER EXIT] Window closed by user.")
        break

if cap is not None:
    cap.release()
cv2.destroyAllWindows()
print("[SHUTDOWN] System closed cleanly.")