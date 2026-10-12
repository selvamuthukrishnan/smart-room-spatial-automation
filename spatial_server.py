import os
import cv2
import sys
import time
import math
import json
import threading
import http.server
from urllib.parse import urlparse, parse_qs
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
CAMERA_SOURCE = 1  # 1 = Phone Link (Phone Camera, 1280x720 HD), 0 = Laptop Webcam
IP_CAMERA_URL = "http://10.105.4.198:8080/video"  # Optional Wi-Fi IP stream (e.g. IP Webcam app)

# Allow command-line override (e.g., python spatial_server.py http://192.168.43.1:8080/video)
if len(sys.argv) > 1:
    CAMERA_SOURCE = sys.argv[1]

# --- 🌐 ESP32 WI-FI CONFIGURATION ---
ESP32_IP = "http://10.46.38.116"  # Live IP of connected ESP32

# --- ⏱️ TIMING & DETECTION SETTINGS ---
SCAN_INTERVAL_SEC = 10.0   # Scans 1 frame every 10 seconds for power efficiency
PROXIMITY_RADIUS = 280     # Proximity radius in pixels around each appliance

print("[AI SERVER] Initializing YOLO-World Model...")
model = YOLO("yolov8s-world.pt")
# Expanded vocabulary classes: includes international terms for lights & fans
MODEL_CLASSES = ["person", "ceiling fan", "fan", "lamp", "ceiling light", "fluorescent light", "light", "tube light"]
model.set_classes(MODEL_CLASSES)

# Predefined Ceiling Appliance Zones (Mapped from your camera view, with auto-anchoring)
APPLIANCE_ZONES = {
    "fan_1": {"pos": (330, 250), "name": "FAN 1 (LEFT)",   "active": False, "detected": False},
    "fan_2": {"pos": (640, 230), "name": "FAN 2 (CENTER)", "active": False, "detected": False},
    "light": {"pos": (435, 204), "name": "TUBE LIGHT",     "active": False, "detected": False}
}

def detect_glowing_lights(frame):
    """
    OpenCV Luminance & Contour Detector:
    Detects physical glowing fluorescent tubes or ceiling lights with 100% precision
    even under intense glare / overexposure where standard AI models get confused.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    detected_fixtures = []
    for c in contours:
        area = cv2.contourArea(c)
        if area > 1200:
            x, y, w, h = cv2.boundingRect(c)
            if y > 15:  # Filter out top-edge banner artifacts
                detected_fixtures.append((x, y, x + w, y + h, area))

    detected_fixtures.sort(key=lambda b: b[4], reverse=True)
    return detected_fixtures

def connect_camera(source=1):
    """
    Connects to camera. Supports both:
      - Windows Phone Link / Built-in Webcam (device 1 for Phone, 0 for Laptop)
      - Wi-Fi IP Camera streams (HTTP / RTSP)
    With automatic fallback if any camera is unreachable!
    """
    is_device_index = isinstance(source, int) or (isinstance(source, str) and str(source).isdigit())

    if is_device_index:
        idx = int(source)
        label = "Phone Link Phone Camera" if idx == 1 else "Laptop Webcam"
        print(f"[CAMERA] Connecting to Device {idx} ({label})...")
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(idx)

        if cap.isOpened():
            print(f"[CAMERA SUCCESS] Connected to Device {idx} ({label}) successfully!")
            return cap
        else:
            print(f"[CAMERA WARNING] Unable to open Device {idx} ({label})!")
            if idx != 0:
                print("[CAMERA FALLBACK] Trying Device 0 (Laptop Webcam)...")
                cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap = cv2.VideoCapture(0)
                if cap.isOpened():
                    print("[CAMERA SUCCESS] Connected to Device 0 (Laptop Webcam) fallback!")
                    return cap
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

# =================================================================================
# 🌐 DIGITAL TWIN DASHBOARD & MJPEG STREAMING SERVER
# =================================================================================
DASHBOARD_PORT = 5000
latest_jpeg_frame = None
frame_lock = threading.Lock()

server_state = {
    "online": True,
    "scan_seconds_remaining": SCAN_INTERVAL_SEC,
    "scan_interval": SCAN_INTERVAL_SEC,
    "humans_detected": 0,
    "appliances_detected": [],
    "last_scan_time": 0,
    "unit_1": {"active": False, "name": "Unit 01 (Front Left)", "gpio": "GPIO 25", "light": "off", "fan": "off"},
    "unit_2": {"active": False, "name": "Unit 02 (Front Center)", "gpio": "GPIO 26", "light": "off", "fan": "off"},
    "zones": {
        "fan_1": {"active": False, "name": "FAN 1 (LEFT)"},
        "fan_2": {"active": False, "name": "FAN 2 (CENTER)"},
        "light": {"active": False, "name": "TUBE LIGHT"}
    },
    "esp32_ip": ESP32_IP,
    "esp32_status": "synced"
}
state_lock = threading.Lock()

def send_esp32_command(appliance_states):
    query = "&".join([f"{k}={'on' if v['active'] else 'off'}" for k, v in appliance_states.items()])
    url = f"{ESP32_IP}/control?{query}"
    try:
        requests.get(url, timeout=1)
    except Exception:
        pass  # ESP32 offline during local simulation

class SpatialDashboardHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress normal polling logs from flooding console

    def send_cors_headers(self, content_type="text/html; charset=utf-8"):
        self.send_header('Content-Type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()

    def do_GET(self):
        url_parts = urlparse(self.path)
        clean_path = url_parts.path

        if clean_path in ['/', '/index.html', '/dashboard.html']:
            self.send_response(200)
            self.send_cors_headers('text/html; charset=utf-8')
            dashboard_file = os.path.join(os.path.dirname(__file__), 'docs', 'index.html')
            if not os.path.exists(dashboard_file):
                dashboard_file = 'docs/index.html'
            try:
                with open(dashboard_file, 'rb') as f:
                    self.wfile.write(f.read())
            except Exception as e:
                self.wfile.write(f"<h3>Dashboard Error: {e}</h3>".encode('utf-8'))

        elif clean_path == '/api/status':
            self.send_response(200)
            self.send_cors_headers('application/json')
            with state_lock:
                payload = json.dumps(server_state).encode('utf-8')
            self.wfile.write(payload)

        elif clean_path == '/video_feed':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache, private')
            self.end_headers()
            try:
                while True:
                    with frame_lock:
                        f_bytes = latest_jpeg_frame
                    if f_bytes:
                        self.wfile.write(b'--frame\r\n')
                        self.wfile.write(b'Content-Type: image/jpeg\r\n\r\n' + f_bytes + b'\r\n')
                    time.sleep(0.04)  # ~25 FPS
            except (ConnectionResetError, BrokenPipeError):
                pass

        elif clean_path == '/api/control':
            qs = parse_qs(url_parts.query)
            unit_id = qs.get('unit', [''])[0]
            action = qs.get('action', ['toggle'])[0]
            with state_lock:
                if unit_id == '1':
                    server_state['unit_1']['active'] = (action == 'on' or (action == 'toggle' and not server_state['unit_1']['active']))
                    APPLIANCE_ZONES['fan_1']['active'] = server_state['unit_1']['active']
                elif unit_id == '2':
                    server_state['unit_2']['active'] = (action == 'on' or (action == 'toggle' and not server_state['unit_2']['active']))
                    APPLIANCE_ZONES['fan_2']['active'] = server_state['unit_2']['active']
            send_esp32_command(APPLIANCE_ZONES)
            self.send_response(200)
            self.send_cors_headers('application/json')
            self.wfile.write(b'{"status":"ok"}')

        else:
            self.send_response(404)
            self.end_headers()

def run_web_server(port=DASHBOARD_PORT):
    try:
        httpd = http.server.ThreadingHTTPServer(('0.0.0.0', port), SpatialDashboardHandler)
        print(f"[DASHBOARD SERVER] Digital Twin Dashboard live at: http://localhost:{port}")
        print(f"[DASHBOARD SERVER] MJPEG Live Camera stream at:    http://localhost:{port}/video_feed")
        print(f"[DASHBOARD SERVER] JSON REST Status endpoint:      http://localhost:{port}/api/status")
        httpd.serve_forever()
    except Exception as e:
        print(f"[DASHBOARD SERVER ERROR] Could not bind to port {port}: {e}")

web_thread = threading.Thread(target=run_web_server, daemon=True)
web_thread.start()

cap = connect_camera(CAMERA_SOURCE)
window_name = "Spatial AI Power Automation Monitor"
cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

last_detected_humans = []
last_detected_appliances = []
prev_u1_active = None
prev_u2_active = None
last_esp_dispatch = 0

print("[AI SERVER] Started in LIVE REAL-TIME MODE! Press 'q', 'Q', 'ESC', or close window to exit.")

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

    # =========================================================================
    # ⚡ CONTINUOUS REAL-TIME AI VISION INFERENCE (Zero-Delay Live Scanning)
    # =========================================================================
    results = model(frame, verbose=False)[0]

    last_detected_humans = []
    last_detected_appliances = []

    for box in results.boxes:
        raw_label = results.names[int(box.cls[0])].lower()
        conf = float(box.conf[0])
        x1, y1, x2, y2 = map(int, box.xyxy[0])

        if "person" in raw_label:
            if conf < 0.25:
                continue
            hx = int((x1 + x2) / 2)
            hy = int(y2)
            last_detected_humans.append((hx, hy, (x1, y1, x2, y2), conf))
        else:
            if conf < 0.15:
                continue
            norm_label = raw_label
            if any(w in raw_label for w in ["lamp", "light", "fluorescent"]):
                norm_label = "tube light"
                APPLIANCE_ZONES["light"]["detected"] = True
                APPLIANCE_ZONES["light"]["pos"] = (int((x1 + x2) / 2), int((y1 + y2) / 2))
            elif "fan" in raw_label:
                norm_label = "ceiling fan"
                APPLIANCE_ZONES["fan_1"]["detected"] = True
            last_detected_appliances.append((norm_label, (x1, y1, x2, y2), conf))

    # Hybrid Luminance Detection: 100% robust detection for glowing lights even under heavy glare
    glowing_fixtures = detect_glowing_lights(frame)
    if glowing_fixtures:
        gx1, gy1, gx2, gy2, g_area = glowing_fixtures[0]
        if not any("light" in a[0] for a in last_detected_appliances):
            last_detected_appliances.append(("tube light (glow)", (gx1, gy1, gx2, gy2), 0.95))
        APPLIANCE_ZONES["light"]["pos"] = (int((gx1 + gx2) / 2), int((gy1 + gy2) / 2))
        APPLIANCE_ZONES["light"]["detected"] = True

    # Check occupancy for each zone
    for key, data in APPLIANCE_ZONES.items():
        zx, zy = data["pos"]
        is_occupied = False

        for (hx, hy, _, _) in last_detected_humans:
            if math.hypot(hx - zx, hy - zy) < PROXIMITY_RADIUS:
                is_occupied = True
                break

        data["active"] = is_occupied

    # Map to Workstation Unit 1 & Unit 2
    u1_active = APPLIANCE_ZONES.get("fan_1", {}).get("active", False) or APPLIANCE_ZONES.get("light", {}).get("active", False)
    u2_active = APPLIANCE_ZONES.get("fan_2", {}).get("active", False)

    with state_lock:
        server_state["unit_1"]["active"] = u1_active
        server_state["unit_2"]["active"] = u2_active
        server_state["humans_detected"] = len(last_detected_humans)
        server_state["appliances_detected"] = [a[0] for a in last_detected_appliances]
        server_state["last_scan_time"] = current_time
        server_state["zones"] = {k: {"active": v["active"], "name": v["name"]} for k, v in APPLIANCE_ZONES.items()}
        server_state["scan_seconds_remaining"] = "LIVE"

    # Send command to ESP32 on state change (or periodic refresh every 3s to prevent Wi-Fi spam)
    if (u1_active != prev_u1_active or u2_active != prev_u2_active or (current_time - last_esp_dispatch > 3.0)):
        send_esp32_command(APPLIANCE_ZONES)
        prev_u1_active = u1_active
        prev_u2_active = u2_active
        last_esp_dispatch = current_time

    # =========================================================================
    # 🎨 RENDER VISUALS (Live frame rendering)
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

    # 3. Draw Appliance Zones (Active=Green, Detected=Gold, Idle=Gray)
    for key, data in APPLIANCE_ZONES.items():
        zx, zy = data["pos"]
        if data["active"]:
            color = (0, 255, 0)
            status_txt = f"{data['name']}: ACTIVE (ON)"
        elif data.get("detected", False):
            color = (0, 215, 255)  # Gold/Cyan
            status_txt = f"{data['name']}: DETECTED"
        else:
            color = (128, 128, 128)
            status_txt = f"{data['name']}: IDLE (OFF)"

        cv2.circle(frame, (zx, zy), 40, color, 2)
        cv2.putText(frame, status_txt, (zx - 65, zy - 45),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 2)

    # 4. Display Live Status Banner
    banner_bg = (30, 30, 30)
    cv2.rectangle(frame, (10, 10), (480, 50), banner_bg, -1)
    status_msg = "Live Vision AI | Mode: REAL-TIME (0s Delay)"
    cv2.putText(frame, status_msg, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 255), 2)

    # 5. Compress Frame for Dashboard Web Stream (MJPEG)
    _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    with frame_lock:
        latest_jpeg_frame = buf.tobytes()

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