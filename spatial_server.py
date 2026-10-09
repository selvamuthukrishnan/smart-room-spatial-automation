import cv2
import time
import math
import requests
from ultralytics import YOLO

# =================================================================================
# PROJECT: Spatial AI Power Automation (10-Sec Power Efficient Scanner)
# =================================================================================

ESP32_IP = "http://192.168.1.50"
SCAN_INTERVAL_SEC = 10.0   # Exactly 1 frame analyzed every 10 seconds
PROXIMITY_RADIUS = 280     # Proximity radius in pixels

print("[AI SERVER] Initializing YOLO-World Model...")
model = YOLO("yolov8s-world.pt")
model.set_classes(["person", "ceiling fan", "tube light"])

# Predefined Ceiling Appliance Zones
APPLIANCE_ZONES = {
    "fan_1": {"pos": (330, 250), "name": "FAN 1 (LEFT)",   "active": False},
    "fan_2": {"pos": (640, 230), "name": "FAN 2 (CENTER)", "active": False},
    "light": {"pos": (740, 260), "name": "TUBE LIGHT",     "active": False}
}

cap = cv2.VideoCapture(0)
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
    ret, frame = cap.read()
    if not ret:
        time.sleep(0.1)
        continue

    current_time = time.time()
    time_since_last_scan = current_time - last_scan_time
    remaining_time = max(0.0, SCAN_INTERVAL_SEC - time_since_last_scan)

    # =========================================================================
    # ⚡ 10-SECOND AI SCAN TRIGGER (Runs ONLY once every 10 seconds)
    # =========================================================================
    if time_since_last_scan >= SCAN_INTERVAL_SEC:
        print(f"\n[AI SCAN TRIGGER] Scanning frame at {time.strftime('%H:%M:%S')}...")
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
        print(f"[STATUS] Scan complete. Sleeping AI for {int(SCAN_INTERVAL_SEC)} seconds...")

    # =========================================================================
    # 🎨 RENDER VISUALS (Uses cached detection during 10-sec sleep)
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

    # 4. Display 10-Second Countdown & Power Efficiency Banner
    banner_bg = (30, 30, 30)
    cv2.rectangle(frame, (10, 10), (450, 50), banner_bg, -1)
    status_msg = f"Next AI Scan: {remaining_time:.1f}s | Mode: ECO"
    cv2.putText(frame, status_msg, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)

    cv2.imshow(window_name, frame)

    # =========================================================================
    # 🚪 SOLID QUIT LOGIC ('q', 'Q', 'ESC', or Window Close 'X')
    # =========================================================================
    key = cv2.waitKey(20) & 0xFF
    if key in [ord('q'), ord('Q'), 27]: # 27 = ESC key
        print("\n[USER EXIT] Quit requested via keyboard.")
        break

    # If user clicked the window's top-right 'X' button
    if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
        print("\n[USER EXIT] Window closed by user.")
        break

cap.release()
cv2.destroyAllWindows()
print("[SHUTDOWN] System closed cleanly.")