import os
import cv2
import time
import math
import socket
import threading
import requests
import numpy as np
from flask import Flask, Response, jsonify, request
from ultralytics import YOLO

# =================================================================================
# PROJECT: Spatial AI Smart Room - Central Server with index.html Digital Twin
# =================================================================================

def get_local_ip():
    """Dynamically finds the laptop's actual IP address on Wi-Fi / Hotspot network"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()

# --- 📱 CAMERA & ESP32 CONFIGURATION ---
# Change to your phone's IP Webcam URL e.g. "http://192.168.43.1:8080/video", or 0 for webcam
CAMERA_SOURCE = 0  
ESP32_IP = "http://192.168.43.125"

# --- 🎯 CLASSROOM APPLIANCES REGISTRY ---
APPLIANCES = {
    "fan_top_left": {
        "name": "Fan 1 (Top Left)",
        "type": "fan",
        "roi": (25, 200, 235, 220),
        "zone_centroid": (150, 480),
        "vision_state": "OFF",
        "control_state": False
    },
    "fan_top_center": {
        "name": "Fan 2 (Top Center)",
        "type": "fan",
        "roi": (415, 200, 230, 225),
        "zone_centroid": (530, 480),
        "vision_state": "OFF",
        "control_state": False
    },
    "fan_top_right": {
        "name": "Fan 3 (Top Right)",
        "type": "fan",
        "roi": (860, 190, 230, 230),
        "zone_centroid": (970, 480),
        "vision_state": "OFF",
        "control_state": False
    },
    "fan_mid_left": {
        "name": "Fan 4 (Row 2 Left)",
        "type": "fan",
        "roi": (260, 500, 130, 130),
        "zone_centroid": (320, 650),
        "vision_state": "OFF",
        "control_state": False
    },
    "fan_mid_center": {
        "name": "Fan 5 (Row 2 Center)",
        "type": "fan",
        "roi": (515, 500, 140, 135),
        "zone_centroid": (580, 650),
        "vision_state": "OFF",
        "control_state": False
    },
    "fan_mid_right": {
        "name": "Fan 6 (Row 2 Right)",
        "type": "fan",
        "roi": (805, 510, 155, 140),
        "zone_centroid": (880, 650),
        "vision_state": "OFF",
        "control_state": False
    },
    "light_left": {
        "name": "Light 1 (Wall Lamp Left)",
        "type": "light",
        "roi": (80, 520, 95, 110),
        "zone_centroid": (150, 650),
        "vision_state": "OFF",
        "control_state": False
    },
    "light_center_tube": {
        "name": "Light 2 (Center Tube Light)",
        "type": "light",
        "roi": (740, 485, 210, 45),
        "zone_centroid": (840, 600),
        "vision_state": "OFF",
        "control_state": False
    }
}

# 10 Workstation Units State for index.html Digital Twin
WORKSTATION_UNITS = [False] * 10

# --- GLOBAL THREADING STATE ---
latest_frame = None
prev_gray_frame = None
lock = threading.Lock()
PROXIMITY_RADIUS = 280
SCAN_INTERVAL_SEC = 10.0
last_scan_time = 0
humans_detected_count = 0
remaining_time_global = 10.0

# --- INITIALIZE FLASK SERVER TO SERVE index.html ---
app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/")
@app.route("/index.html")
@app.route("/dashboard")
@app.route("/dashboard.html")
def serve_index_html():
    """Serves the actual index.html Digital Twin dashboard from project folder"""
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(content, mimetype="text/html")
    return "Error: index.html not found in project folder", 404

def generate_video_stream():
    """Live MJPEG video streaming for index.html <img id='live-stream-img'>"""
    while True:
        with lock:
            if latest_frame is None:
                time.sleep(0.04)
                continue
            ret, buffer = cv2.imencode(".jpg", latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ret:
                time.sleep(0.04)
                continue
            frame_bytes = buffer.tobytes()

        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")
        time.sleep(0.04)

@app.route("/video_feed")
def video_feed():
    return Response(generate_video_stream(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/api/status")
@app.route("/status")
def api_status():
    """Unified API consumed by index.html and ESP32"""
    with lock:
        unit1_active = APPLIANCES["fan_top_left"]["control_state"] or APPLIANCES["light_left"]["control_state"] or WORKSTATION_UNITS[0]
        unit2_active = APPLIANCES["fan_top_center"]["control_state"] or APPLIANCES["light_center_tube"]["control_state"] or WORKSTATION_UNITS[1]

        active_count = sum(1 for u in WORKSTATION_UNITS if u)
        energy_saved = int(round((1.0 - (max(active_count, 1) / 10.0)) * 100))

        return jsonify({
            "units": WORKSTATION_UNITS,
            "unit_1": {"active": unit1_active, "name": "Workstation 01 (Hardware Relay 1)"},
            "unit_2": {"active": unit2_active, "name": "Workstation 02 (Hardware Relay 2)"},
            "relay_1": unit1_active,
            "relay_2": unit2_active,
            "active_units": active_count,
            "energy_saved_percent": energy_saved,
            "humans_detected": humans_detected_count,
            "scan_seconds_remaining": f"{remaining_time_global:.1f}",
            "esp32_ip": ESP32_IP,
            "appliances": APPLIANCES
        })

@app.route("/api/update", methods=["GET", "POST"])
@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    global WORKSTATION_UNITS
    with lock:
        if request.is_json:
            data = request.json
            if "appliance" in data:
                key = data["appliance"]
                if key in APPLIANCES:
                    APPLIANCES[key]["control_state"] = not APPLIANCES[key]["control_state"]
            if "unit" in data:
                uid = int(data["unit"])
                if 0 <= uid < 10:
                    WORKSTATION_UNITS[uid] = not WORKSTATION_UNITS[uid]
        elif request.args:
            for k, v in request.args.items():
                if k.startswith("unit_"):
                    try:
                        idx = int(k.split("_")[1]) - 1
                        if 0 <= idx < 10:
                            WORKSTATION_UNITS[idx] = (v.lower() == "on")
                    except Exception:
                        pass
    return jsonify({"success": True})

def start_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

# Start web server thread
flask_thread = threading.Thread(target=start_flask, daemon=True)
flask_thread.start()

# --- VISION ON / OFF DETECTION ENGINES ---
def detect_fan_spinning(curr_gray, prev_gray, roi):
    x, y, w, h = roi
    fh, fw = curr_gray.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(fw, x + w), min(fh, y + h)

    if x2 <= x1 or y2 <= y1:
        return "OFF"

    crop_curr = curr_gray[y1:y2, x1:x2]
    crop_prev = prev_gray[y1:y2, x1:x2]

    diff = cv2.absdiff(crop_curr, crop_prev)
    _, thresh = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)
    motion_score = np.mean(thresh)

    return "ON (SPINNING)" if motion_score > 3.5 else "OFF (STILL)"

def detect_light_illuminated(frame, roi):
    x, y, w, h = roi
    fh, fw = frame.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(fw, x + w), min(fh, y + h)

    if x2 <= x1 or y2 <= y1:
        return "OFF"

    crop = frame[y1:y2, x1:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    
    mean_val = np.mean(gray)
    bright_percentile = np.percentile(gray, 90)

    if mean_val > 175 or bright_percentile > 230:
        return "ON (GLOWING)"
    else:
        return "OFF (DARK)"

def send_esp32_hardware(relay1, relay2):
    try:
        url = f"{ESP32_IP}/control?light={'on' if relay1 else 'off'}&fan={'on' if relay2 else 'off'}"
        requests.get(url, timeout=0.8)
    except Exception:
        pass

# --- MAIN AI COMPUTER VISION LOOP ---
print("\n" + "="*70)
print(" 🚀 SPATIAL AI SMART ROOM - DIGITAL TWIN SERVER ACTIVE")
print("="*70)
print(f" 💻 Local Dashboard:       http://localhost:5000 (Opens index.html)")
print(f" 📱 Mobile / Hotspot Link:  http://{LOCAL_IP}:5000")
print(f" 📹 Live Video Stream:     http://localhost:5000/video_feed")
print(f" 🌐 Target ESP32 Hardware: {ESP32_IP}")
print("-" * 70)
print(" 💡 To view on phone (Same Hotspot/Wi-Fi):")
print(f"    👉 http://{LOCAL_IP}:5000")
print("="*70 + "\n")

print("[AI SERVER] Loading YOLO-World...")
model = YOLO("yolov8s-world.pt")
model.set_classes(["person", "ceiling fan", "tube light", "lamp", "fluorescent light"])

cap = cv2.VideoCapture(CAMERA_SOURCE)
window_name = "Spatial AI Smart Classroom Vision Monitor"
cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

while True:
    ret, frame = cap.read()
    if not ret or frame is None:
        time.sleep(0.1)
        continue

    curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if prev_gray_frame is None:
        prev_gray_frame = curr_gray.copy()

    current_time = time.time()
    time_since_last_scan = current_time - last_scan_time
    remaining_time = max(0.0, SCAN_INTERVAL_SEC - time_since_last_scan)
    remaining_time_global = remaining_time

    # 1. Real-time Physical Vision Status Detection (Every frame)
    with lock:
        for key, item in APPLIANCES.items():
            if item["type"] == "fan":
                item["vision_state"] = detect_fan_spinning(curr_gray, prev_gray_frame, item["roi"])
            elif item["type"] == "light":
                item["vision_state"] = detect_light_illuminated(frame, item["roi"])

    prev_gray_frame = curr_gray.copy()

    # 2. 10-Second Spatial Proximity Scan (Human Detection & Automation)
    if time_since_last_scan >= SCAN_INTERVAL_SEC:
        last_scan_time = current_time
        print(f"\n[AI SCANNER] Evaluating occupancy at {time.strftime('%H:%M:%S')}...")

        results = model(frame, verbose=False)[0]
        detected_humans = []

        for box in results.boxes:
            label = results.names[int(box.cls[0])].lower()
            if "person" in label and float(box.conf[0]) > 0.28:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                hx, hy = int((x1 + x2) / 2), int(y2)
                detected_humans.append((hx, hy))

        with lock:
            humans_detected_count = len(detected_humans)
            for i, (key, item) in enumerate(APPLIANCES.items()):
                zx, zy = item["zone_centroid"]
                occupied = False
                for (hx, hy) in detected_humans:
                    if math.hypot(hx - zx, hy - zy) < PROXIMITY_RADIUS:
                        occupied = True
                        break
                item["control_state"] = occupied
                if i < 10:
                    WORKSTATION_UNITS[i] = occupied

        # Dispatch hardware commands to ESP32
        r1 = APPLIANCES["fan_top_left"]["control_state"] or APPLIANCES["light_left"]["control_state"]
        r2 = APPLIANCES["fan_top_center"]["control_state"] or APPLIANCES["light_center_tube"]["control_state"]
        send_esp32_hardware(r1, r2)

    # 3. Render Visual Overlays on Video Feed
    with lock:
        for key, item in APPLIANCES.items():
            x, y, w, h = item["roi"]
            is_on = "ON" in item["vision_state"]
            color = (0, 255, 0) if is_on else (80, 80, 80)
            
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            cv2.putText(frame, f"{item['name']}: {item['vision_state']}", 
                        (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 2)

            zx, zy = item["zone_centroid"]
            active_color = (0, 255, 255) if item["control_state"] else (60, 60, 60)
            cv2.circle(frame, (zx, zy), 25, active_color, 2)

        # Store latest frame for the index.html live web stream (/video_feed)
        latest_frame = frame.copy()

    # Top Status Banner
    banner_bg = (20, 20, 30)
    cv2.rectangle(frame, (10, 10), (580, 50), banner_bg, -1)
    status_text = f"Dashboard: http://localhost:5000 | Next Scan: {remaining_time:.1f}s"
    cv2.putText(frame, status_text, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 255, 255), 2)

    cv2.imshow(window_name, frame)

    key = cv2.waitKey(20) & 0xFF
    if key in [ord('q'), ord('Q'), 27]:
        break
    if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
        break

cap.release()
cv2.destroyAllWindows()
print("[SHUTDOWN] System exited successfully.")